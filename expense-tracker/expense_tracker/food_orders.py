"""Food-order profit tracking: income, costs, labour hours.

This is a separate ledger from personal expenses. Each order has money
received (income), costs under order-specific categories, and optional
labour hours. Profit is income minus costs. A configurable share of
income is set aside for annual council rates, ABN and business
registration so that money is reserved without distorting order costing.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Tuple

from .parsing import (
    ParseError,
    format_amount,
    format_date,
    format_hours,
    parse_amount,
    parse_date,
    parse_hours,
    today,
)

INCOME_KIND = "income"
COST_KIND = "cost"
LABOUR_CATEGORY = "Labour"

DEFAULT_ORDER_CATEGORIES = (
    "Grocery",
    "Veggies",
    "Labour",
    "Other",
    "Rates",
    "Company registration",
    "Insurance",
    "Delivery",
    "Packaging",
)

# Yearly council rates, ABN and business registration. Funded by setting
# aside a slice of each order's income instead of booking a fake cost line.
DEFAULT_ANNUAL_OVERHEAD_CENTS = 120000  # $1,200
DEFAULT_MONTHLY_ORDER_INCOME_CENTS = 120000  # assumed $1,200 of orders / month
OVERHEAD_LABEL = "council rates, ABN and business registration"

_CATEGORY_ALIASES = {
    "groceries": "Grocery",
    "grocery": "Grocery",
    "veg": "Veggies",
    "vegetable": "Veggies",
    "vegetables": "Veggies",
    "labor": "Labour",
    "labour": "Labour",
    "company_registration": "Company registration",
    "company registration": "Company registration",
}


@dataclass(frozen=True)
class OrderEntry:
    id: int
    order_id: int
    kind: str
    spent_on: dt.date
    item: str
    category: str
    amount_cents: int
    hours: float = 0.0
    note: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self, symbol: str = "$") -> Dict[str, object]:
        return {
            "id": self.id,
            "order_id": self.order_id,
            "kind": self.kind,
            "date": format_date(self.spent_on),
            "item": self.item,
            "category": self.category,
            "amount_cents": self.amount_cents,
            "amount": self.amount_cents / 100,
            "amount_display": format_amount(self.amount_cents, symbol),
            "hours": self.hours,
            "hours_display": format_hours(self.hours),
            "note": self.note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class FoodOrder:
    id: int
    name: str
    order_date: dt.date
    note: str = ""
    income_cents: int = 0
    expense_cents: int = 0
    hours: float = 0.0
    income_count: int = 0
    expense_count: int = 0
    overhead_reserve_cents: int = 0
    created_at: str = ""
    updated_at: str = ""
    entries: Optional[List[OrderEntry]] = None
    cost_categories: Optional[List] = None

    @property
    def profit_cents(self) -> int:
        return self.income_cents - self.expense_cents

    @property
    def profit_after_reserve_cents(self) -> int:
        return self.profit_cents - self.overhead_reserve_cents

    def to_dict(self, symbol: str = "$") -> Dict[str, object]:
        profit = self.profit_cents
        after_reserve = self.profit_after_reserve_cents
        payload = {
            "id": self.id,
            "name": self.name,
            "date": format_date(self.order_date),
            "note": self.note,
            "income_cents": self.income_cents,
            "income_display": format_amount(self.income_cents, symbol),
            "expense_cents": self.expense_cents,
            "expense_display": format_amount(self.expense_cents, symbol),
            "profit_cents": profit,
            "profit_display": format_amount(profit, symbol),
            "overhead_reserve_cents": self.overhead_reserve_cents,
            "overhead_reserve_display": format_amount(self.overhead_reserve_cents, symbol),
            "profit_after_reserve_cents": after_reserve,
            "profit_after_reserve_display": format_amount(after_reserve, symbol),
            "hours": self.hours,
            "hours_display": format_hours(self.hours),
            "income_count": self.income_count,
            "expense_count": self.expense_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.entries is not None:
            payload["entries"] = [entry.to_dict(symbol) for entry in self.entries]
            payload["income_entries"] = [
                entry.to_dict(symbol) for entry in self.entries if entry.kind == INCOME_KIND
            ]
            payload["cost_entries"] = [
                entry.to_dict(symbol) for entry in self.entries if entry.kind == COST_KIND
            ]
        if self.cost_categories is not None:
            payload["cost_categories"] = [bucket.to_dict(symbol) for bucket in self.cost_categories]
        return payload


class FoodOrderMixin:
    """Order ledger methods mixed into Database."""

    def ensure_order_schema(self, connection) -> None:
        stamp = _now()
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS food_orders (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL,
                order_date TEXT    NOT NULL,
                note       TEXT    NOT NULL DEFAULT '',
                created_at TEXT    NOT NULL,
                updated_at TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS order_categories (
                name       TEXT PRIMARY KEY COLLATE NOCASE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS order_entries (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id     INTEGER NOT NULL,
                kind         TEXT    NOT NULL,
                spent_on     TEXT    NOT NULL,
                item         TEXT    NOT NULL,
                category     TEXT    NOT NULL COLLATE NOCASE,
                amount_cents INTEGER NOT NULL,
                hours        REAL    NOT NULL DEFAULT 0,
                note         TEXT    NOT NULL DEFAULT '',
                created_at   TEXT    NOT NULL,
                updated_at   TEXT    NOT NULL,
                FOREIGN KEY (order_id) REFERENCES food_orders(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_order_entries_order
                ON order_entries (order_id);
            """
        )
        connection.executemany(
            "INSERT OR IGNORE INTO order_categories (name, created_at) VALUES (?, ?)",
            [(name, stamp) for name in DEFAULT_ORDER_CATEGORIES],
        )
        self._copy_tagged_expenses(connection, stamp)

    def overhead_amounts(self) -> Tuple[int, int]:
        annual = _meta_cents(
            self.get_setting("annual_overhead_cents"), DEFAULT_ANNUAL_OVERHEAD_CENTS
        )
        monthly = _meta_cents(
            self.get_setting("expected_monthly_order_income_cents"),
            DEFAULT_MONTHLY_ORDER_INCOME_CENTS,
        )
        if monthly <= 0:
            monthly = DEFAULT_MONTHLY_ORDER_INCOME_CENTS
        return annual, monthly

    def set_overhead_amounts(self, annual=None, monthly=None) -> None:
        if annual is not None:
            cents = parse_amount(annual)
            if cents < 0:
                raise ParseError("Annual overhead cannot be negative")
            self.set_setting("annual_overhead_cents", str(cents))
        if monthly is not None:
            cents = parse_amount(monthly)
            if cents <= 0:
                raise ParseError("Expected monthly order income must be greater than zero")
            self.set_setting("expected_monthly_order_income_cents", str(cents))

    def overhead_snapshot(self, symbol: str = "$", year: Optional[int] = None) -> Dict[str, object]:
        year = year or today().year
        annual, monthly = self.overhead_amounts()
        monthly_reserve = int(round(annual / 12.0)) if annual else 0
        rate = (annual / 12.0 / monthly) if monthly else 0.0
        start = dt.date(year, 1, 1)
        end = dt.date(year, 12, 31)
        ytd = sum(
            order.overhead_reserve_cents
            for order in self.list_food_orders(start=start, end=end)
        )
        remaining = max(0, annual - ytd)
        progress = min(1.0, ytd / annual) if annual else 1.0
        rate_display = "%.2f%%" % (rate * 100)
        return {
            "label": OVERHEAD_LABEL,
            "year": year,
            "annual_cents": annual,
            "annual_display": format_amount(annual, symbol),
            "expected_monthly_income_cents": monthly,
            "expected_monthly_income_display": format_amount(monthly, symbol),
            "monthly_reserve_cents": monthly_reserve,
            "monthly_reserve_display": format_amount(monthly_reserve, symbol),
            "rate": rate,
            "rate_display": rate_display,
            "ytd_reserved_cents": ytd,
            "ytd_reserved_display": format_amount(ytd, symbol),
            "remaining_cents": remaining,
            "remaining_display": format_amount(remaining, symbol),
            "progress": progress,
            "summary": (
                "You pay %s a year for %s. With %s of orders each month, "
                "set aside %s per month (%s of income) so the year is covered."
                % (
                    format_amount(annual, symbol),
                    OVERHEAD_LABEL,
                    format_amount(monthly, symbol),
                    format_amount(monthly_reserve, symbol),
                    rate_display,
                )
            ),
        }

    def _with_reserves(self, orders: List[FoodOrder]) -> List[FoodOrder]:
        annual, monthly = self.overhead_amounts()
        return [
            replace(
                order,
                overhead_reserve_cents=overhead_reserve_cents(
                    order.income_cents, annual, monthly
                ),
            )
            for order in orders
        ]

    def _copy_tagged_expenses(self, connection, stamp: str) -> None:
        already = connection.execute(
            "SELECT value FROM meta WHERE key = 'food_orders_migrated'"
        ).fetchone()
        if already:
            return
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(expenses)").fetchall()
        }
        if "order_name" not in columns:
            connection.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('food_orders_migrated', ?)",
                (stamp,),
            )
            return

        rows = connection.execute(
            "SELECT * FROM expenses WHERE TRIM(order_name) != '' ORDER BY spent_on ASC, id ASC"
        ).fetchall()
        order_ids: Dict[str, int] = {}
        for row in rows:
            key = (row["order_name"] or "").strip().lower()
            if not key:
                continue
            if key not in order_ids:
                cursor = connection.execute(
                    "INSERT INTO food_orders (name, order_date, note, created_at, updated_at) "
                    "VALUES (?, ?, '', ?, ?)",
                    (row["order_name"].strip(), row["spent_on"], stamp, stamp),
                )
                order_ids[key] = int(cursor.lastrowid)
            category = row["category"]
            if _is_income(category):
                kind = INCOME_KIND
                mapped = "Income"
            else:
                kind = COST_KIND
                mapped = _map_order_category(category)
                connection.execute(
                    "INSERT OR IGNORE INTO order_categories (name, created_at) VALUES (?, ?)",
                    (mapped, stamp),
                )
            connection.execute(
                "INSERT INTO order_entries "
                "(order_id, kind, spent_on, item, category, amount_cents, hours, note, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
                (
                    order_ids[key],
                    kind,
                    row["spent_on"],
                    row["item"],
                    mapped,
                    int(row["amount_cents"]),
                    row["note"] or "",
                    stamp,
                    stamp,
                ),
            )
        connection.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('food_orders_migrated', ?)",
            (stamp,),
        )

    def order_categories(self) -> List[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT name FROM order_categories ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [row["name"] for row in rows]

    def add_order_category(self, name: str) -> str:
        clean = _clean_name(name)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT name FROM order_categories WHERE name = ?", (clean,)
            ).fetchone()
            if existing:
                return existing["name"]
            connection.execute(
                "INSERT INTO order_categories (name, created_at) VALUES (?, ?)",
                (clean, _now()),
            )
        return clean

    def create_food_order(self, name: str, order_date=None, note: str = "") -> FoodOrder:
        clean = (name or "").strip()
        if not clean:
            raise ParseError("A food order name is required")
        date_value = parse_date(order_date) if not isinstance(order_date, dt.date) else order_date
        stamp = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO food_orders (name, order_date, note, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (clean, format_date(date_value), (note or "").strip(), stamp, stamp),
            )
            new_id = int(cursor.lastrowid)
        return self.get_food_order(new_id)

    def list_food_orders(
        self,
        start: Optional[dt.date] = None,
        end: Optional[dt.date] = None,
        search: Optional[str] = None,
    ) -> List[FoodOrder]:
        clauses = []
        params: List[object] = []
        if start:
            clauses.append("o.order_date >= ?")
            params.append(format_date(start))
        if end:
            clauses.append("o.order_date <= ?")
            params.append(format_date(end))
        if search:
            clauses.append("o.name LIKE ?")
            params.append("%%%s%%" % search)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        query = (
            "SELECT o.id, o.name, o.order_date, o.note, o.created_at, o.updated_at, "
            "COALESCE(SUM(CASE WHEN e.kind = 'income' THEN e.amount_cents ELSE 0 END), 0) AS income, "
            "COALESCE(SUM(CASE WHEN e.kind = 'cost' THEN e.amount_cents ELSE 0 END), 0) AS cost, "
            "COALESCE(SUM(e.hours), 0) AS hours, "
            "COALESCE(SUM(CASE WHEN e.kind = 'income' THEN 1 ELSE 0 END), 0) AS income_count, "
            "COALESCE(SUM(CASE WHEN e.kind = 'cost' THEN 1 ELSE 0 END), 0) AS expense_count "
            "FROM food_orders o LEFT JOIN order_entries e ON e.order_id = o.id "
            "%s GROUP BY o.id ORDER BY o.order_date DESC, o.id DESC" % where
        )
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return self._with_reserves([_row_to_food_order(row) for row in rows])

    def get_food_order(self, order_id: int, with_entries: bool = True) -> FoodOrder:
        matches = [order for order in self.list_food_orders() if order.id == int(order_id)]
        if not matches:
            raise _error("No food order with id %s" % order_id)
        order = matches[0]
        if not with_entries:
            return order
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM order_entries WHERE order_id = ? ORDER BY spent_on ASC, id ASC",
                (int(order_id),),
            ).fetchall()
        entries = [_row_to_order_entry(row) for row in rows]
        from .storage import Bucket

        buckets: Dict[str, Bucket] = {}
        for entry in entries:
            if entry.kind != COST_KIND:
                continue
            current = buckets.get(entry.category.lower())
            if current is None:
                buckets[entry.category.lower()] = Bucket(
                    key=entry.category, total_cents=entry.amount_cents, count=1
                )
            else:
                buckets[entry.category.lower()] = Bucket(
                    key=current.key,
                    total_cents=current.total_cents + entry.amount_cents,
                    count=current.count + 1,
                )
        cost_categories = sorted(buckets.values(), key=lambda bucket: (-bucket.total_cents, bucket.key.lower()))
        return FoodOrder(
            id=order.id,
            name=order.name,
            order_date=order.order_date,
            note=order.note,
            income_cents=order.income_cents,
            expense_cents=order.expense_cents,
            hours=order.hours,
            income_count=order.income_count,
            expense_count=order.expense_count,
            overhead_reserve_cents=order.overhead_reserve_cents,
            created_at=order.created_at,
            updated_at=order.updated_at,
            entries=entries,
            cost_categories=cost_categories,
        )

    def update_food_order(
        self,
        order_id: int,
        *,
        name: Optional[str] = None,
        order_date=None,
        note: Optional[str] = None,
    ) -> FoodOrder:
        current = self.get_food_order(order_id, with_entries=False)
        updates = {}
        if name is not None:
            clean = name.strip()
            if not clean:
                raise ParseError("A food order name is required")
            updates["name"] = clean
        if order_date is not None:
            date_value = order_date if isinstance(order_date, dt.date) else parse_date(order_date)
            updates["order_date"] = format_date(date_value)
        if note is not None:
            updates["note"] = note.strip()
        if updates:
            updates["updated_at"] = _now()
            assignments = ", ".join("%s = ?" % column for column in updates)
            with self._connect() as connection:
                connection.execute(
                    "UPDATE food_orders SET %s WHERE id = ?" % assignments,
                    (*updates.values(), int(order_id)),
                )
        return self.get_food_order(current.id)

    def delete_food_order(self, order_id: int) -> bool:
        with self._connect() as connection:
            connection.execute("DELETE FROM order_entries WHERE order_id = ?", (int(order_id),))
            cursor = connection.execute("DELETE FROM food_orders WHERE id = ?", (int(order_id),))
        return cursor.rowcount > 0

    def add_order_entry(
        self,
        order_id: int,
        *,
        kind: str,
        item: str,
        amount="",
        category: str = "",
        hours=0,
        spent_on=None,
        note: str = "",
    ) -> OrderEntry:
        self.get_food_order(order_id, with_entries=False)
        clean_kind = (kind or COST_KIND).strip().lower()
        if clean_kind not in {INCOME_KIND, COST_KIND}:
            raise ParseError("Entry type must be income or cost")
        clean_item = (item or "").strip()
        if not clean_item:
            raise ParseError("An item description is required")
        cents = 0 if amount in ("", None) else parse_amount(amount)
        hour_value = parse_hours(hours)
        if clean_kind == INCOME_KIND:
            clean_category = "Income"
        else:
            clean_category = self.add_order_category(category or "Other")
        date_value = parse_date(spent_on) if not isinstance(spent_on, dt.date) else spent_on
        stamp = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO order_entries "
                "(order_id, kind, spent_on, item, category, amount_cents, hours, note, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(order_id),
                    clean_kind,
                    format_date(date_value),
                    clean_item,
                    clean_category,
                    cents,
                    hour_value,
                    (note or "").strip(),
                    stamp,
                    stamp,
                ),
            )
            new_id = int(cursor.lastrowid)
            connection.execute(
                "UPDATE food_orders SET updated_at = ? WHERE id = ?",
                (stamp, int(order_id)),
            )
        return OrderEntry(
            id=new_id,
            order_id=int(order_id),
            kind=clean_kind,
            spent_on=date_value,
            item=clean_item,
            category=clean_category,
            amount_cents=cents,
            hours=hour_value,
            note=(note or "").strip(),
            created_at=stamp,
            updated_at=stamp,
        )

    def update_order_entry(
        self,
        entry_id: int,
        *,
        item: Optional[str] = None,
        amount=None,
        category: Optional[str] = None,
        hours=None,
        spent_on=None,
        note: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> OrderEntry:
        current = self.get_order_entry(entry_id)
        if current is None:
            raise _error("No order entry with id %s" % entry_id)
        updates: Dict[str, object] = {}
        next_kind = current.kind
        if kind is not None:
            next_kind = kind.strip().lower()
            if next_kind not in {INCOME_KIND, COST_KIND}:
                raise ParseError("Entry type must be income or cost")
            updates["kind"] = next_kind
        if item is not None:
            clean_item = item.strip()
            if not clean_item:
                raise ParseError("An item description is required")
            updates["item"] = clean_item
        if amount is not None:
            updates["amount_cents"] = parse_amount(amount)
        if hours is not None:
            updates["hours"] = parse_hours(hours)
        if spent_on is not None:
            date_value = spent_on if isinstance(spent_on, dt.date) else parse_date(spent_on)
            updates["spent_on"] = format_date(date_value)
        if note is not None:
            updates["note"] = note.strip()
        if next_kind == INCOME_KIND:
            updates["category"] = "Income"
        elif category is not None:
            updates["category"] = self.add_order_category(category)
        if not updates:
            return current
        updates["updated_at"] = _now()
        assignments = ", ".join("%s = ?" % column for column in updates)
        with self._connect() as connection:
            connection.execute(
                "UPDATE order_entries SET %s WHERE id = ?" % assignments,
                (*updates.values(), int(entry_id)),
            )
            connection.execute(
                "UPDATE food_orders SET updated_at = ? WHERE id = ?",
                (updates["updated_at"], current.order_id),
            )
        updated = self.get_order_entry(entry_id)
        assert updated is not None
        return updated

    def get_order_entry(self, entry_id: int) -> Optional[OrderEntry]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM order_entries WHERE id = ?", (int(entry_id),)
            ).fetchone()
        return _row_to_order_entry(row) if row else None

    def delete_order_entry(self, entry_id: int) -> bool:
        current = self.get_order_entry(entry_id)
        if current is None:
            return False
        with self._connect() as connection:
            connection.execute("DELETE FROM order_entries WHERE id = ?", (int(entry_id),))
            connection.execute(
                "UPDATE food_orders SET updated_at = ? WHERE id = ?",
                (_now(), current.order_id),
            )
        return True


