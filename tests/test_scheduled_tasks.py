import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from scheduled_tasks import parse_schedule_text


class ScheduleParserTests(unittest.TestCase):
    def test_daily_natural_language_with_am_time(self):
        frequency, clock, timezone, request, due = parse_schedule_text(
            "Every day at 8am, send me the latest AI headlines"
        )
        self.assertEqual(frequency, "daily")
        self.assertEqual(clock, "08:00")
        self.assertEqual(timezone, "Asia/Taipei")
        self.assertEqual(request, "send me the latest AI headlines")
        self.assertEqual(due.tzinfo, ZoneInfo("Asia/Taipei"))
        self.assertGreater(due, datetime.now(ZoneInfo("Asia/Taipei")))

    def test_daily_natural_language_with_24_hour_time(self):
        frequency, clock, timezone, request, due = parse_schedule_text(
            "Send me a daily summary at 08:30"
        )
        self.assertEqual((frequency, clock, timezone), ("daily", "08:30", "Asia/Taipei"))
        self.assertEqual(request, "Send me a summary")

    def test_weekly_request_with_explicit_timezone(self):
        frequency, clock, timezone, request, due = parse_schedule_text(
            "Every week at 09:00 [Europe/Paris], review my study plan"
        )
        self.assertEqual((frequency, clock, timezone), ("weekly", "09:00", "Europe/Paris"))
        self.assertEqual(request, "review my study plan")
        self.assertEqual(due.tzinfo, ZoneInfo("Europe/Paris"))

    def test_structured_schedule(self):
        frequency, clock, timezone, request, due = parse_schedule_text(
            "daily at 19:30 | practise French"
        )
        self.assertEqual((frequency, clock, timezone, request),
                         ("daily", "19:30", "Asia/Taipei", "practise French"))

    def test_request_whitespace_is_normalized(self):
        _, _, _, request, _ = parse_schedule_text(
            "Every day at 8am, send me   the latest AI headlines"
        )
        self.assertEqual(request, "send me the latest AI headlines")

    def test_invalid_structured_time_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "valid 24-hour time"):
            parse_schedule_text("daily at 24:00 | practise French")

    def test_missing_time_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "recurring request and time"):
            parse_schedule_text("Every day, send me AI headlines")

    def test_unknown_timezone_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone is not recognized"):
            parse_schedule_text("daily at 08:00 [Mars/Olympus] | practise French")


if __name__ == "__main__":
    unittest.main()
