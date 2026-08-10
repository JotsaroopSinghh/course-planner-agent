import json


def load_courses(path="app/data/courses.json"):
    with open(path) as f:
        return json.load(f)


def satisfies(rule, completed: set) -> bool:
    # items inside "and"/"or" lists can be plain course code strings (like "CMPUT 175") or nested rule dicts - handle both

    if isinstance(rule, str):
        return rule in completed
    if "course" in rule:
        return rule["course"] in completed
    if "and" in rule:
        return all(satisfies(r, completed) for r in rule["and"])
    if "or" in rule:
        return any(satisfies(r, completed) for r in rule["or"])
    raise ValueError(f"unknown rule type: {rule}")

def is_eligible(course_code: str, completed: set, courses: dict) -> bool:
    return satisfies(courses[course_code]["prereqs"], completed)