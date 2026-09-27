import csv
import datetime as dt
import io
import tempfile
import unittest
from pathlib import Path

from expense_tracker.parsing import ParseError
from expense_tracker.storage import Database, StorageError


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.db = Database(self.root / "expenses.db")

    def tearDown(self):
        self._directory.cleanup()


class BasicOperationTests(DatabaseTestCase):
    def test_add_and_read_back(self):
        expense = self.db.add_expense("Coffee", "4.50", "Dining", "2026-03-01", note="with Sam")
        self.assertEqual(expense.amount_cents, 450)
        self.assertEqual(expense.spent_on, dt.date(2026, 3, 1))

        stored = self.db.get_expense(expense.id)
        self.assertEqual(stored, expense)

    def test_item_is_required(self):
        with self.assertRaises(ParseError):
            self.db.add_expense("   ", "4.50", "Dining")

    def test_unknown_category_is_created(self):
        self.db.add_expense("Cat food", "12", "Pets", "2026-03-01")
        self.assertIn("Pets", self.db.categories())

    def test_category_matching_is_case_insensitive(self):
        self.db.add_expense("Lunch", "10", "dining", "2026-03-01")
        self.db.add_expense("Dinner", "20", "DINING", "2026-03-01")
        buckets = self.db.summary("category")
        self.assertEqual(len(buckets), 1)
        self.assertEqual(buckets[0].total_cents, 3000)

    def test_update_expense(self):
        expense = self.db.add_expense("Coffee", "4.50", "Dining", "2026-03-01")
        updated = self.db.update_expense(expense.id, amount="5.25", category="Groceries")
        self.assertEqual(updated.amount_cents, 525)
        self.assertEqual(updated.category, "Groceries")
        self.assertEqual(updated.item, "Coffee")

    def test_update_missing_expense(self):
        with self.assertRaises(StorageError):
            self.db.update_expense(999, amount="1")

    def test_delete_expense(self):
        expense = self.db.add_expense("Coffee", "4.50", "Dining", "2026-03-01")
        self.assertTrue(self.db.delete_expense(expense.id))
        self.assertFalse(self.db.delete_expense(expense.id))
        self.assertIsNone(self.db.get_expense(expense.id))

    def test_settings_round_trip(self):
        self.assertEqual(self.db.currency_symbol, "$")
        self.assertEqual(self.db.retention_months, 12)
        self.db.set_setting("currency_symbol", "\u00a3")
        self.db.set_setting("retention_months", "6")
        self.assertEqual(self.db.currency_symbol, "\u00a3")
        self.assertEqual(self.db.retention_months, 6)

    def test_reopening_keeps_data(self):
        self.db.add_expense("Coffee", "4.50", "Dining", "2026-03-01")
        reopened = Database(self.root / "expenses.db")
        self.assertEqual(reopened.totals().count, 1)


class QueryTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.db.add_expense("Groceries run", "80.00", "Groceries", "2026-03-01")
        self.db.add_expense("Coffee", "4.50", "Dining", "2026-03-01", note="oat milk")
        self.db.add_expense("Train ticket", "12.30", "Transport", "2026-03-02")
        self.db.add_expense("Old dinner", "50.00", "Dining", "2026-01-15")

    def test_range_filtering_is_inclusive(self):
        expenses = self.db.list_expenses(start=dt.date(2026, 3, 1), end=dt.date(2026, 3, 2))
        self.assertEqual(len(expenses), 3)

    def test_default_order_is_newest_first(self):
        expenses = self.db.list_expenses()
        self.assertEqual(expenses[0].item, "Train ticket")
        self.assertEqual(expenses[-1].item, "Old dinner")

    def test_oldest_first(self):
        expenses = self.db.list_expenses(newest_first=False)
        self.assertEqual(expenses[0].item, "Old dinner")

    def test_category_filter(self):
        expenses = self.db.list_expenses(category="Dining")
        self.assertEqual(len(expenses), 2)

    def test_search_matches_item_and_note(self):
        self.assertEqual(len(self.db.list_expenses(search="Coffee")), 1)
        self.assertEqual(len(self.db.list_expenses(search="oat")), 1)
        self.assertEqual(len(self.db.list_expenses(search="nothing")), 0)

    def test_limit(self):
        self.assertEqual(len(self.db.list_expenses(limit=2)), 2)

    def test_totals(self):
        bucket = self.db.totals()
        self.assertEqual(bucket.total_cents, 14680)
        self.assertEqual(bucket.count, 4)

    def test_summary_by_category_is_sorted_by_spend(self):
        buckets = self.db.summary("category")
        self.assertEqual([bucket.key for bucket in buckets], ["Groceries", "Dining", "Transport"])
        self.assertEqual(buckets[1].total_cents, 5450)

    def test_summary_by_month(self):
        buckets = self.db.summary("month")
        self.assertEqual([bucket.key for bucket in buckets], ["2026-01", "2026-03"])

    def test_summary_by_day(self):
        buckets = self.db.summary("day", start=dt.date(2026, 3, 1), end=dt.date(2026, 3, 31))
        self.assertEqual([bucket.key for bucket in buckets], ["2026-03-01", "2026-03-02"])
        self.assertEqual(buckets[0].total_cents, 8450)

    def test_summary_rejects_unknown_grouping(self):
        with self.assertRaises(StorageError):
            self.db.summary("colour")

    def test_date_span(self):
        self.assertEqual(self.db.date_span(), (dt.date(2026, 1, 15), dt.date(2026, 3, 2)))


