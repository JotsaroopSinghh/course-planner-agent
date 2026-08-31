import json
import os
import re

from dotenv import load_dotenv
from google import genai

from app.graph import (
    build_unlocks_map,
    eligible_courses,
    is_eligible,
    load_courses,
    missing_prerequisites,
)

MODEL = "gemini-3.7-flash"
MAX_TOOL_ROUNDS = 5

SYSTEM_INSTRUCTION = """You are a University of Alberta course-planning assistant.

The provided graph tools and structured course dataset are the source of truth for prerequisites and course eligibility.

Never use your own memory or general knowledge to make factual claims about course prerequisites or eligibility.

Use the appropriate tool before answering a course-specific prerequisite or eligibility question.

If the requested course is not present in the dataset, clearly state that it is not currently supported.

Do not invent prerequisites, course availability, degree requirements, schedules or course information.

A dependent course is a course that references another course somewhere in its prerequisite expression. This does not necessarily mean the dependent course is immediately eligible.
When stating course facts, only use information returned by the tools. Do not add, infer or expand course titles, descriptions or prerequisite information from your own knowledge.

The course dataset is intentionally incomplete. If a tool reports that a course is unknown, say that the course is "not currently supported in this dataset." Do not claim that the course does not exist or is not recognized by the University of Alberta.

Keep final answers concise and clear."""

TOOLS = [
    {
        "type": "function",
        "name": "check_eligibility",
        "description": (
            "Check whether the student is currently eligible to take a course, "
            "based on the student's real completed-course record."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "course_code": {
                    "type": "string",
                    "description": "The course code to check, e.g. 'CMPUT 204'.",
                },
            },
            "required": ["course_code"],
        },
    },
    {
        "type": "function",
        "name": "get_missing_prerequisites",
        "description": (
            "Get the prerequisites the student still needs to complete a course, "
            "preserving the nested AND/OR structure of the requirement."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "course_code": {
                    "type": "string",
                    "description": "The course code to check, e.g. 'CMPUT 204'.",
                },
            },
            "required": ["course_code"],
        },
    },
    {
        "type": "function",
        "name": "get_eligible_courses",
        "description": (
            "List the courses the student is currently eligible to take, "
            "based on the student's real completed-course record. "
            "Already completed courses are excluded."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "type": "function",
        "name": "get_dependent_courses",
        "description": (
            "List the dependent courses for a given course: courses whose "
            "prerequisite expression references this course somewhere. "
            "This does not mean those dependent courses are immediately eligible."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "course_code": {
                    "type": "string",
                    "description": "The course code to look up, e.g. 'CMPUT 272'.",
                },
            },
            "required": ["course_code"],
        },
    },
]

_courses = None
_unlocks_map = None


def _get_courses():
    global _courses
    if _courses is None:
        _courses = load_courses()
    return _courses


def _get_unlocks_map():
    global _unlocks_map
    if _unlocks_map is None:
        _unlocks_map = build_unlocks_map(_get_courses())
    return _unlocks_map


def normalize_course_code(course_code):
    # removes whitespace and uppercases eg "cmput  204" -> "CMPUT 204",
    # without guessing malformed course codes.
    if not isinstance(course_code, str):
        return course_code
    return re.sub(r"\s+", " ", course_code.strip()).upper()


def _normalize_completed_courses(completed_courses):
    if completed_courses is None:
        return set()

    if isinstance(completed_courses, str):
        completed_courses = completed_courses.split(",")

    return {
        normalize_course_code(course)
        for course in completed_courses
        if isinstance(course, str) and course.strip()
    }

def _handle_check_eligibility(args: dict, completed: set) -> dict:
    course_code = normalize_course_code(args.get("course_code", ""))
    courses = _get_courses()
    if course_code not in courses:
        return {"course": course_code, "known": False, "eligible": False}
    return {
        "course": course_code,
        "known": True,
        "eligible": is_eligible(course_code, completed, courses),
    }


def _handle_get_missing_prerequisites(args: dict, completed: set) -> dict:
    course_code = normalize_course_code(args.get("course_code", ""))
    courses = _get_courses()
    return missing_prerequisites(course_code, completed, courses)


def _handle_get_eligible_courses(args: dict, completed: set) -> dict:
    courses = _get_courses()
    return {"eligible_courses": eligible_courses(completed, courses)}


def _handle_get_dependent_courses(args: dict, completed: set) -> dict:
    course_code = normalize_course_code(args.get("course_code", ""))
    courses = _get_courses()
    if course_code not in courses:
        return {"course": course_code, "known": False, "dependent_courses": []}
    unlocks = _get_unlocks_map()
    return {
        "course": course_code,
        "known": True,
        "dependent_courses": sorted(unlocks.get(course_code, set())),
    }


TOOL_HANDLERS = {
    "check_eligibility": _handle_check_eligibility,
    "get_missing_prerequisites": _handle_get_missing_prerequisites,
    "get_eligible_courses": _handle_get_eligible_courses,
    "get_dependent_courses": _handle_get_dependent_courses,
}

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client

    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to your environment or .env file."
        )
    _client = genai.Client(api_key=api_key)
    return _client


def _run_tool_call(name: str, arguments, completed: set):
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return {"error": f"unknown tool: {name}"}

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            return {"error": f"malformed arguments for tool {name}"}
    if not isinstance(arguments, dict):
        return {"error": f"malformed arguments for tool {name}"}

    try:
        return handler(arguments, completed)
    except (KeyError, TypeError, ValueError) as exc:
        return {"error": f"tool {name} failed: {exc}"}


def ask(question: str, completed_courses) -> str:
    completed = _normalize_completed_courses(completed_courses)
    try:
        client = _get_client()
    except RuntimeError as exc:
        return str(exc)

    try:
        interaction = client.interactions.create(
            model=MODEL,
            input=question,
            system_instruction=SYSTEM_INSTRUCTION,
            tools=TOOLS,
        )
    except Exception as exc: 
        return f"Sorry, I couldn't reach the course-planning assistant right now: {exc}"

    for _ in range(MAX_TOOL_ROUNDS):
        function_call_steps = [
            step for step in (interaction.steps or []) if step.type == "function_call"
        ]

        if not function_call_steps:
            if interaction.output_text:
                return interaction.output_text
            return "I received an unexpected response and couldn't produce an answer."

        function_results = []
        for step in function_call_steps:
            result = _run_tool_call(step.name, step.arguments, completed)
            function_results.append(
                {
                    "type": "function_result",
                    "name": step.name,
                    "call_id": step.id,
                    "result": [
                        {
                            "type": "text",
                            "text": json.dumps(result),
                        }
                    ],
                }
            )

        try:
            interaction = client.interactions.create(
                model=MODEL,
                previous_interaction_id=interaction.id,
                tools=TOOLS,
                input=function_results,
            )
        except Exception as exc: 
            return f"Sorry, I couldn't reach the course-planning assistant right now: {exc}"

    return (
        "I wasn't able to complete that request within the allowed number "
        "of tool rounds."
    )