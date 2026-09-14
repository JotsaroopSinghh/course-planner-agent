import json
from pathlib import Path

from app.profile import normalize_course_code


DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parents[1] / "datasets" / "ualberta_cmput.json"
)
EMPTY_RULE = {"and": []}


def load_courses(path=None):
    # Use the bundled UAlberta dataset by default, but allow any dataset
    # following the same schema to be plugged into the engine.
    dataset_path = Path(path) if path else DEFAULT_DATASET_PATH

    try:
        with dataset_path.open(encoding="utf-8") as f:
            courses = json.load(f)
    except FileNotFoundError as exc:
        raise ValueError(f"course dataset not found: {dataset_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"course dataset is not valid JSON: {dataset_path}"
        ) from exc

    if not isinstance(courses, dict):
        raise ValueError(
            "course dataset must be a JSON object keyed by course code"
        )

    # Catch malformed rule structures before the graph engine tries to use them.
    validate_dataset(courses)

    # Profiles and datasets should use the same course-code format internally,
    # even if a contributor writes something like "cmput   204" in their JSON.
    normalized = {}

    for raw_code, data in courses.items():
        code = normalize_course_code(raw_code)

        if code in normalized:
            raise ValueError(
                f"duplicate course code after normalization: {code}"
            )

        record = dict(data)
        record["prereqs"] = _normalize_rule(
            record.get("prereqs", EMPTY_RULE)
        )

        if "coreqs" in record:
            record["coreqs"] = _normalize_rule(record["coreqs"])

        normalized[code] = record

    return normalized


def _normalize_rule(rule):
    # Requirement rules are recursive, so course codes need to be normalized
    # all the way down the AND/OR tree.
    if isinstance(rule, str):
        return normalize_course_code(rule)

    if "course" in rule:
        return {"course": normalize_course_code(rule["course"])}

    if "and" in rule:
        return {
            "and": [_normalize_rule(child) for child in rule["and"]]
        }

    if "or" in rule:
        return {
            "or": [_normalize_rule(child) for child in rule["or"]]
        }

    raise ValueError(f"unknown rule type: {rule}")


def validate_rule(rule, location="rule"):
    # A rule can be a plain course code or one recursive course/AND/OR object.
    if isinstance(rule, str):
        if not rule.strip():
            raise ValueError(f"{location} contains an empty course code")
        return

    if not isinstance(rule, dict):
        raise ValueError(
            f"{location} must be a course-code string or rule object"
        )

    # Exactly one operation is allowed per rule object. This also catches
    # misspelled or unsupported fields instead of silently ignoring them.
    rule_keys = [
        key for key in ("course", "and", "or")
        if key in rule
    ]

    if len(rule_keys) != 1 or len(rule) != 1:
        raise ValueError(
            f"{location} must contain exactly one of: course, and, or"
        )

    key = rule_keys[0]

    if key == "course":
        if not isinstance(rule[key], str) or not rule[key].strip():
            raise ValueError(
                f"{location}.course must be a non-empty string"
            )
        return

    children = rule[key]

    if not isinstance(children, list):
        raise ValueError(f"{location}.{key} must be a list")

    # An empty AND is useful for courses with no requirements, but an
    # empty OR would never be satisfiable.
    if key == "or" and not children:
        raise ValueError(
            f"{location}.or must contain at least one option"
        )

    for index, child in enumerate(children):
        validate_rule(child, f"{location}.{key}[{index}]")


def validate_dataset(courses: dict):
    # Validate only the fields the engine depends on. Extra metadata such as
    # titles, source URLs and verification dates can live beside the rules.
    for code, data in courses.items():
        if not isinstance(code, str) or not code.strip():
            raise ValueError(
                "course dataset keys must be non-empty course-code strings"
            )

        if not isinstance(data, dict):
            raise ValueError(
                f"record for {code} must be a JSON object"
            )

        if "title" in data and not isinstance(data["title"], str):
            raise ValueError(f"title for {code} must be a string")

        validate_rule(
            data.get("prereqs", EMPTY_RULE),
            f"{code}.prereqs",
        )

        validate_rule(
            data.get("coreqs", EMPTY_RULE),
            f"{code}.coreqs",
        )


def satisfies(rule, available_courses: set) -> bool:
    # Walk the rule tree recursively until it reaches individual courses.
    if isinstance(rule, str):
        return rule in available_courses

    if not isinstance(rule, dict):
        raise ValueError(f"invalid requirement rule: {rule}")

    if "course" in rule:
        return rule["course"] in available_courses

    if "and" in rule:
        return all(
            satisfies(child, available_courses)
            for child in rule["and"]
        )

    if "or" in rule:
        return any(
            satisfies(child, available_courses)
            for child in rule["or"]
        )

    raise ValueError(f"unknown rule type: {rule}")


def _missing_rule(rule, available_courses: set):
    # This mirrors satisfies(), but returns the unsatisfied parts of the
    # rule tree so the agent can explain what the student is missing.
    if isinstance(rule, str):
        return (
            None
            if rule in available_courses
            else {"type": "course", "course": rule}
        )

    if not isinstance(rule, dict):
        raise ValueError(f"invalid requirement rule: {rule}")

    if "course" in rule:
        course = rule["course"]

        return (
            None
            if course in available_courses
            else {"type": "course", "course": course}
        )

    if "and" in rule:
        missing = [
            item
            for item in (
                _missing_rule(child, available_courses)
                for child in rule["and"]
            )
            if item is not None
        ]

        return {
            "type": "all_of",
            "missing": missing,
        } if missing else None

    if "or" in rule:
        options = [
            _missing_rule(child, available_courses)
            for child in rule["or"]
        ]

        # One satisfied option is enough to satisfy the entire OR branch.
        if any(option is None for option in options):
            return None

        return {
            "type": "one_of",
            "options": options,
        }

    raise ValueError(f"unknown rule type: {rule}")


