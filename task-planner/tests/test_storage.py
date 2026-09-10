import datetime as dt
import tempfile
import unittest
from pathlib import Path

from task_planner.parsing import ParseError
from task_planner.storage import Database, StorageError


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.db = Database(self.root / "tasks.db")

    def tearDown(self):
        self._directory.cleanup()


class CategoryTests(DatabaseTestCase):
    def test_default_categories_exist(self):
        names = [category.name for category in self.db.categories()]
        self.assertIn("Family", names)
        self.assertIn("Career", names)

    def test_add_and_rename_category(self):
        created = self.db.add_category("School")
        self.assertEqual(created.name, "School")
        renamed = self.db.rename_category("School", "Education")
        self.assertEqual(renamed.name, "Education")
        self.assertIsNone(self.db.get_category("School"))

    def test_duplicate_category_is_rejected(self):
        with self.assertRaises(StorageError):
            self.db.add_category("Family")

    def test_delete_category_with_open_tasks_requires_move(self):
        self.db.add_task("Call admissions", "Family")
        with self.assertRaises(StorageError):
            self.db.delete_category("Family")
        moved = self.db.delete_category("Family", move_to="Admin")
        self.assertEqual(moved, 1)
        self.assertEqual(self.db.next_step("Admin").title, "Call admissions")


class TaskQueueTests(DatabaseTestCase):
    def test_first_task_becomes_next_step(self):
        first = self.db.add_task("Book school tour", "Family", due_on="2026-09-12")
        second = self.db.add_task("Submit form", "Family")
        nxt = self.db.next_step("Family")
        self.assertEqual(nxt.id, first.id)
        self.assertEqual(nxt.title, "Book school tour")
        board = {item.category.name: item for item in self.db.board()}
        self.assertEqual(board["Family"].upcoming[0].id, second.id)

    def test_as_next_jumps_the_queue(self):
        self.db.add_task("Later work", "Career")
        urgent = self.db.add_task("Send the follow-up today", "Career", as_next=True)
        self.assertEqual(self.db.next_step("Career").id, urgent.id)

    def test_completing_promotes_the_following_step(self):
        first = self.db.add_task("Step one", "Admin")
        second = self.db.add_task("Step two", "Admin")
        self.db.complete_task(first.id)
        self.assertEqual(self.db.next_step("Admin").id, second.id)
        self.assertEqual(self.db.get_task(first.id).status, "done")

    def test_blank_title_is_rejected(self):
        with self.assertRaises(ParseError):
            self.db.add_task("   ", "Family")

    def test_unknown_category_is_created(self):
        task = self.db.add_task("Buy rice", "Groceries")
        self.assertEqual(task.category, "Groceries")
        self.assertIsNotNone(self.db.get_category("Groceries"))

    def test_update_and_clear_due_date(self):
        task = self.db.add_task("Pay rates", "Finance", due_on="2026-09-20")
        updated = self.db.update_task(task.id, title="Pay council rates", due_on="2026-09-22")
        self.assertEqual(updated.title, "Pay council rates")
        self.assertEqual(updated.due_on, dt.date(2026, 9, 22))
        cleared = self.db.update_task(task.id, clear_due=True)
        self.assertIsNone(cleared.due_on)

    def test_reorder(self):
        first = self.db.add_task("A", "Home")
        second = self.db.add_task("B", "Home")
        self.db.move_task(second.id, "up")
        self.assertEqual(self.db.next_step("Home").id, second.id)
        self.db.move_task(second.id, "up")
        self.assertEqual(self.db.next_step("Home").id, second.id)

    def test_delete_task_promotes_queue(self):
        first = self.db.add_task("A", "Health")
        second = self.db.add_task("B", "Health")
        self.assertTrue(self.db.delete_task(first.id))
        self.assertEqual(self.db.next_step("Health").id, second.id)
        self.assertEqual(self.db.next_step("Health").position, 0)

    def test_reopen_as_next(self):
        task = self.db.add_task("Old step", "Personal")
        later = self.db.add_task("Newer step", "Personal")
        self.db.complete_task(task.id)
        self.assertEqual(self.db.next_step("Personal").id, later.id)
        self.db.reopen_task(task.id, as_next=True)
        self.assertEqual(self.db.next_step("Personal").id, task.id)

    def test_overdue_flag(self):
        task = self.db.add_task("Overdue call", "Admin", due_on="2020-01-01")
        self.assertTrue(task.is_overdue(dt.date(2026, 9, 10)))
        today_task = self.db.add_task("Do today", "Admin", due_on="2026-09-10")
        self.assertTrue(today_task.is_due_today(dt.date(2026, 9, 10)))

    def test_missing_task_errors(self):
        with self.assertRaises(StorageError):
            self.db.complete_task(999)
        self.assertFalse(self.db.delete_task(999))


class CommentTests(DatabaseTestCase):
    def test_comment_on_task_and_category(self):
        task = self.db.add_task("Book school tour", "Family")
        on_task = self.db.add_comment("left a voicemail", task_id=task.id, comment_on="2026-09-10")
        on_cat = self.db.add_comment("waiting on paperwork", category="Family", comment_on="2026-09-09")
        self.assertEqual(on_task.task_id, task.id)
        self.assertEqual(on_task.comment_on, dt.date(2026, 9, 10))
        comments = self.db.list_comments(category="Family")
        self.assertEqual([c.id for c in comments], [on_task.id, on_cat.id])
        board = {item.category.name: item for item in self.db.board()}
        self.assertEqual(board["Family"].latest_comment.id, on_task.id)

    def test_blank_comment_rejected(self):
        with self.assertRaises(ParseError):
            self.db.add_comment("  ", category="Family")

    def test_comment_requires_a_place(self):
        with self.assertRaises(ParseError):
            self.db.add_comment("hello")

    def test_delete_comment(self):
        comment = self.db.add_comment("note", category="Finance")
        self.assertTrue(self.db.delete_comment(comment.id))
        self.assertFalse(self.db.delete_comment(comment.id))


class BoardStatsTests(DatabaseTestCase):
    def test_stats_and_due_soon(self):
        self.db.add_task("Overdue", "Admin", due_on="2020-01-01")
        self.db.add_task("Soon", "Finance", due_on=dt.date.today())
        self.db.add_task("No date", "Home")
        stats = self.db.stats()
        self.assertEqual(stats["open_tasks"], 3)
        self.assertEqual(stats["with_next_step"], 3)
        self.assertGreaterEqual(stats["missing_next_step"], 1)
        self.assertEqual(stats["overdue"], 1)
        self.assertEqual(stats["due_today"], 1)
        due = self.db.due_soon(days=7)
        titles = [task.title for task in due]
        self.assertIn("Overdue", titles)
        self.assertIn("Soon", titles)
        self.assertNotIn("No date", titles)

    def test_reopening_keeps_data(self):
        self.db.add_task("Keep me", "Career")
        reopened = Database(self.root / "tasks.db")
        self.assertEqual(reopened.next_step("Career").title, "Keep me")
