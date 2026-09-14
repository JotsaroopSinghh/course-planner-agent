import unittest

from app.agent import _run_tool_call
from app.graph import build_unlocks_map
from app.profile import StudentProfile


class AgentToolTests(unittest.TestCase):
    def setUp(self):
        self.courses = {
            "A 100": {"prereqs": {"and": []}},
            "B 200": {"prereqs": "A 100"},
            "C 300": {"prereqs": "B 200", "coreqs": "LAB 300"},
        }
        self.profile = StudentProfile.from_dict({
            "completed_courses": ["A 100", "B 200"],
            "current_courses": ["LAB 300"],
        })
        self.unlocks = build_unlocks_map(self.courses)

    def test_check_eligibility_uses_profile_state(self):
        result = _run_tool_call(
            "check_eligibility",
            {"course_code": " c  300 "},
            self.profile,
            self.courses,
            self.unlocks,
        )
        self.assertTrue(result["known"])
        self.assertTrue(result["eligible"])
        self.assertTrue(result["corequisites"]["satisfied"])

    def test_course_requirements_returns_full_rules(self):
        result = _run_tool_call(
            "get_course_requirements",
            {"course_code": "C 300"},
            self.profile,
            self.courses,
            self.unlocks,
        )
        self.assertTrue(result["known"])
        self.assertEqual(result["prerequisites"], "B 200")
        self.assertEqual(result["corequisites"], "LAB 300")

    def test_missing_requirements_preserves_structure(self):
        empty_profile = StudentProfile()
        result = _run_tool_call(
            "get_missing_requirements",
            {"course_code": "C 300"},
            empty_profile,
            self.courses,
            self.unlocks,
        )
        self.assertFalse(result["eligible"])
        self.assertEqual(result["prerequisites"]["missing"]["course"], "B 200")
        self.assertEqual(result["corequisites"]["missing"]["course"], "LAB 300")

    def test_dependent_courses_are_deterministic(self):
        result = _run_tool_call(
            "get_dependent_courses",
            {"course_code": "A 100"},
            self.profile,
            self.courses,
            self.unlocks,
        )
        self.assertEqual(result["dependent_courses"], ["B 200"])

    def test_unknown_and_malformed_tool_calls_return_errors(self):
        unknown = _run_tool_call("not_a_tool", {}, self.profile, self.courses, self.unlocks)
        malformed = _run_tool_call(
            "check_eligibility", "{bad json", self.profile, self.courses, self.unlocks
        )
        self.assertIn("error", unknown)
        self.assertIn("error", malformed)


if __name__ == "__main__":
    unittest.main()

class AgentLoopTests(unittest.TestCase):
    def test_ask_executes_function_call_then_returns_model_answer(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        import json

        from app.agent import ask

        function_call = SimpleNamespace(
            type="function_call",
            name="check_eligibility",
            arguments={"course_code": "CMPUT 291"},
            id="call-1",
        )
        first = SimpleNamespace(
            id="interaction-1",
            steps=[function_call],
            output_text=None,
        )
        second = SimpleNamespace(
            id="interaction-2",
            steps=[],
            output_text="Yes, the represented requirements are satisfied.",
        )

        class FakeInteractions:
            def __init__(self):
                self.calls = []
                self.responses = [first, second]

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return self.responses.pop(0)

        fake_interactions = FakeInteractions()
        fake_client = SimpleNamespace(interactions=fake_interactions)
        profile = StudentProfile.from_dict({
            "completed_courses": ["CMPUT 175", "CMPUT 272"],
            "current_courses": ["CMPUT 201"],
        })

        with patch("app.agent._client", fake_client):
            answer = ask("Can I take CMPUT 291?", profile)

        self.assertEqual(answer, "Yes, the represented requirements are satisfied.")
        self.assertEqual(len(fake_interactions.calls), 2)
        second_input = fake_interactions.calls[1]["input"][0]
        self.assertEqual(second_input["type"], "function_result")
        result = json.loads(second_input["result"][0]["text"])
        self.assertTrue(result["eligible"])
        self.assertTrue(result["prerequisites"]["satisfied"])
        self.assertTrue(result["corequisites"]["satisfied"])
