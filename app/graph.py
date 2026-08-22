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


def has_cycle(courses: dict) -> bool:
    # white/gray/black DFS - gray means "on the current path", so hitting
    # a gray node means we looped back on an ancestor = cycle
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {code: WHITE for code in courses}

    def visit(code):
        color[code] = GRAY
        for prereq in collect_course_codes(courses[code]["prereqs"]):
            if prereq not in color:
                continue  # prereq not in our dataset, nothing to walk into
            if color[prereq] == GRAY:
                return True
            if color[prereq] == WHITE and visit(prereq):
                return True
        color[code] = BLACK
        return False

    return any(color[code] == WHITE and visit(code) for code in courses)


def topological_order(courses: dict) -> list:
    # Kahn's algorithm: peel off nodes with no remaining prereqs, one layer
    # at a time. in_degree here = "how many prereqs (in our dataset) does
    # this course still have left"
    unlocks = build_unlocks_map(courses)
    in_degree = {
        code: len(collect_course_codes(data["prereqs"]) & courses.keys())
        for code, data in courses.items()
    }

    queue = [code for code, deg in in_degree.items() if deg == 0]
    order = []
    while queue:
        code = queue.pop(0)
        order.append(code)
        for unlocked in unlocks[code]:
            in_degree[unlocked] -= 1
            if in_degree[unlocked] == 0:
                queue.append(unlocked)

    if len(order) != len(courses):
        # leftover nodes never hit in_degree 0 - only happens if there's a cycle
        raise ValueError("cycle detected, no valid topological order")
    return order