class CategoryManagementTests(DatabaseTestCase):
    def test_rename_moves_expenses(self):
        self.db.add_expense("Coffee", "4.50", "Dining", "2026-03-01")
        moved = self.db.rename_category("Dining", "Eating out")
        self.assertEqual(moved, 1)
        self.assertIn("Eating out", self.db.categories())
        self.assertNotIn("Dining", self.db.categories())
        self.assertEqual(self.db.list_expenses()[0].category, "Eating out")

    def test_rename_unknown_category(self):
        with self.assertRaises(StorageError):
            self.db.rename_category("Nope", "Something")

    def test_delete_unused_category(self):
        self.db.add_category("Hobbies")
        self.db.delete_category("Hobbies")
        self.assertNotIn("Hobbies", self.db.categories())

    def test_delete_used_category_requires_target(self):
        self.db.add_expense("Coffee", "4.50", "Dining", "2026-03-01")
        with self.assertRaises(StorageError):
            self.db.delete_category("Dining")

        moved = self.db.delete_category("Dining", reassign_to="Other")
        self.assertEqual(moved, 1)
        self.assertEqual(self.db.list_expenses()[0].category, "Other")


class RetentionTests(DatabaseTestCase):
    def test_cutoff_is_twelve_months_back(self):
        self.assertEqual(self.db.retention_cutoff(dt.date(2026, 9, 1)), dt.date(2025, 9, 1))

    def test_prune_archives_and_deletes_old_rows(self):
        self.db.add_expense("Ancient", "10.00", "Other", "2024-01-05")
        self.db.add_expense("Just outside", "20.00", "Other", "2025-08-31")
        self.db.add_expense("Just inside", "30.00", "Other", "2025-09-01")
        self.db.add_expense("Recent", "40.00", "Other", "2026-08-20")

        result = self.db.prune(reference=dt.date(2026, 9, 1))
        self.assertEqual(result.count, 2)
        self.assertEqual(result.total_cents, 3000)

        remaining = {expense.item for expense in self.db.list_expenses()}
        self.assertEqual(remaining, {"Just inside", "Recent"})

        with result.archive_path.open(encoding="utf-8") as handle:
            archived = list(csv.DictReader(handle))
        self.assertEqual([row["item"] for row in archived], ["Ancient", "Just outside"])
        self.assertEqual(archived[0]["amount"], "10.00")

    def test_prune_dry_run_changes_nothing(self):
        self.db.add_expense("Ancient", "10.00", "Other", "2024-01-05")
        result = self.db.prune(reference=dt.date(2026, 9, 1), dry_run=True)
        self.assertEqual(result.count, 1)
        self.assertIsNone(result.archive_path)
        self.assertEqual(self.db.totals().count, 1)

    def test_prune_appends_to_existing_archive(self):
        self.db.add_expense("First", "10.00", "Other", "2024-01-05")
        self.db.prune(reference=dt.date(2026, 9, 1))
        self.db.add_expense("Second", "20.00", "Other", "2024-02-05")
        result = self.db.prune(reference=dt.date(2026, 9, 1))

        with result.archive_path.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([row["item"] for row in rows], ["First", "Second"])

    def test_prune_with_nothing_to_do(self):
        self.db.add_expense("Recent", "10.00", "Other", "2026-08-20")
        result = self.db.prune(reference=dt.date(2026, 9, 1))
        self.assertEqual(result.count, 0)
        self.assertEqual(self.db.totals().count, 1)

    def test_custom_retention_window(self):
        self.db.set_setting("retention_months", "3")
        self.assertEqual(self.db.retention_cutoff(dt.date(2026, 9, 1)), dt.date(2026, 6, 1))


class ImportExportTests(DatabaseTestCase):
    def test_export_then_import_round_trip(self):
        self.db.add_expense("Coffee", "4.50", "Dining", "2026-03-01", note="oat milk")
        self.db.add_expense("Train", "12.30", "Transport", "2026-03-02")

        buffer = io.StringIO()
        exported = self.db.export_csv(buffer)
        self.assertEqual(exported, 2)

        target = Database(self.root / "copy.db")
        buffer.seek(0)
        imported = target.import_csv(buffer)
        self.assertEqual(imported, 2)
        self.assertEqual(target.totals().total_cents, 1680)
        self.assertEqual(target.list_expenses(newest_first=False)[0].note, "oat milk")

    def test_import_requires_columns(self):
        with self.assertRaises(StorageError):
            self.db.import_csv(io.StringIO("date,item\n2026-03-01,Coffee\n"))

    def test_import_reports_bad_line(self):
        payload = "date,item,category,amount\n2026-03-01,Coffee,Dining,abc\n"
        with self.assertRaises(StorageError) as context:
            self.db.import_csv(io.StringIO(payload))
        self.assertIn("Line 2", str(context.exception))

    def test_import_skips_blank_lines(self):
        payload = "date,item,category,amount\n2026-03-01,Coffee,Dining,4.50\n,,,\n"
        self.assertEqual(self.db.import_csv(io.StringIO(payload)), 1)


if __name__ == "__main__":
    unittest.main()
