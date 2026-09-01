"""Parsing and formatting helpers for dates, money and reporting ranges."""

from __future__ import annotations

import calendar
import datetime as dt
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional, Tuple

ISO_DATE = "%Y-%m-%d"

_MONTH_NAMES = {
    name.lower(): number
    for number, name in enumerate(calendar.month_name)
    if name
}
_MONTH_NAMES.update(
    {name.lower(): number for number, name in enumerate(calendar.month_abbr) if name}
)

_MONEY_CLEAN_RE = re.compile(r"[,\s\u00a0]")
_CURRENCY_PREFIX_RE = re.compile(r"^[^\d\-+.]+")
_CURRENCY_SUFFIX_RE = re.compile(r"[^\d]+$")


class ParseError(ValueError):
    """Raised when user supplied input cannot be understood."""


def today() -> dt.date:
    return dt.date.today()


def parse_amount(value) -> int:
    """Convert a user supplied amount into integer cents.

    Accepts plain numbers, thousands separators and a leading or trailing
    currency symbol, e.g. ``12``, ``12.5``, ``$1,234.56`` or ``9.99 USD``.
    Negative values are allowed so refunds can be recorded.
    """

    if isinstance(value, int) and not isinstance(value, bool):
        return value * 100
    if isinstance(value, float):
        raw = repr(value)
    else:
        raw = str(value)

    text = _MONEY_CLEAN_RE.sub("", raw).strip()
    if not text:
        raise ParseError("Amount is required, for example 12.50")

    text = _CURRENCY_PREFIX_RE.sub("", text, count=1)
    text = _CURRENCY_SUFFIX_RE.sub("", text, count=1)
    if not text or text in {"-", "+", "."}:
        raise ParseError("Could not read an amount from %r" % raw)

    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise ParseError("Could not read an amount from %r" % raw) from None

    if not amount.is_finite():
        raise ParseError("Could not read an amount from %r" % raw)

    cents = (amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def format_amount(cents: int, symbol: str = "$") -> str:
    """Render integer cents as a human readable amount."""

    negative = cents < 0
    whole, remainder = divmod(abs(int(cents)), 100)
    text = "{}{:,}.{:02d}".format(symbol, whole, remainder)
    return "-" + text if negative else text


def amount_to_decimal(cents: int) -> Decimal:
    return (Decimal(int(cents)) / 100).quantize(Decimal("0.01"))


def parse_date(value, reference: Optional[dt.date] = None) -> dt.date:
    """Parse a date written in one of several convenient shorthands.

    Supported: empty/``today``/``now``, ``yesterday``, ISO ``YYYY-MM-DD``,
    ``YYYY/MM/DD``, ``MM-DD`` (nearest past occurrence) and ``-N`` for
    *N* days ago.
    """

    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value

    ref = reference or today()
    text = ("" if value is None else str(value)).strip().lower()
    if text in {"", "today", "now", "t"}:
        return ref
    if text in {"yesterday", "yest", "y"}:
        return ref - dt.timedelta(days=1)
    if text in {"tomorrow"}:
        return ref + dt.timedelta(days=1)

    offset = re.fullmatch(r"([+-]\d+)d?", text)
    if offset:
        return ref + dt.timedelta(days=int(offset.group(1)))

    normalised = text.replace("/", "-").replace(".", "-")
    parts = normalised.split("-")
    try:
        if len(parts) == 3:
            year, month, day = (int(part) for part in parts)
            if year < 100:
                year += 2000
            return dt.date(year, month, day)
        if len(parts) == 2:
            month, day = (int(part) for part in parts)
            candidate = dt.date(ref.year, month, day)
            if candidate > ref:
                candidate = dt.date(ref.year - 1, month, day)
            return candidate
    except ValueError:
        raise ParseError("%r is not a valid date, expected YYYY-MM-DD" % value) from None

    raise ParseError("%r is not a valid date, expected YYYY-MM-DD" % value)


def format_date(value: dt.date) -> str:
    return value.strftime(ISO_DATE)


def add_months(value: dt.date, months: int) -> dt.date:
    """Shift a date by whole months, clamping to the end of short months."""

    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def month_bounds(year: int, month: int) -> Tuple[dt.date, dt.date]:
    last_day = calendar.monthrange(year, month)[1]
    return dt.date(year, month, 1), dt.date(year, month, last_day)


def parse_month(value, reference: Optional[dt.date] = None) -> Tuple[dt.date, dt.date]:
    """Resolve a month expression into an inclusive ``(start, end)`` range."""

    ref = reference or today()
    text = ("" if value is None else str(value)).strip().lower()
    if text in {"", "this", "current", "this-month"}:
        return month_bounds(ref.year, ref.month)
    if text in {"last", "prev", "previous", "last-month"}:
        previous = add_months(dt.date(ref.year, ref.month, 1), -1)
        return month_bounds(previous.year, previous.month)

    match = re.fullmatch(r"(\d{4})[-/](\d{1,2})", text)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if not 1 <= month <= 12:
            raise ParseError("%r is not a valid month" % value)
        return month_bounds(year, month)

    match = re.fullmatch(r"(\d{1,2})[-/](\d{4})", text)
    if match:
        month, year = int(match.group(1)), int(match.group(2))
        if not 1 <= month <= 12:
            raise ParseError("%r is not a valid month" % value)
        return month_bounds(year, month)

    name_match = re.fullmatch(r"([a-z]+)\s*(\d{4})?", text)
    if name_match and name_match.group(1) in _MONTH_NAMES:
        month = _MONTH_NAMES[name_match.group(1)]
        if name_match.group(2):
            year = int(name_match.group(2))
        else:
            year = ref.year if month <= ref.month else ref.year - 1
        return month_bounds(year, month)

    raise ParseError("%r is not a valid month, expected YYYY-MM" % value)


def resolve_range(
    *,
    start=None,
    end=None,
    month=None,
    year=None,
    days=None,
    reference: Optional[dt.date] = None,
) -> Tuple[Optional[dt.date], Optional[dt.date]]:
    """Turn the assorted range selectors into an inclusive date range."""

    ref = reference or today()
    if month is not None:
        return parse_month(month, ref)
    if year is not None:
        year_number = int(year)
        return dt.date(year_number, 1, 1), dt.date(year_number, 12, 31)
    if days is not None:
        span = int(days)
        if span < 1:
            raise ParseError("--days must be at least 1")
        return ref - dt.timedelta(days=span - 1), ref

    start_date = parse_date(start, ref) if start else None
    end_date = parse_date(end, ref) if end else None
    if start_date and end_date and start_date > end_date:
        raise ParseError("Start date %s is after end date %s" % (start_date, end_date))
    return start_date, end_date


def describe_range(start: Optional[dt.date], end: Optional[dt.date]) -> str:
    if start and end:
        return "%s to %s" % (format_date(start), format_date(end))
    if start:
        return "since %s" % format_date(start)
    if end:
        return "up to %s" % format_date(end)
    return "all time"
