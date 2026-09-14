import json
import os

from dotenv import load_dotenv

from app.graph import (
    build_unlocks_map,
    eligible_courses,
    load_courses,
    requirement_status,
)
from app.profile import StudentProfile, normalize_course_code


MODEL = "gemini-3.8-flash"
MAX_TOOL_ROUNDS = 5


# Gemini handles natural-language interpretation and tool selection.
# Course facts and eligibility decisions always come from the dataset
# and deterministic Python tools below.
SYSTEM_INSTRUCTION = """You are a course-planning assistant.

The provided tools, structured course dataset, and student profile are the source of truth for course requirements and eligibility.

Eligibility means only that the prerequisite and corequisite rules represented in the selected dataset are satisfied. Never imply that this guarantees official registration eligibility.

Never use your own memory or general knowledge to make factual claims about prerequisites, corequisites, or eligibility.

Use the appropriate tool before answering a course-specific requirement or eligibility question.

If the requested course is not present in the dataset, clearly state that it is not currently supported in this dataset.

Do not invent prerequisites, corequisites, course availability, degree requirements, schedules, or course information.

A dependent course is a course that references another course somewhere in its prerequisite expression. This does not necessarily mean the dependent course is immediately eligible.

When stating course facts, only use information returned by the tools. The dataset may intentionally cover only part of an institution's catalogue.

Keep final answers concise and clear."""


