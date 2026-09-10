import datetime as dt
import unittest

from task_planner.parsing import ParseError, format_date, parse_date, parse_optional_date, resolve_range


class DateParsingTests(unittest.TestCase):
    def test_shorthands(self):
        ref = dt.date(2026, 9, 10)
        self.assertEqual(parse_date("today", ref), ref)
        self.assertEqual(parse_date("yesterday", ref), dt.date(2026, 9, 9))
        self.assertEqual(parse_date("tomorrow", ref), dt.date(2026, 9, 11))
        self.assertEqual(parse_date("2026-09-12", ref), dt.date(2026, 9, 12))
        self.assertEqual(parse_date("-3", ref), dt.date(2026, 9, 7))

    def test_optional_blank(self):
        self.assertIsNone(parse_optional_date(""))
        self.assertIsNone(parse_optional_date(None))
        self.assertEqual(parse_optional_date("2026-01-02"), dt.date(2026, 1, 2))

    def test_invalid_date(self):
        with self.assertRaises(ParseError):
            parse_date("not-a-date")

    def test_format_none(self):
        self.assertIsNone(format_date(None))
        self.assertEqual(format_date(dt.date(2026, 9, 10)), "2026-09-10")

    def test_range_days(self):
        ref = dt.date(2026, 9, 10)
        start, end = resolve_range(days=7, reference=ref)
        self.assertEqual(end, ref)
        self.assertEqual(start, dt.date(2026, 9, 4))
