import json
import tempfile
import unittest
from pathlib import Path

from app.graph import (
    eligible_courses,
    has_cycle,
    load_courses,
    requirement_status,
    satisfies,
    topological_order,
)
from app.profile import StudentProfile, load_student_profile, normalize_course_code


class ProfileTests(unittest.TestCase):
    def test_profile_normalizes_completed_and_current_courses(self):
        profile = StudentProfile.from_dict({
            "completed_courses": [" cmput   175 ", "math 134"],
            "current_courses": "cmput 201, CMPUT 272",
        })
        self.assertEqual(profile.completed_courses, frozenset({"CMPUT 175", "MATH 134"}))
        self.assertEqual(profile.current_courses, frozenset({"CMPUT 201", "CMPUT 272"}))

    def test_normalize_rejects_empty_code(self):
        with self.assertRaises(ValueError):
            normalize_course_code("   ")


class DatasetAndGraphTests(unittest.TestCase):
    def setUp(self):
        self.courses = {
            "A 100": {"title": "A", "prereqs": {"and": []}},
            "B 200": {"title": "B", "prereqs": {"or": ["A 100", "X 100"]}},
            "C 300": {
                "title": "C",
                "prereqs": {"and": ["B 200", {"or": ["MATH 100", "MATH 110"]}]},
                "coreqs": {"or": ["LAB 300", "LAB 301"]},
            },
        }

    def test_nested_and_or_rules(self):
        rule = self.courses["C 300"]["prereqs"]
        self.assertTrue(satisfies(rule, {"B 200", "MATH 110"}))
        self.assertFalse(satisfies(rule, {"B 200"}))

    def test_corequisite_can_be_current_or_completed(self):
        current_status = requirement_status(
            "C 300", {"B 200", "MATH 100"}, {"LAB 300"}, self.courses
        )
        completed_status = requirement_status(
            "C 300", {"B 200", "MATH 100", "LAB 301"}, set(), self.courses
        )
        self.assertTrue(current_status["eligible"])
        self.assertTrue(completed_status["eligible"])


    def test_current_course_does_not_satisfy_prerequisite(self):
        status = requirement_status("B 200", set(), {"A 100"}, self.courses)
        self.assertFalse(status["eligible"])
        self.assertFalse(status["prerequisites"]["satisfied"])

    def test_missing_corequisite_makes_course_ineligible(self):
        status = requirement_status("C 300", {"B 200", "MATH 100"}, set(), self.courses)
        self.assertFalse(status["eligible"])
        self.assertTrue(status["prerequisites"]["satisfied"])
        self.assertFalse(status["corequisites"]["satisfied"])

    def test_unknown_course_is_explicit(self):
        status = requirement_status("NOPE 999", set(), set(), self.courses)
        self.assertFalse(status["known"])
        self.assertFalse(status["eligible"])

    def test_eligible_courses_excludes_completed_and_current(self):
        result = eligible_courses({"A 100"}, self.courses, {"B 200"})
        self.assertNotIn("A 100", result)
        self.assertNotIn("B 200", result)

    def test_cycle_detection_and_topological_order(self):
        acyclic = {
            "A": {"prereqs": {"and": []}},
            "B": {"prereqs": "A"},
            "C": {"prereqs": "B"},
        }
        cyclic = {
            "A": {"prereqs": "C"},
            "B": {"prereqs": "A"},
            "C": {"prereqs": "B"},
        }
        self.assertFalse(has_cycle(acyclic))
        self.assertEqual(topological_order(acyclic), ["A", "B", "C"])
        self.assertTrue(has_cycle(cyclic))
        with self.assertRaises(ValueError):
            topological_order(cyclic)


    def test_rule_rejects_unknown_fields(self):
        from app.graph import validate_rule

        with self.assertRaises(ValueError):
            validate_rule({"and": ["A 100"], "typo": True})

    def test_custom_dataset_can_be_loaded_from_any_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "my_university.json"
            custom = {
                "cs   101": {"title": "Intro", "prereqs": {"and": []}},
                "cs 201": {"title": "Next", "prereqs": "cs 101"},
            }
            path.write_text(json.dumps(custom), encoding="utf-8")
            loaded = load_courses(path)
            self.assertIn("CS 101", loaded)
            self.assertEqual(loaded["CS 201"]["prereqs"], "CS 101")

    def test_custom_student_profile_can_be_loaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "student.json"
            path.write_text(
                json.dumps({"completed_courses": ["a 100"], "current_courses": ["b 200"]}),
                encoding="utf-8",
            )
            profile = load_student_profile(path)
            self.assertEqual(profile.completed_courses, frozenset({"A 100"}))
            self.assertEqual(profile.current_courses, frozenset({"B 200"}))


if __name__ == "__main__":
    unittest.main()

class ReferenceDatasetTests(unittest.TestCase):
    def test_reference_dataset_is_valid_acyclic_and_expected_size(self):
        courses = load_courses()
        self.assertEqual(len(courses), 18)
        self.assertFalse(has_cycle(courses))
        self.assertEqual(len(topological_order(courses)), 18)


    def test_reference_dataset_records_official_sources_and_verification_dates(self):
        courses = load_courses()
        for code, record in courses.items():
            self.assertTrue(record.get("source", "").startswith("https://apps.ualberta.ca/catalogue/course/"), code)
            self.assertEqual(record.get("verified"), "2026-09-13", code)

    def test_reference_dataset_exercises_nested_rules_and_corequisites(self):
        courses = load_courses()
        cmput_379 = courses["CMPUT 379"]["prereqs"]
        self.assertIn("and", cmput_379)
        self.assertIn("coreqs", courses["CMPUT 267"])
        self.assertIn("coreqs", courses["CMPUT 291"])
