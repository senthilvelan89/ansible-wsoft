import datetime as dt
import unittest

from expense_tracker.parsing import (
    ParseError,
    add_months,
    describe_range,
    format_amount,
    month_bounds,
    parse_amount,
    parse_date,
    parse_month,
    resolve_range,
)


class ParseAmountTests(unittest.TestCase):
    def test_reads_common_formats(self):
        self.assertEqual(parse_amount("12"), 1200)
        self.assertEqual(parse_amount("12.5"), 1250)
        self.assertEqual(parse_amount("12.50"), 1250)
        self.assertEqual(parse_amount("$1,234.56"), 123456)
        self.assertEqual(parse_amount(" 9.99 "), 999)
        self.assertEqual(parse_amount("9.99 USD"), 999)
        self.assertEqual(parse_amount(7), 700)

    def test_rounds_half_up_to_cents(self):
        self.assertEqual(parse_amount("0.005"), 1)
        self.assertEqual(parse_amount("1.014"), 101)
        self.assertEqual(parse_amount("1.015"), 102)

    def test_allows_negative_for_refunds(self):
        self.assertEqual(parse_amount("-20.00"), -2000)

    def test_rejects_nonsense(self):
        for value in ["", "   ", "abc", "$", "."]:
            with self.assertRaises(ParseError):
                parse_amount(value)

    def test_no_floating_point_drift(self):
        total = sum(parse_amount(value) for value in ["0.1", "0.2", "0.3"])
        self.assertEqual(total, 60)


class FormatAmountTests(unittest.TestCase):
    def test_formats_with_separators(self):
        self.assertEqual(format_amount(123456), "$1,234.56")
        self.assertEqual(format_amount(5), "$0.05")
        self.assertEqual(format_amount(-2000), "-$20.00")
        self.assertEqual(format_amount(1000, "\u20ac"), "\u20ac10.00")


class ParseDateTests(unittest.TestCase):
    reference = dt.date(2026, 3, 15)

    def test_keywords(self):
        self.assertEqual(parse_date("today", self.reference), self.reference)
        self.assertEqual(parse_date("", self.reference), self.reference)
        self.assertEqual(parse_date("yesterday", self.reference), dt.date(2026, 3, 14))
        self.assertEqual(parse_date("-3", self.reference), dt.date(2026, 3, 12))

    def test_iso_and_slashes(self):
        self.assertEqual(parse_date("2025-12-31", self.reference), dt.date(2025, 12, 31))
        self.assertEqual(parse_date("2025/12/31", self.reference), dt.date(2025, 12, 31))

    def test_month_day_uses_nearest_past_year(self):
        self.assertEqual(parse_date("03-01", self.reference), dt.date(2026, 3, 1))
        self.assertEqual(parse_date("12-25", self.reference), dt.date(2025, 12, 25))

    def test_rejects_invalid(self):
        for value in ["2026-13-01", "2026-02-30", "not-a-date"]:
            with self.assertRaises(ParseError):
                parse_date(value, self.reference)


class MonthTests(unittest.TestCase):
    reference = dt.date(2026, 3, 15)

    def test_named_and_numeric_months(self):
        self.assertEqual(parse_month("2025-11"), (dt.date(2025, 11, 1), dt.date(2025, 11, 30)))
        self.assertEqual(parse_month("this", self.reference), (dt.date(2026, 3, 1), dt.date(2026, 3, 31)))
        self.assertEqual(parse_month("last", self.reference), (dt.date(2026, 2, 1), dt.date(2026, 2, 28)))
        self.assertEqual(parse_month("feb", self.reference), (dt.date(2026, 2, 1), dt.date(2026, 2, 28)))
        self.assertEqual(parse_month("december", self.reference), (dt.date(2025, 12, 1), dt.date(2025, 12, 31)))

    def test_leap_year_bounds(self):
        self.assertEqual(month_bounds(2028, 2), (dt.date(2028, 2, 1), dt.date(2028, 2, 29)))

    def test_rejects_invalid(self):
        with self.assertRaises(ParseError):
            parse_month("2026-13")


class AddMonthsTests(unittest.TestCase):
    def test_clamps_to_short_months(self):
        self.assertEqual(add_months(dt.date(2026, 3, 31), -1), dt.date(2026, 2, 28))
        self.assertEqual(add_months(dt.date(2026, 1, 31), 1), dt.date(2026, 2, 28))

    def test_year_rollover(self):
        self.assertEqual(add_months(dt.date(2026, 3, 15), -12), dt.date(2025, 3, 15))
        self.assertEqual(add_months(dt.date(2026, 3, 15), -15), dt.date(2024, 12, 15))


class ResolveRangeTests(unittest.TestCase):
    reference = dt.date(2026, 3, 15)

    def test_days_window_includes_today(self):
        start, end = resolve_range(days=7, reference=self.reference)
        self.assertEqual((start, end), (dt.date(2026, 3, 9), self.reference))

    def test_year_window(self):
        self.assertEqual(
            resolve_range(year=2025, reference=self.reference),
            (dt.date(2025, 1, 1), dt.date(2025, 12, 31)),
        )

    def test_explicit_dates(self):
        self.assertEqual(
            resolve_range(start="2026-01-01", end="2026-01-31", reference=self.reference),
            (dt.date(2026, 1, 1), dt.date(2026, 1, 31)),
        )

    def test_rejects_backwards_range(self):
        with self.assertRaises(ParseError):
            resolve_range(start="2026-02-01", end="2026-01-01", reference=self.reference)

    def test_description(self):
        self.assertEqual(describe_range(None, None), "all time")
        self.assertEqual(describe_range(dt.date(2026, 1, 1), None), "since 2026-01-01")


if __name__ == "__main__":
    unittest.main()
