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

def collect_course_codes(rule) -> set:
    # walks the rule tree and just grabs every course code in it,
    # doesn't care about and/or logic, just need the flat list
    if isinstance(rule, str):
        return {rule}
    if "course" in rule:
        return {rule["course"]}
    if "and" in rule:
        return set().union(*(collect_course_codes(r) for r in rule["and"]), set())
    if "or" in rule:
        return set().union(*(collect_course_codes(r) for r in rule["or"]), set())
    raise ValueError(f"unknown rule type: {rule}")


def build_unlocks_map(courses: dict) -> dict:
    # courses.json only tells us what each course NEEDS, not what it opens up
    # so we build the reverse here once instead of recalculating it every time
    unlocks = {code: set() for code in courses}
    for code, data in courses.items():
        for prereq in collect_course_codes(data["prereqs"]):
            if prereq in unlocks:  # skip stuff not in our dataset yet
                unlocks[prereq].add(code)
    return unlocks