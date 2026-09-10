"""SQLite storage for categories, queued tasks and dated comments."""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from .parsing import (
    ParseError,
    format_date,
    parse_date,
    parse_optional_date,
    today,
)

SCHEMA_VERSION = 1

DEFAULT_CATEGORIES = (
    "Career",
    "Property",
    "Family",
    "Admin",
    "Finance",
    "Home",
    "Health",
    "Personal",
)

OPEN = "open"
DONE = "done"
STATUSES = (OPEN, DONE)


class StorageError(RuntimeError):
    """Raised for operations the database cannot satisfy."""


@dataclass(frozen=True)
class Category:
    id: int
    name: str
    sort_order: int
    created_at: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "sort_order": self.sort_order,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class Task:
    id: int
    category_id: int
    category: str
    title: str
    due_on: Optional[dt.date]
    status: str
    position: int
    created_at: str = ""
    updated_at: str = ""
    completed_at: Optional[str] = None

    def is_overdue(self, reference: Optional[dt.date] = None) -> bool:
        if self.status != OPEN or self.due_on is None:
            return False
        return self.due_on < (reference or today())

    def is_due_today(self, reference: Optional[dt.date] = None) -> bool:
        if self.status != OPEN or self.due_on is None:
            return False
        return self.due_on == (reference or today())

    def to_dict(self, reference: Optional[dt.date] = None) -> Dict[str, object]:
        ref = reference or today()
        return {
            "id": self.id,
            "category_id": self.category_id,
            "category": self.category,
            "title": self.title,
            "due_on": format_date(self.due_on),
            "status": self.status,
            "position": self.position,
            "is_overdue": self.is_overdue(ref),
            "is_due_today": self.is_due_today(ref),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }


@dataclass(frozen=True)
class Comment:
    id: int
    category_id: int
    category: str
    task_id: Optional[int]
    task_title: Optional[str]
    body: str
    comment_on: dt.date
    created_at: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "category_id": self.category_id,
            "category": self.category,
            "task_id": self.task_id,
            "task_title": self.task_title,
            "body": self.body,
            "comment_on": format_date(self.comment_on),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class CategoryBoard:
    category: Category
    next_step: Optional[Task]
    upcoming: List[Task]
    latest_comment: Optional[Comment]
    open_count: int
    done_count: int

    def to_dict(self, reference: Optional[dt.date] = None) -> Dict[str, object]:
        ref = reference or today()
        payload = self.category.to_dict()
        payload.update(
            {
                "next_step": self.next_step.to_dict(ref) if self.next_step else None,
                "upcoming": [task.to_dict(ref) for task in self.upcoming],
                "latest_comment": self.latest_comment.to_dict() if self.latest_comment else None,
                "open_count": self.open_count,
                "done_count": self.done_count,
            }
        )
        return payload


