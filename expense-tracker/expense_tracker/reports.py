"""Plain text rendering of expense listings and summaries."""

from __future__ import annotations

from typing import List, Optional, Sequence

from .parsing import format_amount, format_date
from .storage import Bucket, Expense

BAR_CHARACTER = "\u2588"


def render_table(headers: Sequence[str], rows: Sequence[Sequence[str]], aligns: Optional[Sequence[str]] = None) -> str:
    """Render a simple fixed width table."""

    if not rows:
        return ""
    columns = len(headers)
    aligns = list(aligns or ["left"] * columns)
    widths = [len(str(header)) for header in headers]
    for row in rows:
        for index in range(columns):
            widths[index] = max(widths[index], len(str(row[index])))

    def line(values: Sequence[str]) -> str:
        cells = []
        for index in range(columns):
            text = str(values[index])
            if aligns[index] == "right":
                cells.append(text.rjust(widths[index]))
            else:
                cells.append(text.ljust(widths[index]))
        return "  ".join(cells).rstrip()

    separator = "  ".join("-" * width for width in widths)
    body = [line(headers), separator]
    body.extend(line(row) for row in rows)
    return "\n".join(body)


def render_expenses(expenses: Sequence[Expense], symbol: str = "$", show_note: bool = True) -> str:
    if not expenses:
        return "No expenses recorded for this range."

    include_note = show_note and any(expense.note for expense in expenses)
    headers = ["ID", "DATE", "ITEM", "CATEGORY", "AMOUNT"]
    aligns = ["right", "left", "left", "left", "right"]
    if include_note:
        headers.append("NOTE")
        aligns.append("left")

    rows: List[List[str]] = []
    for expense in expenses:
        row = [
            str(expense.id),
            format_date(expense.spent_on),
            expense.item,
            expense.category,
            format_amount(expense.amount_cents, symbol),
        ]
        if include_note:
            row.append(expense.note)
        rows.append(row)

    total = sum(expense.amount_cents for expense in expenses)
    table = render_table(headers, rows, aligns)
    footer = "%d expense(s), total %s" % (len(expenses), format_amount(total, symbol))
    return "%s\n\n%s" % (table, footer)


def render_summary(
    buckets: Sequence[Bucket],
    symbol: str = "$",
    title: str = "",
    bar_width: int = 24,
    label: str = "CATEGORY",
) -> str:
    if not buckets:
        return "%sNo expenses recorded for this range." % (title + "\n" if title else "")

    total = sum(bucket.total_cents for bucket in buckets)
    largest = max(abs(bucket.total_cents) for bucket in buckets) or 1

    rows: List[List[str]] = []
    for bucket in buckets:
        share = (bucket.total_cents / total * 100) if total else 0.0
        filled = int(round(abs(bucket.total_cents) / largest * bar_width))
        rows.append(
            [
                bucket.key,
                format_amount(bucket.total_cents, symbol),
                "%5.1f%%" % share,
                str(bucket.count),
                BAR_CHARACTER * max(filled, 1 if bucket.total_cents else 0),
            ]
        )

    table = render_table(
        [label, "TOTAL", "SHARE", "COUNT", ""],
        rows,
        ["left", "right", "right", "right", "left"],
    )
    parts = []
    if title:
        parts.append(title)
    parts.append(table)
    parts.append("")
    parts.append("TOTAL: %s across %d expense(s)" % (format_amount(total, symbol), sum(b.count for b in buckets)))
    return "\n".join(parts)
