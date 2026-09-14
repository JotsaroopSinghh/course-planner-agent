import unittest

from app.planner import plan_to_course
from app.profile import StudentProfile


class PlannerTests(unittest.TestCase):
    def test_simple_prerequisite_chain_is_ordered(self):
        courses = {
            "A": {"prereqs": {"and": []}},
            "B": {"prereqs": "A"},
            "C": {"prereqs": "B"},
        }

        result = plan_to_course(
            "C",
            StudentProfile(),
            courses,
        )

        self.assertEqual(
            result["prerequisite_plan"],
            ["A", "B"],
        )

    def test_nested_and_requirements_include_every_branch(self):
        courses = {
            "A": {"prereqs": {"and": []}},
            "B": {"prereqs": "A"},
            "C": {"prereqs": {"and": []}},
            "D": {"prereqs": {"and": ["B", "C"]}},
        }

        result = plan_to_course(
            "D",
            StudentProfile(),
            courses,
        )

        self.assertEqual(
            result["prerequisite_plan"],
            ["A", "B", "C"],
        )

    def test_or_rule_chooses_shorter_path(self):
        courses = {
            "A": {"prereqs": {"and": []}},
            "B": {"prereqs": {"and": []}},
            "C": {"prereqs": {"and": []}},
            "TARGET": {
                "prereqs": {
                    "or": [
                        "A",
                        {"and": ["B", "C"]},
                    ]
                }
            },
        }

        result = plan_to_course(
            "TARGET",
            StudentProfile(),
            courses,
        )

        self.assertEqual(
            result["prerequisite_plan"],
            ["A"],
        )

    def test_completed_courses_are_omitted(self):
        courses = {
            "A": {"prereqs": {"and": []}},
            "B": {"prereqs": "A"},
            "C": {"prereqs": "B"},
        }

        profile = StudentProfile.from_dict({
            "completed_courses": ["A"],
        })

        result = plan_to_course(
            "C",
            profile,
            courses,
        )

        self.assertEqual(
            result["prerequisite_plan"],
            ["B"],
        )

    def test_current_courses_are_not_recommended_again(self):
        courses = {
            "A": {"prereqs": {"and": []}},
            "B": {"prereqs": "A"},
            "C": {"prereqs": "B"},
        }

        profile = StudentProfile.from_dict({
            "completed_courses": ["A"],
            "current_courses": ["B"],
        })

        result = plan_to_course(
            "C",
            profile,
            courses,
        )

        self.assertEqual(
            result["prerequisite_plan"],
            [],
        )

    def test_external_requirement_is_reported(self):
        courses = {
            "TARGET": {
                "prereqs": {
                    "and": [
                        "MATH 100",
                    ]
                }
            }
        }

        result = plan_to_course(
            "TARGET",
            StudentProfile(),
            courses,
        )

        self.assertEqual(
            result["prerequisite_plan"],
            ["MATH 100"],
        )

        self.assertEqual(
            result["external_requirements"],
            ["MATH 100"],
        )

    def test_completed_target_needs_no_plan(self):
        courses = {
            "TARGET": {
                "prereqs": {"and": []},
            }
        }

        profile = StudentProfile.from_dict({
            "completed_courses": ["TARGET"],
        })

        result = plan_to_course(
            "TARGET",
            profile,
            courses,
        )

        self.assertTrue(result["already_completed"])
        self.assertEqual(result["prerequisite_plan"], [])

    def test_unknown_target_is_explicit(self):
        result = plan_to_course(
            "UNKNOWN 100",
            StudentProfile(),
            {},
        )

        self.assertFalse(result["known"])
        self.assertEqual(result["prerequisite_plan"], [])

    def test_cycle_is_rejected(self):
        courses = {
            "A": {"prereqs": "B"},
            "B": {"prereqs": "A"},
        }

        with self.assertRaises(ValueError):
            plan_to_course(
                "A",
                StudentProfile(),
                courses,
            )


if __name__ == "__main__":
    unittest.main()