def overhead_reserve_cents(income_cents: int, annual_cents: int, monthly_income_cents: int) -> int:
    """Share of this order's income to set aside for annual overhead.

    With $1,200/year overhead and $1,200/month of orders, that is $100 per
    month, or one twelfth of the order's income.
    """

    if income_cents <= 0 or annual_cents <= 0 or monthly_income_cents <= 0:
        return 0
    return int(round(income_cents * annual_cents / (12.0 * monthly_income_cents)))


def _meta_cents(raw, default: int) -> int:
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def _map_order_category(name: str) -> str:
    clean = (name or "").strip()
    if not clean:
        return "Other"
    return _CATEGORY_ALIASES.get(clean.lower(), clean)


def _now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _clean_name(name: str) -> str:
    clean = (name or "").strip()
    if not clean:
        raise ParseError("A category name is required")
    return clean


def _is_income(name: Optional[str]) -> bool:
    return (name or "").strip().lower() == "income"


def _error(message: str):
    from .storage import StorageError

    return StorageError(message)


def _row_to_food_order(row) -> FoodOrder:
    return FoodOrder(
        id=int(row["id"]),
        name=row["name"],
        order_date=parse_date(row["order_date"]),
        note=row["note"] or "",
        income_cents=int(row["income"] or 0),
        expense_cents=int(row["cost"] or 0),
        hours=float(row["hours"] or 0),
        income_count=int(row["income_count"] or 0),
        expense_count=int(row["expense_count"] or 0),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_order_entry(row) -> OrderEntry:
    return OrderEntry(
        id=int(row["id"]),
        order_id=int(row["order_id"]),
        kind=row["kind"],
        spent_on=parse_date(row["spent_on"]),
        item=row["item"],
        category=row["category"],
        amount_cents=int(row["amount_cents"]),
        hours=float(row["hours"] or 0),
        note=row["note"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
