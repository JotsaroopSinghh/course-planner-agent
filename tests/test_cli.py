import json
import tempfile
import unittest
from pathlib import Path

from app.cli import build_parser, build_profile


class CliTests(unittest.TestCase):
    def test_direct_course_arguments_build_profile(self):
        args = build_parser().parse_args([
            "--completed", "cmput 175, math 134",
            "--current", "cmput 201",
        ])
        profile = build_profile(args)
        self.assertEqual(profile.completed_courses, frozenset({"CMPUT 175", "MATH 134"}))
        self.assertEqual(profile.current_courses, frozenset({"CMPUT 201"}))

    def test_profile_file_takes_precedence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "student.json"
            path.write_text(
                json.dumps({"completed_courses": ["CMPUT 272"], "current_courses": []}),
                encoding="utf-8",
            )
            args = build_parser().parse_args([
                "--profile", str(path),
                "--completed", "CMPUT 175",
            ])
            profile = build_profile(args)
            self.assertEqual(profile.completed_courses, frozenset({"CMPUT 272"}))


if __name__ == "__main__":
    unittest.main()
