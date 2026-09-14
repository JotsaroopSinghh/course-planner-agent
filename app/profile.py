import json
import re
from dataclasses import dataclass
from pathlib import Path


def normalize_course_code(course_code: str) -> str:
    # Keep course codes consistent across profiles and datasets.
    # This only normalizes formatting,it doesn't try to guess invalid codes.
    if not isinstance(course_code, str):
        raise TypeError("course codes must be strings")

    normalized = re.sub(r"\s+", " ", course_code.strip()).upper()

    if not normalized:
        raise ValueError("course code cannot be empty")

    return normalized


def _normalize_course_collection(values) -> frozenset[str]:
    # Missing fields are treated as an empty course list.
    if values is None:
        return frozenset()

    if isinstance(values, str):
        values = values.split(",")

    if not isinstance(values, (list, tuple, set, frozenset)):
        raise TypeError(
            "course collections must be a list, set, tuple, or comma-separated string"
        )

    # frozenset removes duplicates and keeps StudentProfile immutable.
    return frozenset(
        normalize_course_code(value)
        for value in values
        if isinstance(value, str) and value.strip()
    )


@dataclass(frozen=True)
class StudentProfile:
    # Completed courses satisfy prerequisites.
    completed_courses: frozenset[str] = frozenset()

    # Current courses matter separately because they may satisfy corequisites.
    current_courses: frozenset[str] = frozenset()

    @classmethod
    def from_dict(cls, data: dict):
        # Profiles come from JSON, so fail early if the top-level structure is wrong.
        if not isinstance(data, dict):
            raise TypeError("student profile must be a JSON object")

        return cls(
            completed_courses=_normalize_course_collection(
                data.get("completed_courses")
            ),
            current_courses=_normalize_course_collection(
                data.get("current_courses")
            ),
        )

    @property
    def courses_available_for_corequisites(self) -> frozenset[str]:
        # A corequisite can already be completed or currently in progress.
        return self.completed_courses | self.current_courses


def load_student_profile(path) -> StudentProfile:
    path = Path(path)

    # Keep file/JSON errors readable for CLI users instead of exposing raw exceptions.
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as exc:
        raise ValueError(f"student profile not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"student profile is not valid JSON: {path}") from exc

    return StudentProfile.from_dict(data)