# These schemas are exposed to Gemini. The model chooses which tool to call,
# but it never receives control over the underlying course logic.
TOOLS = [
    {
        "type": "function",
        "name": "check_eligibility",
        "description": (
            "Check whether the student's completed and current courses satisfy "
            "the prerequisite and corequisite rules represented in the dataset."
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
        "name": "get_course_requirements",
        "description": (
            "Get the complete prerequisite and corequisite rules stored for "
            "a supported course, along with its dataset metadata."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "course_code": {
                    "type": "string",
                    "description": "The course code to look up, e.g. 'CMPUT 204'.",
                },
            },
            "required": ["course_code"],
        },
    },
    {
        "type": "function",
        "name": "get_missing_requirements",
        "description": (
            "Get any prerequisite and corequisite requirements the student "
            "is missing, preserving nested AND/OR structure."
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
            "List supported courses whose prerequisite/corequisite rules "
            "are satisfied by the student's profile. Completed and current "
            "courses are excluded."
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
            "List supported courses whose prerequisite expression references "
            "a given course. This does not mean those courses are immediately eligible."
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


def _coerce_profile(profile) -> StudentProfile:
    # Internally the agent always works with StudentProfile, but keeping these
    # shortcuts avoids breaking callers that used the older list-based API.
    if isinstance(profile, StudentProfile):
        return profile

    if isinstance(profile, dict):
        return StudentProfile.from_dict(profile)

    return StudentProfile.from_dict({
        "completed_courses": profile,
    })


def _handle_check_eligibility(
    args: dict,
    profile: StudentProfile,
    courses: dict,
    unlocks: dict,
) -> dict:
    course_code = normalize_course_code(args.get("course_code", ""))

    return requirement_status(
        course_code,
        set(profile.completed_courses),
        set(profile.current_courses),
        courses,
    )


def _handle_get_course_requirements(
    args: dict,
    profile: StudentProfile,
    courses: dict,
    unlocks: dict,
) -> dict:
    course_code = normalize_course_code(args.get("course_code", ""))

    if course_code not in courses:
        return {
            "course": course_code,
            "known": False,
        }

    data = courses[course_code]

    # Return the raw requirement tree so Gemini can explain it without
    # reconstructing or guessing any course facts.
    result = {
        "course": course_code,
        "known": True,
        "title": data.get("title"),
        "units": data.get("units"),
        "prerequisites": data.get("prereqs", {"and": []}),
        "corequisites": data.get("coreqs", {"and": []}),
    }

    # Source metadata is optional for custom datasets.
    for key in ("source", "verified"):
        if key in data:
            result[key] = data[key]

    return result


def _handle_get_missing_requirements(
    args: dict,
    profile: StudentProfile,
    courses: dict,
    unlocks: dict,
) -> dict:
    course_code = normalize_course_code(args.get("course_code", ""))

    return requirement_status(
        course_code,
        set(profile.completed_courses),
        set(profile.current_courses),
        courses,
    )


def _handle_get_eligible_courses(
    args: dict,
    profile: StudentProfile,
    courses: dict,
    unlocks: dict,
) -> dict:
    return {
        "eligible_courses": eligible_courses(
            set(profile.completed_courses),
            courses,
            set(profile.current_courses),
        )
    }


def _handle_get_dependent_courses(
    args: dict,
    profile: StudentProfile,
    courses: dict,
    unlocks: dict,
) -> dict:
    course_code = normalize_course_code(args.get("course_code", ""))

    if course_code not in courses:
        return {
            "course": course_code,
            "known": False,
            "dependent_courses": [],
        }

    return {
        "course": course_code,
        "known": True,
        "dependent_courses": sorted(
            unlocks.get(course_code, set())
        ),
    }


# Keeping dispatch in one table makes adding another deterministic tool
# independent from the Gemini interaction loop.
TOOL_HANDLERS = {
    "check_eligibility": _handle_check_eligibility,
    "get_course_requirements": _handle_get_course_requirements,
    "get_missing_requirements": _handle_get_missing_requirements,
    "get_eligible_courses": _handle_get_eligible_courses,
    "get_dependent_courses": _handle_get_dependent_courses,
}


_client = None


def _get_client():
    global _client

    # Reuse the client instead of recreating it for every question.
    if _client is not None:
        return _client

    load_dotenv()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to your environment or .env file."
        )

    # Import lazily so graph/profile tests can run without requiring
    # the Gemini SDK to be imported first.
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is not installed. Run: pip install -r requirements.txt"
        ) from exc

    _client = genai.Client(api_key=api_key)
    return _client


def _run_tool_call(
    name: str,
    arguments,
    profile: StudentProfile,
    courses: dict,
    unlocks: dict,
):
    handler = TOOL_HANDLERS.get(name)

    if handler is None:
        return {
            "error": f"unknown tool: {name}",
        }

    # Gemini normally returns a dict, but accepting JSON strings makes
    # the dispatcher a little more defensive against malformed responses.
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            return {
                "error": f"malformed arguments for tool {name}",
            }

    if not isinstance(arguments, dict):
        return {
            "error": f"malformed arguments for tool {name}",
        }

    try:
        return handler(
            arguments,
            profile,
            courses,
            unlocks,
        )
    except (KeyError, TypeError, ValueError) as exc:
        # Tool failures are returned to the model as data instead of
        # crashing the entire interaction.
        return {
            "error": f"tool {name} failed: {exc}",
        }


def ask(
    question: str,
    student_profile,
    dataset_path=None,
    trace=False,
) -> str:
    # Load all deterministic state before contacting Gemini.
    try:
        profile = _coerce_profile(student_profile)
        courses = load_courses(dataset_path)
        unlocks = build_unlocks_map(courses)
    except (TypeError, ValueError) as exc:
        return f"Configuration error: {exc}"

    try:
        client = _get_client()
    except RuntimeError as exc:
        return str(exc)

    # The first model call contains the user's question and available tools.
    try:
        interaction = client.interactions.create(
            model=MODEL,
            input=question,
            system_instruction=SYSTEM_INSTRUCTION,
            tools=TOOLS,
        )
    except Exception as exc:
        return (
            "Sorry, I couldn't reach the course-planning assistant "
            f"right now: {exc}"
        )

    # Gemini may need several tool calls before it has enough information
    # to produce a final natural-language answer.
    for _ in range(MAX_TOOL_ROUNDS):
        function_call_steps = [
            step
            for step in (interaction.steps or [])
            if step.type == "function_call"
        ]

        # No function calls means Gemini has finished reasoning with the
        # tool results and should now have a final answer.
        if not function_call_steps:
            if interaction.output_text:
                return interaction.output_text

            return (
                "I received an unexpected response and couldn't "
                "produce an answer."
            )

        function_results = []

        for step in function_call_steps:
            result = _run_tool_call(
                step.name,
                step.arguments,
                profile,
                courses,
                unlocks,
            )

            # Trace mode is useful for demos and debugging because it shows
            # exactly which deterministic tools Gemini chose to call.
            if trace:
                print(f"-> tool: {step.name}({step.arguments})")
                print(
                    f"<- result: {json.dumps(result, sort_keys=True)}"
                )

            function_results.append({
                "type": "function_result",
                "name": step.name,
                "call_id": step.id,
                "result": [{
                    "type": "text",
                    "text": json.dumps(result),
                }],
            })

        # Continue the same interaction and give Gemini only the actual
        # results produced by our deterministic tools.
        try:
            interaction = client.interactions.create(
                model=MODEL,
                previous_interaction_id=interaction.id,
                tools=TOOLS,
                input=function_results,
            )
        except Exception as exc:
            return (
                "Sorry, I couldn't reach the course-planning assistant "
                f"right now: {exc}"
            )

    # Prevent a malformed interaction from creating an endless tool loop.
    return (
        "I wasn't able to complete that request within the allowed "
        "number of tool rounds."
    )