def default_home() -> Path:
    override = os.environ.get("TASK_PLANNER_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".task-planner"


def default_db_path() -> Path:
    override = os.environ.get("TASK_PLANNER_DB")
    if override:
        return Path(override).expanduser()
    return default_home() / "tasks.db"


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
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    name       TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                    sort_order INTEGER NOT NULL,
                    created_at TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_id  INTEGER NOT NULL REFERENCES categories(id),
                    title        TEXT    NOT NULL,
                    due_on       TEXT,
                    status       TEXT    NOT NULL DEFAULT 'open',
                    position     INTEGER NOT NULL,
                    created_at   TEXT    NOT NULL,
                    updated_at   TEXT    NOT NULL,
                    completed_at TEXT,
                    CHECK (status IN ('open', 'done'))
                );

                CREATE TABLE IF NOT EXISTS comments (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_id INTEGER NOT NULL REFERENCES categories(id),
                    task_id     INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                    body        TEXT    NOT NULL,
                    comment_on  TEXT    NOT NULL,
                    created_at  TEXT    NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_category_status
                    ON tasks (category_id, status, position);
                CREATE INDEX IF NOT EXISTS idx_tasks_due_on
                    ON tasks (due_on);
                CREATE INDEX IF NOT EXISTS idx_comments_comment_on
                    ON comments (comment_on);
                CREATE INDEX IF NOT EXISTS idx_comments_category
                    ON comments (category_id);
                """
            )
            existing = connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            if existing is None:
                stamp = _timestamp()
                connection.executemany(
                    "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                    [
                        ("schema_version", str(SCHEMA_VERSION)),
                        ("created_at", stamp),
                    ],
                )
                connection.executemany(
                    "INSERT OR IGNORE INTO categories (name, sort_order, created_at) VALUES (?, ?, ?)",
                    [(name, index, stamp) for index, name in enumerate(DEFAULT_CATEGORIES)],
                )

    # -------------------------------------------------------------- settings

    def get_setting(self, key: str, fallback: Optional[str] = None) -> Optional[str]:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else fallback

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # ------------------------------------------------------------ categories

    def categories(self) -> List[Category]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, name, sort_order, created_at FROM categories ORDER BY sort_order, name"
            ).fetchall()
        return [_category_from_row(row) for row in rows]

    def get_category(self, name: str) -> Optional[Category]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, name, sort_order, created_at FROM categories WHERE name = ? COLLATE NOCASE",
                (name.strip(),),
            ).fetchone()
        return _category_from_row(row) if row else None

    def get_category_by_id(self, category_id: int) -> Optional[Category]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, name, sort_order, created_at FROM categories WHERE id = ?",
                (category_id,),
            ).fetchone()
        return _category_from_row(row) if row else None

    def add_category(self, name: str) -> Category:
        cleaned = _clean_name(name)
        if self.get_category(cleaned):
            raise StorageError("Category %r already exists" % cleaned)
        stamp = _timestamp()
        with self._connect() as connection:
            next_order = connection.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM categories"
            ).fetchone()[0]
            cursor = connection.execute(
                "INSERT INTO categories (name, sort_order, created_at) VALUES (?, ?, ?)",
                (cleaned, next_order, stamp),
            )
            category_id = cursor.lastrowid
        return Category(id=category_id, name=cleaned, sort_order=next_order, created_at=stamp)

    def rename_category(self, old: str, new: str) -> Category:
        category = self._require_category(old)
        cleaned = _clean_name(new)
        if cleaned.lower() != category.name.lower() and self.get_category(cleaned):
            raise StorageError("Category %r already exists" % cleaned)
        with self._connect() as connection:
            connection.execute("UPDATE categories SET name = ? WHERE id = ?", (cleaned, category.id))
        updated = self.get_category_by_id(category.id)
        assert updated is not None
        return updated

    def delete_category(self, name: str, *, move_to: Optional[str] = None) -> int:
        category = self._require_category(name)
        target = self._require_category(move_to) if move_to else None
        if target and target.id == category.id:
            raise StorageError("Cannot move tasks into the category being deleted")
        with self._connect() as connection:
            open_count = connection.execute(
                "SELECT COUNT(*) FROM tasks WHERE category_id = ? AND status = ?",
                (category.id, OPEN),
            ).fetchone()[0]
            if open_count and target is None:
                raise StorageError(
                    "Category %r still has %d open task(s). Move them with --move-to, or finish them first."
                    % (category.name, open_count)
                )
            task_count = connection.execute(
                "SELECT COUNT(*) FROM tasks WHERE category_id = ?",
                (category.id,),
            ).fetchone()[0]
            if target:
                max_position = connection.execute(
                    "SELECT COALESCE(MAX(position), -1) FROM tasks WHERE category_id = ? AND status = ?",
                    (target.id, OPEN),
                ).fetchone()[0]
                open_rows = connection.execute(
                    "SELECT id FROM tasks WHERE category_id = ? AND status = ? ORDER BY position, id",
                    (category.id, OPEN),
                ).fetchall()
                for offset, row in enumerate(open_rows, start=1):
                    connection.execute(
                        "UPDATE tasks SET category_id = ?, position = ? WHERE id = ?",
                        (target.id, max_position + offset, row["id"]),
                    )
                connection.execute(
                    "UPDATE tasks SET category_id = ? WHERE category_id = ?",
                    (target.id, category.id),
                )
                connection.execute(
                    "UPDATE comments SET category_id = ? WHERE category_id = ?",
                    (target.id, category.id),
                )
            else:
                connection.execute("DELETE FROM comments WHERE category_id = ?", (category.id,))
                connection.execute("DELETE FROM tasks WHERE category_id = ?", (category.id,))
            connection.execute("DELETE FROM categories WHERE id = ?", (category.id,))
        return task_count

    def _require_category(self, name: str) -> Category:
        category = self.get_category(name)
        if category is None:
            raise StorageError("Unknown category %r" % name)
        return category

    def _require_category_id(self, category_id: int) -> Category:
        category = self.get_category_by_id(category_id)
        if category is None:
            raise StorageError("Unknown category id %d" % category_id)
        return category

    # ----------------------------------------------------------------- tasks

    def add_task(
        self,
        title: str,
        category: str,
        due_on=None,
        *,
        as_next: bool = False,
    ) -> Task:
        cleaned = _clean_title(title)
        cat = self.get_category(category)
        if cat is None:
            cat = self.add_category(category)
        due = parse_optional_date(due_on)
        stamp = _timestamp()
        with self._connect() as connection:
            if as_next:
                connection.execute(
                    "UPDATE tasks SET position = position + 1 WHERE category_id = ? AND status = ?",
                    (cat.id, OPEN),
                )
                position = 0
            else:
                position = connection.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM tasks WHERE category_id = ? AND status = ?",
                    (cat.id, OPEN),
                ).fetchone()[0]
            cursor = connection.execute(
                """
                INSERT INTO tasks (category_id, title, due_on, status, position, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (cat.id, cleaned, format_date(due), OPEN, position, stamp, stamp),
            )
            task_id = cursor.lastrowid
        task = self.get_task(task_id)
        assert task is not None
        return task

    def get_task(self, task_id: int) -> Optional[Task]:
        with self._connect() as connection:
            row = connection.execute(_TASK_SELECT + " WHERE t.id = ?", (task_id,)).fetchone()
        return _task_from_row(row) if row else None

    def list_tasks(
        self,
        *,
        category: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        due_start: Optional[dt.date] = None,
        due_end: Optional[dt.date] = None,
        limit: Optional[int] = None,
    ) -> List[Task]:
        clauses = []
        params: List[object] = []
        if category:
            clauses.append("c.name = ? COLLATE NOCASE")
            params.append(category)
        if status:
            if status not in STATUSES:
                raise ParseError("Status must be 'open' or 'done'")
            clauses.append("t.status = ?")
            params.append(status)
        if search:
            clauses.append("t.title LIKE ?")
            params.append("%" + search.strip() + "%")
        if due_start:
            clauses.append("t.due_on IS NOT NULL AND t.due_on >= ?")
            params.append(format_date(due_start))
        if due_end:
            clauses.append("t.due_on IS NOT NULL AND t.due_on <= ?")
            params.append(format_date(due_end))

        sql = _TASK_SELECT
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += """
            ORDER BY
                CASE t.status WHEN 'open' THEN 0 ELSE 1 END,
                CASE WHEN t.status = 'open' THEN t.position ELSE 0 END,
                t.due_on IS NULL,
                t.due_on,
                t.id
        """
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))

        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_task_from_row(row) for row in rows]

    def update_task(
        self,
        task_id: int,
        *,
        title: Optional[str] = None,
        category: Optional[str] = None,
        due_on=None,
        clear_due: bool = False,
    ) -> Task:
        task = self._require_task(task_id)
        new_title = _clean_title(title) if title is not None else task.title
        new_due = task.due_on
        if clear_due:
            new_due = None
        elif due_on is not None:
            new_due = parse_optional_date(due_on)

        new_category_id = task.category_id
        if category is not None:
            cat = self.get_category(category)
            if cat is None:
                cat = self.add_category(category)
            new_category_id = cat.id

        stamp = _timestamp()
        with self._connect() as connection:
            if new_category_id != task.category_id and task.status == OPEN:
                position = connection.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM tasks WHERE category_id = ? AND status = ?",
                    (new_category_id, OPEN),
                ).fetchone()[0]
            else:
                position = task.position
            connection.execute(
                """
                UPDATE tasks
                   SET title = ?, category_id = ?, due_on = ?, position = ?, updated_at = ?
                 WHERE id = ?
                """,
                (new_title, new_category_id, format_date(new_due), position, stamp, task_id),
            )
        updated = self.get_task(task_id)
        assert updated is not None
        return updated

    def complete_task(self, task_id: int) -> Task:
        task = self._require_task(task_id)
        if task.status == DONE:
            return task
        stamp = _timestamp()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                   SET status = ?, completed_at = ?, updated_at = ?
                 WHERE id = ?
                """,
                (DONE, stamp, stamp, task_id),
            )
            connection.execute(
                "UPDATE tasks SET position = position - 1 WHERE category_id = ? AND status = ? AND position > ?",
                (task.category_id, OPEN, task.position),
            )
        updated = self.get_task(task_id)
        assert updated is not None
        return updated

    def reopen_task(self, task_id: int, *, as_next: bool = False) -> Task:
        task = self._require_task(task_id)
        if task.status == OPEN:
            return task
        stamp = _timestamp()
        with self._connect() as connection:
            if as_next:
                connection.execute(
                    "UPDATE tasks SET position = position + 1 WHERE category_id = ? AND status = ?",
                    (task.category_id, OPEN),
                )
                position = 0
            else:
                position = connection.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM tasks WHERE category_id = ? AND status = ?",
                    (task.category_id, OPEN),
                ).fetchone()[0]
            connection.execute(
                """
                UPDATE tasks
                   SET status = ?, completed_at = NULL, position = ?, updated_at = ?
                 WHERE id = ?
                """,
                (OPEN, position, stamp, task_id),
            )
        updated = self.get_task(task_id)
        assert updated is not None
        return updated

    def delete_task(self, task_id: int) -> bool:
        task = self.get_task(task_id)
        if task is None:
            return False
        with self._connect() as connection:
            connection.execute("UPDATE comments SET task_id = NULL WHERE task_id = ?", (task_id,))
            connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            if task.status == OPEN:
                connection.execute(
                    "UPDATE tasks SET position = position - 1 WHERE category_id = ? AND status = ? AND position > ?",
                    (task.category_id, OPEN, task.position),
                )
        return True

    def next_step(self, category: str) -> Optional[Task]:
        cat = self._require_category(category)
        with self._connect() as connection:
            row = connection.execute(
                _TASK_SELECT + " WHERE t.category_id = ? AND t.status = ? ORDER BY t.position, t.id LIMIT 1",
                (cat.id, OPEN),
            ).fetchone()
        return _task_from_row(row) if row else None

    def move_task(self, task_id: int, direction: str) -> Task:
        task = self._require_task(task_id)
        if task.status != OPEN:
            raise StorageError("Only open tasks can be reordered")
        delta = -1 if direction in {"up", "next", "sooner"} else 1
        with self._connect() as connection:
            neighbour = connection.execute(
                """
                SELECT id, position FROM tasks
                 WHERE category_id = ? AND status = ? AND position = ?
                """,
                (task.category_id, OPEN, task.position + delta),
            ).fetchone()
            if neighbour is None:
                return task
            connection.execute(
                "UPDATE tasks SET position = ?, updated_at = ? WHERE id = ?",
                (neighbour["position"], _timestamp(), task.id),
            )
            connection.execute(
                "UPDATE tasks SET position = ?, updated_at = ? WHERE id = ?",
                (task.position, _timestamp(), neighbour["id"]),
            )
        updated = self.get_task(task_id)
        assert updated is not None
        return updated

    def _require_task(self, task_id: int) -> Task:
        task = self.get_task(task_id)
        if task is None:
            raise StorageError("No task with id %d" % task_id)
        return task

    # -------------------------------------------------------------- comments

    def add_comment(
        self,
        body: str,
        *,
        category: Optional[str] = None,
        task_id: Optional[int] = None,
        comment_on=None,
    ) -> Comment:
        cleaned = (body or "").strip()
        if not cleaned:
            raise ParseError("Comment text is required")
        if len(cleaned) > 2000:
            raise ParseError("Comment is too long")

        task = None
        if task_id is not None:
            task = self._require_task(int(task_id))
            cat = self.get_category_by_id(task.category_id)
            assert cat is not None
        elif category:
            cat = self._require_category(category)
        else:
            raise ParseError("A category or task is required for a comment")

        when = parse_date(comment_on) if comment_on not in (None, "") else today()
        stamp = _timestamp()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO comments (category_id, task_id, body, comment_on, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (cat.id, task.id if task else None, cleaned, format_date(when), stamp),
            )
            comment_id = cursor.lastrowid
        comment = self.get_comment(comment_id)
        assert comment is not None
        return comment

    def get_comment(self, comment_id: int) -> Optional[Comment]:
        with self._connect() as connection:
            row = connection.execute(_COMMENT_SELECT + " WHERE n.id = ?", (comment_id,)).fetchone()
        return _comment_from_row(row) if row else None

    def list_comments(
        self,
        *,
        category: Optional[str] = None,
        task_id: Optional[int] = None,
        start: Optional[dt.date] = None,
        end: Optional[dt.date] = None,
        limit: Optional[int] = None,
    ) -> List[Comment]:
        clauses = []
        params: List[object] = []
        if category:
            clauses.append("c.name = ? COLLATE NOCASE")
            params.append(category)
        if task_id is not None:
            clauses.append("n.task_id = ?")
            params.append(int(task_id))
        if start:
            clauses.append("n.comment_on >= ?")
            params.append(format_date(start))
        if end:
            clauses.append("n.comment_on <= ?")
            params.append(format_date(end))

        sql = _COMMENT_SELECT
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY n.comment_on DESC, n.id DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))

        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_comment_from_row(row) for row in rows]

    def delete_comment(self, comment_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
            return cursor.rowcount > 0

    # ----------------------------------------------------------------- board

    def board(self, upcoming_limit: int = 4) -> List[CategoryBoard]:
        categories = self.categories()
        boards: List[CategoryBoard] = []
        with self._connect() as connection:
            for category in categories:
                open_rows = connection.execute(
                    _TASK_SELECT + " WHERE t.category_id = ? AND t.status = ? ORDER BY t.position, t.id",
                    (category.id, OPEN),
                ).fetchall()
                open_tasks = [_task_from_row(row) for row in open_rows]
                done_count = connection.execute(
                    "SELECT COUNT(*) FROM tasks WHERE category_id = ? AND status = ?",
                    (category.id, DONE),
                ).fetchone()[0]
                comment_row = connection.execute(
                    _COMMENT_SELECT + " WHERE n.category_id = ? ORDER BY n.comment_on DESC, n.id DESC LIMIT 1",
                    (category.id,),
                ).fetchone()
                next_step = open_tasks[0] if open_tasks else None
                upcoming = open_tasks[1 : 1 + upcoming_limit]
                boards.append(
                    CategoryBoard(
                        category=category,
                        next_step=next_step,
                        upcoming=upcoming,
                        latest_comment=_comment_from_row(comment_row) if comment_row else None,
                        open_count=len(open_tasks),
                        done_count=done_count,
                    )
                )
        return boards

    def stats(self, reference: Optional[dt.date] = None) -> Dict[str, int]:
        ref = reference or today()
        stamp = format_date(ref)
        week_end = format_date(ref + dt.timedelta(days=7))
        with self._connect() as connection:
            categories = connection.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
            open_tasks = connection.execute(
                "SELECT COUNT(*) FROM tasks WHERE status = ?", (OPEN,)
            ).fetchone()[0]
            with_next = connection.execute(
                "SELECT COUNT(DISTINCT category_id) FROM tasks WHERE status = ?", (OPEN,)
            ).fetchone()[0]
            overdue = connection.execute(
                "SELECT COUNT(*) FROM tasks WHERE status = ? AND due_on IS NOT NULL AND due_on < ?",
                (OPEN, stamp),
            ).fetchone()[0]
            due_today = connection.execute(
                "SELECT COUNT(*) FROM tasks WHERE status = ? AND due_on = ?",
                (OPEN, stamp),
            ).fetchone()[0]
            due_soon = connection.execute(
                "SELECT COUNT(*) FROM tasks WHERE status = ? AND due_on IS NOT NULL AND due_on >= ? AND due_on <= ?",
                (OPEN, stamp, week_end),
            ).fetchone()[0]
            missing_next = categories - with_next
        return {
            "categories": categories,
            "open_tasks": open_tasks,
            "with_next_step": with_next,
            "missing_next_step": missing_next,
            "overdue": overdue,
            "due_today": due_today,
            "due_this_week": due_soon,
        }

    def due_soon(self, days: int = 7, reference: Optional[dt.date] = None) -> List[Task]:
        ref = reference or today()
        end = ref + dt.timedelta(days=days)
        with self._connect() as connection:
            rows = connection.execute(
                _TASK_SELECT
                + """
                 WHERE t.status = ?
                   AND t.due_on IS NOT NULL
                   AND t.due_on <= ?
                 ORDER BY t.due_on, c.sort_order, t.position, t.id
                """,
                (OPEN, format_date(end)),
            ).fetchall()
        return [_task_from_row(row) for row in rows]


_TASK_SELECT = """
    SELECT t.id, t.category_id, c.name AS category, t.title, t.due_on, t.status,
           t.position, t.created_at, t.updated_at, t.completed_at
      FROM tasks t
      JOIN categories c ON c.id = t.category_id