def requirement_status(
    course_code: str,
    completed: set,
    current: set,
    courses: dict,
) -> dict:
    # Prerequisites must already be completed. Corequisites can also be
    # satisfied by courses the student is currently taking.
    if course_code not in courses:
        return {
            "course": course_code,
            "known": False,
            "eligible": False,
            "prerequisites": None,
            "corequisites": None,
        }

    data = courses[course_code]

    prereq_rule = data.get("prereqs", EMPTY_RULE)
    coreq_rule = data.get("coreqs", EMPTY_RULE)

    prereq_missing = _missing_rule(
        prereq_rule,
        completed,
    )

    coreq_missing = _missing_rule(
        coreq_rule,
        completed | current,
    )

    prereq_status = {
        "satisfied": prereq_missing is None,
        "missing": prereq_missing,
    }

    coreq_status = {
        "satisfied": coreq_missing is None,
        "missing": coreq_missing,
    }

    return {
        "course": course_code,
        "known": True,
        "eligible": (
            prereq_status["satisfied"]
            and coreq_status["satisfied"]
        ),
        "prerequisites": prereq_status,
        "corequisites": coreq_status,
    }


def is_eligible(
    course_code: str,
    completed: set,
    courses: dict,
    current=None,
) -> bool:
    current = set() if current is None else current

    return requirement_status(
        course_code,
        completed,
        current,
        courses,
    )["eligible"]


def missing_prerequisites(
    course_code: str,
    completed: set,
    courses: dict,
) -> dict:
    # Keep the original prerequisite-only interface for existing callers.
    if course_code not in courses:
        return {
            "course": course_code,
            "known": False,
            "satisfied": False,
            "missing": None,
        }

    missing = _missing_rule(
        courses[course_code].get("prereqs", EMPTY_RULE),
        completed,
    )

    return {
        "course": course_code,
        "known": True,
        "satisfied": missing is None,
        "missing": missing,
    }


def eligible_courses(
    completed: set,
    courses: dict,
    current=None,
) -> list:
    current = set() if current is None else current

    # Don't suggest courses the student has completed or is already taking.
    unavailable = completed | current

    return sorted(
        code
        for code in courses
        if code not in unavailable
        and is_eligible(code, completed, courses, current)
    )


def collect_course_codes(rule) -> set:
    # Flatten a rule tree into the course codes it references.
    # AND/OR meaning doesn't matter when building graph connections.
    if isinstance(rule, str):
        return {rule}

    if not isinstance(rule, dict):
        raise ValueError(f"invalid requirement rule: {rule}")

    if "course" in rule:
        return {rule["course"]}

    if "and" in rule:
        return set().union(
            *(
                collect_course_codes(child)
                for child in rule["and"]
            ),
            set(),
        )

    if "or" in rule:
        return set().union(
            *(
                collect_course_codes(child)
                for child in rule["or"]
            ),
            set(),
        )

    raise ValueError(f"unknown rule type: {rule}")


def build_unlocks_map(courses: dict) -> dict:
    # Dataset records point from a course to its prerequisites.
    # Reverse those relationships so we can answer what each course unlocks.
    # Corequisites are not prerequisite dependencies, so they're left out.
    unlocks = {
        code: set()
        for code in courses
    }

    for code, data in courses.items():
        for prereq in collect_course_codes(
            data.get("prereqs", EMPTY_RULE)
        ):
            # References outside the current dataset are valid, but there is
            # no local graph node to connect them to.
            if prereq in unlocks:
                unlocks[prereq].add(code)

    return unlocks


def has_cycle(courses: dict) -> bool:
    # White/gray/black DFS over prerequisite references.
    # Reaching a gray node means we looped back into the current path.
    WHITE, GRAY, BLACK = 0, 1, 2

    color = {
        code: WHITE
        for code in courses
    }

    def visit(code):
        color[code] = GRAY

        for prereq in collect_course_codes(
            courses[code].get("prereqs", EMPTY_RULE)
        ):
            # Requirements outside this dataset aren't graph nodes here.
            if prereq not in color:
                continue

            if color[prereq] == GRAY:
                return True

            if color[prereq] == WHITE and visit(prereq):
                return True

        color[code] = BLACK
        return False

    return any(
        color[code] == WHITE and visit(code)
        for code in sorted(courses)
    )


def topological_order(courses: dict) -> list:
    # Kahn's algorithm over the prerequisite reference graph.
    # Sorting keeps the result deterministic across runs.
    unlocks = build_unlocks_map(courses)

    in_degree = {
        code: len(
            collect_course_codes(
                data.get("prereqs", EMPTY_RULE)
            )
            & courses.keys()
        )
        for code, data in courses.items()
    }

    queue = sorted(
        code
        for code, degree in in_degree.items()
        if degree == 0
    )

    order = []

    while queue:
        code = queue.pop(0)
        order.append(code)

        for unlocked in sorted(unlocks[code]):
            in_degree[unlocked] -= 1

            if in_degree[unlocked] == 0:
                queue.append(unlocked)
                queue.sort()

    # Anything left after Kahn's algorithm belongs to a cycle.
    if len(order) != len(courses):
        raise ValueError(
            "cycle detected, no valid topological order"
        )

    return order