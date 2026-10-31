"""Plain text rendering of expense listings and summaries."""

from __future__ import annotations

from typing import List, Optional, Sequence

from .parsing import format_amount, format_date, format_hours
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
    include_order = any(expense.order_name for expense in expenses)
    headers = ["ID", "DATE", "ITEM", "CATEGORY", "AMOUNT"]
    aligns = ["right", "left", "left", "left", "right"]
    if include_order:
        headers.append("ORDER")
        aligns.append("left")
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
        if include_order:
            row.append(expense.order_name)
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


def render_orders(orders, symbol: str = "$", title: str = "") -> str:
    if not orders:
        return "%sNo food orders recorded for this range." % (title + "\n" if title else "")

    rows: List[List[str]] = []
    for order in orders:
        date_value = getattr(order, "order_date", None) or getattr(order, "last_date", None)
        rows.append(
            [
                "%s (#%s)" % (order.name, order.id) if getattr(order, "id", None) else order.name,
                format_date(date_value) if date_value else "",
                format_amount(order.income_cents, symbol),
                format_amount(order.expense_cents, symbol),
                format_amount(order.profit_cents, symbol),
                format_amount(getattr(order, "overhead_reserve_cents", 0), symbol),
                format_amount(getattr(order, "tax_reserve_cents", 0), symbol),
                format_amount(
                    getattr(order, "keep_cents", order.profit_cents),
                    symbol,
                ),
                format_hours(getattr(order, "hours", 0)),
            ]
        )

    table = render_table(
        ["ORDER", "DATE", "INCOME", "EXPENSES", "PROFIT", "RATES", "TAX", "KEEP", "HOURS"],
        rows,
        ["left", "left", "right", "right", "right", "right", "right", "right", "right"],
    )
    income = sum(order.income_cents for order in orders)
    cost = sum(order.expense_cents for order in orders)
    hours = sum(getattr(order, "hours", 0) for order in orders)
    reserve = sum(getattr(order, "overhead_reserve_cents", 0) for order in orders)
    tax = sum(getattr(order, "tax_reserve_cents", 0) for order in orders)
    parts = []
    if title:
        parts.append(title)
    parts.append(table)
    parts.append("")
    parts.append(
        "%d order(s): income %s, expenses %s, profit %s, rates %s, tax %s, keep %s, labour %s hours"
        % (
            len(orders),
            format_amount(income, symbol),
            format_amount(cost, symbol),
            format_amount(income - cost, symbol),
            format_amount(reserve, symbol),
            format_amount(tax, symbol),
            format_amount(income - cost - reserve - tax, symbol),
            format_hours(hours),
        )
    )
    return "\n".join(parts)
