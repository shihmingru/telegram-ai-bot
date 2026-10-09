import unittest
from unittest.mock import patch

import platform_tools


class PlatformToolSafetyTests(unittest.TestCase):
    def test_mutating_tools_are_blocked_without_approval(self):
        cases = [
            ("github_create_issue", {"repository": "owner/repo", "title": "Test"}),
            ("render_trigger_deploy", {"service_id": "srv-test"}),
            ("todoist_create_task", {"content": "Test"}),
            ("google_calendar_create_event", {"summary": "Test", "start": "2026-10-10T10:00:00+08:00", "end": "2026-10-10T11:00:00+08:00"}),
        ]
        for name, args in cases:
            with self.subTest(tool=name):
                result = platform_tools.execute_platform_tool(name, args, allow_mutation=False)
                self.assertIn("error", result)
                self.assertIn("approval", result["error"].lower())

    def test_mutating_tool_requires_required_arguments_after_approval(self):
        result = platform_tools.execute_platform_tool("todoist_create_task", {}, allow_mutation=True)
        self.assertIn("error", result)
        self.assertIn("content is required", result["error"])

    def test_platform_allowlist_fails_closed(self):
        with patch.dict("os.environ", {}, clear=True):
            import bot
            self.assertFalse(bot.is_platform_user("12345"))

    def test_action_summary_is_specific(self):
        summary = platform_tools._action_summary(
            "todoist_create_task", {"content": "Submit thesis"}
        )
        self.assertIn("Submit thesis", summary)

    def test_google_calendar_does_not_use_missing_credentials(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Google Calendar is not configured"):
                platform_tools._google_access_token()


if __name__ == "__main__":
    unittest.main()