"""

_COMMENT_SELECT = """
    SELECT n.id, n.category_id, c.name AS category, n.task_id, t.title AS task_title,
           n.body, n.comment_on, n.created_at
      FROM comments n
      JOIN categories c ON c.id = n.category_id
      LEFT JOIN tasks t ON t.id = n.task_id
"""


def _timestamp() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _clean_name(name: str) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise ParseError("Category name is required")
    if len(cleaned) > 80:
        raise ParseError("Category name is too long")
    return cleaned


def _clean_title(title: str) -> str:
    cleaned = " ".join((title or "").split())
    if not cleaned:
        raise ParseError("Task title is required")
    if len(cleaned) > 240:
        raise ParseError("Task title is too long")
    return cleaned


def _category_from_row(row: sqlite3.Row) -> Category:
    return Category(
        id=row["id"],
        name=row["name"],
        sort_order=row["sort_order"],
        created_at=row["created_at"],
    )


def _task_from_row(row: sqlite3.Row) -> Task:
    due = parse_optional_date(row["due_on"]) if row["due_on"] else None
    return Task(
        id=row["id"],
        category_id=row["category_id"],
        category=row["category"],
        title=row["title"],
        due_on=due,
        status=row["status"],
        position=row["position"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )


def _comment_from_row(row: sqlite3.Row) -> Comment:
    return Comment(
        id=row["id"],
        category_id=row["category_id"],
        category=row["category"],
        task_id=row["task_id"],
        task_title=row["task_title"],
        body=row["body"],
        comment_on=parse_date(row["comment_on"]),
        created_at=row["created_at"],
    )
