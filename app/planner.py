from app.graph import EMPTY_RULE, requirement_status
from app.profile import StudentProfile, normalize_course_code


def _merge_unique(*sequences):
    # Preserve dependency order while avoiding the same course appearing twice.
    merged = []
    seen = set()

    for sequence in sequences:
        for course in sequence:
            if course not in seen:
                seen.add(course)
                merged.append(course)

    return merged


def _plan_rule(
    rule,
    available_courses: set,
    courses: dict,
    visiting: set,
) -> list:
    if isinstance(rule, str):
        return _plan_course(
            rule,
            available_courses,
            courses,
            visiting,
        )

    if not isinstance(rule, dict):
        raise ValueError(f"invalid requirement rule: {rule}")

    if "course" in rule:
        return _plan_course(
            rule["course"],
            available_courses,
            courses,
            visiting,
        )

    if "and" in rule:
        # Every branch is required, so combine their plans while preserving
        # the dependency order produced by each recursive walk.
        plans = [
            _plan_rule(
                child,
                available_courses,
                courses,
                visiting,
            )
            for child in rule["and"]
        ]

        return _merge_unique(*plans)

    if "or" in rule:
        # Prefer the alternative requiring the fewest additional courses.
        # Lexicographic ordering makes ties deterministic.
        candidates = [
            _plan_rule(
                child,
                available_courses,
                courses,
                visiting,
            )
            for child in rule["or"]
        ]

        return min(
            candidates,
            key=lambda plan: (len(plan), tuple(plan)),
        )

    raise ValueError(f"unknown rule type: {rule}")


def _plan_course(
    course_code: str,
    available_courses: set,
    courses: dict,
    visiting: set,
) -> list:
    course_code = normalize_course_code(course_code)

    # Completed or currently enrolled courses do not need to be suggested
    # again when planning toward a future target.
    if course_code in available_courses:
        return []

    # Requirements outside the selected dataset are still real requirements,
    # but there is no local prerequisite graph available to expand them.
    if course_code not in courses:
        return [course_code]

    if course_code in visiting:
        raise ValueError(
            f"cycle detected while planning through {course_code}"
        )

    visiting.add(course_code)

    try:
        prereq_plan = _plan_rule(
            courses[course_code].get("prereqs", EMPTY_RULE),
            available_courses,
            courses,
            visiting,
        )
    finally:
        visiting.remove(course_code)

    return _merge_unique(
        prereq_plan,
        [course_code],
    )


def plan_to_course(
    course_code: str,
    profile: StudentProfile,
    courses: dict,
) -> dict:
    target = normalize_course_code(course_code)

    if target not in courses:
        return {
            "target": target,
            "known": False,
            "already_completed": False,
            "in_progress": False,
            "prerequisite_plan": [],
            "external_requirements": [],
            "corequisites": None,
        }

    completed = set(profile.completed_courses)
    current = set(profile.current_courses)

    if target in completed:
        return {
            "target": target,
            "known": True,
            "already_completed": True,
            "in_progress": False,
            "prerequisite_plan": [],
            "external_requirements": [],
            "corequisites": {
                "satisfied": True,
                "missing": None,
            },
        }

    if target in current:
        return {
            "target": target,
            "known": True,
            "already_completed": False,
            "in_progress": True,
            "prerequisite_plan": [],
            "external_requirements": [],
            "corequisites": requirement_status(
                target,
                completed,
                current,
                courses,
            )["corequisites"],
        }

    # For future planning, a currently enrolled course is treated as already
    # on the student's path so it isn't recommended a second time.
    available = completed | current

    prerequisite_plan = _plan_rule(
        courses[target].get("prereqs", EMPTY_RULE),
        available,
        courses,
        {target},
    )

    external_requirements = [
        course
        for course in prerequisite_plan
        if course not in courses
    ]

    status = requirement_status(
        target,
        completed,
        current,
        courses,
    )

    return {
        "target": target,
        "known": True,
        "already_completed": False,
        "in_progress": False,
        "prerequisite_plan": prerequisite_plan,
        "external_requirements": external_requirements,
        "corequisites": status["corequisites"],
    }