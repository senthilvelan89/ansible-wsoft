"""SQLite storage for expenses, categories and the retention window."""

from __future__ import annotations

import csv
import datetime as dt
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence

from . import DEFAULT_RETENTION_MONTHS
from .parsing import (
    ParseError,
    add_months,
    format_amount,
    format_date,
    parse_amount,
    parse_date,
    today,
)

SCHEMA_VERSION = 1

DEFAULT_CATEGORIES = (
    "Groceries",
    "Dining",
    "Transport",
    "Housing",
    "Utilities",
    "Health",
    "Shopping",
    "Entertainment",
    "Travel",
    "Education",
    "Personal",
    "Other",
)

EXPORT_COLUMNS = ("id", "date", "item", "category", "amount", "note", "created_at")


class StorageError(RuntimeError):
    """Raised for operations the database cannot satisfy."""


@dataclass(frozen=True)
class Expense:
    id: int
    spent_on: dt.date
    item: str
    category: str
    amount_cents: int
    note: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self, symbol: str = "$") -> Dict[str, object]:
        return {
            "id": self.id,
            "date": format_date(self.spent_on),
            "item": self.item,
            "category": self.category,
            "amount_cents": self.amount_cents,
            "amount": self.amount_cents / 100,
            "amount_display": format_amount(self.amount_cents, symbol),
            "note": self.note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class Bucket:
    """One row of an aggregate report."""

    key: str
    total_cents: int
    count: int

    def to_dict(self, symbol: str = "$") -> Dict[str, object]:
        return {
            "key": self.key,
            "total_cents": self.total_cents,
            "total": self.total_cents / 100,
            "total_display": format_amount(self.total_cents, symbol),
            "count": self.count,
        }


@dataclass
class PruneResult:
    cutoff: dt.date
    archived: List[Expense] = field(default_factory=list)
    archive_path: Optional[Path] = None
    dry_run: bool = False

    @property
    def count(self) -> int:
        return len(self.archived)

    @property
    def total_cents(self) -> int:
        return sum(expense.amount_cents for expense in self.archived)


def default_home() -> Path:
    override = os.environ.get("EXPENSE_TRACKER_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".expense-tracker"


def default_db_path() -> Path:
    override = os.environ.get("EXPENSE_TRACKER_DB")
    if override:
        return Path(override).expanduser()
    return default_home() / "expenses.db"


class Database:
    """All persistence lives here; a connection is opened per operation.

    Opening per operation keeps the class safe to share between the threads of
    the bundled web server without holding locks across requests.
    """

    def __init__(self, path: Optional[os.PathLike] = None):
        self.path = Path(path).expanduser() if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    # ----------------------------------------------------------------- setup

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS categories (
                    name       TEXT PRIMARY KEY COLLATE NOCASE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS expenses (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    spent_on     TEXT    NOT NULL,
                    item         TEXT    NOT NULL,
                    category     TEXT    NOT NULL COLLATE NOCASE,
                    amount_cents INTEGER NOT NULL,
                    note         TEXT    NOT NULL DEFAULT '',
                    created_at   TEXT    NOT NULL,
                    updated_at   TEXT    NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_expenses_spent_on
                    ON expenses (spent_on);
                CREATE INDEX IF NOT EXISTS idx_expenses_category
                    ON expenses (category);
                """
            )
            existing = connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            if existing is None:
                stamp = _timestamp()
                connection.executemany(
                    "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                    [
                        ("schema_version", str(SCHEMA_VERSION)),
                        ("currency_symbol", os.environ.get("EXPENSE_TRACKER_CURRENCY", "$")),
                        ("retention_months", str(DEFAULT_RETENTION_MONTHS)),
                        ("created_at", stamp),
                    ],
                )
                connection.executemany(
                    "INSERT OR IGNORE INTO categories (name, created_at) VALUES (?, ?)",
                    [(name, stamp) for name in DEFAULT_CATEGORIES],
                )

    # -------------------------------------------------------------- settings

    def get_setting(self, key: str, fallback: Optional[str] = None) -> Optional[str]:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else fallback

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    @property
    def currency_symbol(self) -> str:
        return self.get_setting("currency_symbol", "$") or "$"

    @property
    def retention_months(self) -> int:
        raw = self.get_setting("retention_months", str(DEFAULT_RETENTION_MONTHS))
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return DEFAULT_RETENTION_MONTHS

    # ------------------------------------------------------------ categories

    def categories(self) -> List[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT name FROM categories ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [row["name"] for row in rows]

    def add_category(self, name: str) -> str:
        clean = _clean_category(name)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT name FROM categories WHERE name = ?", (clean,)
            ).fetchone()
            if existing:
                return existing["name"]
            connection.execute(
                "INSERT INTO categories (name, created_at) VALUES (?, ?)",
                (clean, _timestamp()),
            )
        return clean

    def rename_category(self, old: str, new: str) -> int:
        source = _clean_category(old)
        target = _clean_category(new)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT name FROM categories WHERE name = ?", (source,)
            ).fetchone()
            if row is None:
                raise StorageError("No category named %r" % old)
            connection.execute(
                "INSERT OR IGNORE INTO categories (name, created_at) VALUES (?, ?)",
                (target, _timestamp()),
            )
            cursor = connection.execute(
                "UPDATE expenses SET category = ?, updated_at = ? WHERE category = ?",
                (target, _timestamp(), source),
            )
            if source.lower() != target.lower():
                connection.execute("DELETE FROM categories WHERE name = ?", (source,))
        return cursor.rowcount

    def delete_category(self, name: str, reassign_to: Optional[str] = None) -> int:
        source = _clean_category(name)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT name FROM categories WHERE name = ?", (source,)
            ).fetchone()
            if row is None:
                raise StorageError("No category named %r" % name)
            used = connection.execute(
                "SELECT COUNT(*) AS total FROM expenses WHERE category = ?", (source,)
            ).fetchone()["total"]
            moved = 0
            if used:
                if not reassign_to:
                    raise StorageError(
                        "%r still has %d expense(s); pass a category to move them to"
                        % (row["name"], used)
                    )
                target = _clean_category(reassign_to)
                connection.execute(
                    "INSERT OR IGNORE INTO categories (name, created_at) VALUES (?, ?)",
                    (target, _timestamp()),
                )
                cursor = connection.execute(
                    "UPDATE expenses SET category = ?, updated_at = ? WHERE category = ?",
                    (target, _timestamp(), source),
                )
                moved = cursor.rowcount
            connection.execute("DELETE FROM categories WHERE name = ?", (source,))
        return moved

    # -------------------------------------------------------------- expenses

    def add_expense(
        self,
        item: str,
        amount,
        category: str,
        spent_on=None,
        note: str = "",
    ) -> Expense:
        clean_item = (item or "").strip()
        if not clean_item:
            raise ParseError("An item description is required")
        cents = amount if isinstance(amount, int) and not isinstance(amount, bool) else parse_amount(amount)
        clean_category = self.add_category(category or "Other")
        date_value = parse_date(spent_on) if not isinstance(spent_on, dt.date) else spent_on
        stamp = _timestamp()

        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO expenses (spent_on, item, category, amount_cents, note, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    format_date(date_value),
                    clean_item,
                    clean_category,
                    cents,
                    (note or "").strip(),
                    stamp,
                    stamp,
                ),
            )
            new_id = int(cursor.lastrowid)
        return Expense(
            id=new_id,
            spent_on=date_value,
            item=clean_item,
            category=clean_category,
            amount_cents=cents,
            note=(note or "").strip(),
            created_at=stamp,
            updated_at=stamp,
        )

    def get_expense(self, expense_id: int) -> Optional[Expense]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM expenses WHERE id = ?", (int(expense_id),)
            ).fetchone()
        return _row_to_expense(row) if row else None

    def update_expense(
        self,
        expense_id: int,
        *,
        item: Optional[str] = None,
        amount=None,
        category: Optional[str] = None,
        spent_on=None,
        note: Optional[str] = None,
    ) -> Expense:
        current = self.get_expense(expense_id)
        if current is None:
            raise StorageError("No expense with id %s" % expense_id)

        updates: Dict[str, object] = {}
        if item is not None:
            clean_item = item.strip()
            if not clean_item:
                raise ParseError("An item description is required")
            updates["item"] = clean_item
        if amount is not None:
            updates["amount_cents"] = parse_amount(amount)
        if category is not None:
            updates["category"] = self.add_category(category)
        if spent_on is not None:
            updates["spent_on"] = format_date(
                spent_on if isinstance(spent_on, dt.date) else parse_date(spent_on)
            )
        if note is not None:
            updates["note"] = note.strip()

        if not updates:
            return current

        updates["updated_at"] = _timestamp()
        assignments = ", ".join("%s = ?" % column for column in updates)
        with self._connect() as connection:
            connection.execute(
                "UPDATE expenses SET %s WHERE id = ?" % assignments,
                (*updates.values(), int(expense_id)),
            )
        updated = self.get_expense(expense_id)
        assert updated is not None
        return updated

    def delete_expense(self, expense_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM expenses WHERE id = ?", (int(expense_id),))
        return cursor.rowcount > 0

    def list_expenses(
        self,
        start: Optional[dt.date] = None,
        end: Optional[dt.date] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
        limit: Optional[int] = None,
        newest_first: bool = True,
    ) -> List[Expense]:
        where, params = _range_clause(start, end, category, search)
        order = "spent_on DESC, id DESC" if newest_first else "spent_on ASC, id ASC"
        query = "SELECT * FROM expenses %s ORDER BY %s" % (where, order)
        if limit:
            query += " LIMIT %d" % int(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_row_to_expense(row) for row in rows]

    def totals(
        self,
        start: Optional[dt.date] = None,
        end: Optional[dt.date] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Bucket:
        where, params = _range_clause(start, end, category, search)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(amount_cents), 0) AS total, COUNT(*) AS count FROM expenses %s"
                % where,
                params,
            ).fetchone()
        return Bucket(key="total", total_cents=int(row["total"]), count=int(row["count"]))

    def summary(
        self,
        group_by: str = "category",
        start: Optional[dt.date] = None,
        end: Optional[dt.date] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Bucket]:
        expressions = {
            "category": "category",
            "month": "substr(spent_on, 1, 7)",
            "day": "spent_on",
            "item": "item",
        }
        if group_by not in expressions:
            raise StorageError(
                "Cannot group by %r, choose one of %s"
                % (group_by, ", ".join(sorted(expressions)))
            )
        where, params = _range_clause(start, end, category, search)
        expression = expressions[group_by]
        order = "bucket ASC" if group_by in {"month", "day"} else "total DESC, bucket ASC"
        query = (
            "SELECT %s AS bucket, SUM(amount_cents) AS total, COUNT(*) AS count "
            "FROM expenses %s GROUP BY bucket ORDER BY %s" % (expression, where, order)
        )
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            Bucket(key=str(row["bucket"]), total_cents=int(row["total"]), count=int(row["count"]))
            for row in rows
        ]

    def date_span(self) -> Optional[tuple]:
        """Return the oldest and newest recorded dates, if any."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT MIN(spent_on) AS oldest, MAX(spent_on) AS newest FROM expenses"
            ).fetchone()
        if not row or row["oldest"] is None:
            return None
        return parse_date(row["oldest"]), parse_date(row["newest"])

    # ------------------------------------------------------------- retention

    def retention_cutoff(self, reference: Optional[dt.date] = None) -> dt.date:
        """Expenses dated before this day fall outside the retention window."""

        return add_months(reference or today(), -self.retention_months)

    def prune(
        self,
        reference: Optional[dt.date] = None,
        dry_run: bool = False,
        archive_path: Optional[Path] = None,
    ) -> PruneResult:
        """Archive then delete expenses older than the retention window."""

        cutoff = self.retention_cutoff(reference)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM expenses WHERE spent_on < ? ORDER BY spent_on ASC, id ASC",
                (format_date(cutoff),),
            ).fetchall()
        expired = [_row_to_expense(row) for row in rows]
        result = PruneResult(cutoff=cutoff, archived=expired, dry_run=dry_run)
        if not expired or dry_run:
            return result

        target = Path(archive_path) if archive_path else self.archive_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        write_header = not target.exists() or target.stat().st_size == 0
        with target.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if write_header:
                writer.writerow(EXPORT_COLUMNS)
            for expense in expired:
                writer.writerow(_expense_to_row(expense))

        with self._connect() as connection:
            connection.execute(
                "DELETE FROM expenses WHERE spent_on < ?", (format_date(cutoff),)
            )
        self.set_setting("last_prune_at", _timestamp())
        result.archive_path = target
        return result

    def archive_path(self) -> Path:
        return self.path.parent / "archive" / "expenses-archive.csv"

    # --------------------------------------------------------- import/export

    def export_csv(self, handle, expenses: Optional[Sequence[Expense]] = None) -> int:
        rows = list(expenses) if expenses is not None else self.list_expenses(newest_first=False)
        writer = csv.writer(handle)
        writer.writerow(EXPORT_COLUMNS)
        for expense in rows:
            writer.writerow(_expense_to_row(expense))
        return len(rows)

    def import_csv(self, handle) -> int:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise StorageError("The CSV file is empty")
        headers = {name.strip().lower() for name in reader.fieldnames}
        required = {"date", "item", "amount"}
        missing = required - headers
        if missing:
            raise StorageError(
                "CSV is missing required column(s): %s" % ", ".join(sorted(missing))
            )

        imported = 0
        for line_number, raw in enumerate(reader, start=2):
            record = {
                (key or "").strip().lower(): (value or "").strip()
                for key, value in raw.items()
            }
            if not any(record.values()):
                continue
            try:
                self.add_expense(
                    item=record.get("item", ""),
                    amount=record.get("amount", ""),
                    category=record.get("category") or "Other",
                    spent_on=record.get("date") or None,
                    note=record.get("note", ""),
                )
            except (ParseError, StorageError) as error:
                raise StorageError("Line %d: %s" % (line_number, error)) from None
            imported += 1
        return imported


def _range_clause(
    start: Optional[dt.date],
    end: Optional[dt.date],
    category: Optional[str] = None,
    search: Optional[str] = None,
) -> tuple:
    clauses: List[str] = []
    params: List[object] = []
    if start:
        clauses.append("spent_on >= ?")
        params.append(format_date(start))
    if end:
        clauses.append("spent_on <= ?")
        params.append(format_date(end))
    if category:
        clauses.append("category = ?")
        params.append(_clean_category(category))
    if search:
        clauses.append("(item LIKE ? OR note LIKE ?)")
        pattern = "%%%s%%" % search
        params.extend([pattern, pattern])
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _row_to_expense(row: sqlite3.Row) -> Expense:
    return Expense(
        id=int(row["id"]),
        spent_on=parse_date(row["spent_on"]),
        item=row["item"],
        category=row["category"],
        amount_cents=int(row["amount_cents"]),
        note=row["note"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _expense_to_row(expense: Expense) -> Iterable[object]:
    return (
        expense.id,
        format_date(expense.spent_on),
        expense.item,
        expense.category,
        "%.2f" % (expense.amount_cents / 100),
        expense.note,
        expense.created_at,
    )


def _clean_category(name: str) -> str:
    clean = (name or "").strip()
    if not clean:
        raise ParseError("A category name is required")
    return clean


def _timestamp() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")
