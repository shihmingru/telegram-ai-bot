import unittest

from agent_skills import validate_skill


class SkillValidationTests(unittest.TestCase):
    def test_normalizes_name(self):
        self.assertEqual(
            validate_skill("  Morning Review  ", "Review a list of tasks, summarize priorities, and suggest the next action."),
            ("morning review", "Review a list of tasks, summarize priorities, and suggest the next action."),
        )

    def test_rejects_invalid_name(self):
        with self.assertRaises(ValueError):
            validate_skill("../secrets", "This is a sufficiently long set of instructions for a test skill.")

    def test_rejects_too_short_instructions(self):
        with self.assertRaises(ValueError):
            validate_skill("review", "too short")

    def test_rejects_oversized_instructions(self):
        with self.assertRaises(ValueError):
            validate_skill("review", "x" * 6001)


if __name__ == "__main__":
    unittest.main()
