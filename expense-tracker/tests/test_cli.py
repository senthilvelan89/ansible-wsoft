import contextlib
import datetime as dt
import io
import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from expense_tracker.cli import main
from expense_tracker.storage import Database


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.db_path = self.root / "expenses.db"

    def tearDown(self):
        self._directory.cleanup()

    def run_cli(self, *args, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        arguments = ["--db", str(self.db_path), *args]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            if stdin is not None:
                with unittest.mock.patch("sys.stdin", io.StringIO(stdin)):
                    code = main(arguments)
            else:
                code = main(arguments)
        return code, out.getvalue(), err.getvalue()

    @property
    def db(self):
        return Database(self.db_path)


class AddCommandTests(CliTestCase):
    def test_add_reports_the_entry_and_day_total(self):
        code, out, _ = self.run_cli("add", "Coffee", "4.50", "Dining", "-d", "2026-03-01")
        self.assertEqual(code, 0)
        self.assertIn("Added #1", out)
        self.assertIn("$4.50", out)
        self.assertIn("Total for 2026-03-01", out)
        self.assertEqual(self.db.totals().total_cents, 450)

    def test_category_defaults_to_other(self):
        self.run_cli("add", "Something", "5")
        self.assertEqual(self.db.list_expenses()[0].category, "Other")

    def test_category_prefix_is_expanded(self):
        self.run_cli("add", "Coffee", "4.50", "din", "-d", "2026-03-01")
        self.assertEqual(self.db.list_expenses()[0].category, "Dining")

    def test_note_is_stored(self):
        self.run_cli("add", "Coffee", "4.50", "Dining", "-n", "with Sam")
        self.assertEqual(self.db.list_expenses()[0].note, "with Sam")

    def test_bad_amount_exits_with_error(self):
        code, _, err = self.run_cli("add", "Coffee", "not-money", "Dining")
        self.assertEqual(code, 2)
        self.assertIn("Error:", err)

    def test_bad_date_exits_with_error(self):
        code, _, err = self.run_cli("add", "Coffee", "4.50", "Dining", "-d", "31-31-31")
        self.assertEqual(code, 2)
        self.assertIn("Error:", err)


class ListAndSummaryTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.run_cli("add", "Groceries run", "80", "Groceries", "-d", "2026-03-01")
        self.run_cli("add", "Coffee", "4.50", "Dining", "-d", "2026-03-01")
        self.run_cli("add", "Train", "12.30", "Transport", "-d", "2026-03-02")

    def test_list_shows_all_entries(self):
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("Coffee", out)
        self.assertIn("3 expense(s)", out)

    def test_list_json(self):
        _, out, _ = self.run_cli("list", "--json")
        payload = json.loads(out)
        self.assertEqual(len(payload), 3)
        self.assertEqual(payload[0]["date"], "2026-03-02")

    def test_list_filters_by_category(self):
        _, out, _ = self.run_cli("list", "-c", "Dining", "--json")
        payload = json.loads(out)
        self.assertEqual([row["item"] for row in payload], ["Coffee"])

    def test_list_filters_by_month(self):
        _, out, _ = self.run_cli("list", "-m", "2026-03", "--json")
        self.assertEqual(len(json.loads(out)), 3)
        _, out, _ = self.run_cli("list", "-m", "2026-02", "--json")
        self.assertEqual(json.loads(out), [])

    def test_summary_by_category(self):
        _, out, _ = self.run_cli("summary", "--json")
        payload = json.loads(out)
        self.assertEqual(payload["group_by"], "category")
        self.assertEqual(payload["total_cents"], 9680)
        self.assertEqual(payload["buckets"][0]["key"], "Groceries")
        self.assertEqual(payload["buckets"][0]["total_display"], "$80.00")

    def test_summary_by_day(self):
        _, out, _ = self.run_cli("summary", "--by", "day", "--json")
        payload = json.loads(out)
        self.assertEqual([bucket["key"] for bucket in payload["buckets"]], ["2026-03-01", "2026-03-02"])

    def test_summary_table_has_bars_and_total(self):
        _, out, _ = self.run_cli("summary")
        self.assertIn("Spend by category", out)
        self.assertIn("TOTAL: $96.80", out)
        self.assertIn("\u2588", out)

    def test_empty_range_is_reported_clearly(self):
        _, out, _ = self.run_cli("list", "-m", "2020-01")
        self.assertIn("No expenses recorded", out)


class EditDeleteTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.run_cli("add", "Coffee", "4.50", "Dining", "-d", "2026-03-01")

    def test_edit_amount_and_category(self):
        code, out, _ = self.run_cli("edit", "1", "-a", "6.25", "-c", "Groceries")
        self.assertEqual(code, 0)
        self.assertIn("Updated #1", out)
        expense = self.db.get_expense(1)
        self.assertEqual(expense.amount_cents, 625)
        self.assertEqual(expense.category, "Groceries")

    def test_delete_with_force(self):
        code, out, _ = self.run_cli("delete", "1", "--force")
        self.assertEqual(code, 0)
        self.assertIn("Deleted #1", out)
        self.assertEqual(self.db.totals().count, 0)

    def test_delete_missing_id(self):
        code, _, err = self.run_cli("delete", "42", "--force")
        self.assertEqual(code, 1)
        self.assertIn("No expense with id 42", err)


class CategoryCommandTests(CliTestCase):
    def test_list_shows_defaults(self):
        _, out, _ = self.run_cli("categories")
        self.assertIn("Groceries", out)
        self.assertIn("Transport", out)

    def test_add_and_rename(self):
        self.run_cli("categories", "add", "Pets")
        self.run_cli("add", "Cat food", "12", "Pets")
        code, out, _ = self.run_cli("categories", "rename", "Pets", "Animals")
        self.assertEqual(code, 0)
        self.assertIn("1 expense(s) updated", out)
        self.assertEqual(self.db.list_expenses()[0].category, "Animals")

    def test_delete_requires_move_target_when_used(self):
        self.run_cli("add", "Coffee", "4.50", "Dining")
        code, _, err = self.run_cli("categories", "delete", "Dining")
        self.assertEqual(code, 2)
        self.assertIn("still has 1 expense", err)

        code, out, _ = self.run_cli("categories", "delete", "Dining", "--move-to", "Other")
        self.assertEqual(code, 0)
        self.assertEqual(self.db.list_expenses()[0].category, "Other")


class ImportExportCommandTests(CliTestCase):
    def test_export_and_import_csv(self):
        self.run_cli("add", "Coffee", "4.50", "Dining", "-d", "2026-03-01")
        target = self.root / "out.csv"
        code, out, _ = self.run_cli("export", "-o", str(target))
        self.assertEqual(code, 0)
        self.assertIn("Wrote 1 expense(s)", out)
        self.assertIn("Coffee", target.read_text(encoding="utf-8"))

        self.db_path = self.root / "second.db"
        code, out, _ = self.run_cli("import", str(target))
        self.assertEqual(code, 0)
        self.assertEqual(self.db.totals().total_cents, 450)

    def test_export_json_to_stdout(self):
        self.run_cli("add", "Coffee", "4.50", "Dining", "-d", "2026-03-01")
        _, out, _ = self.run_cli("export", "--format", "json")
        payload = json.loads(out)
        self.assertEqual(payload[0]["item"], "Coffee")

    def test_import_missing_file(self):
        code, _, err = self.run_cli("import", str(self.root / "nope.csv"))
        self.assertEqual(code, 2)
        self.assertIn("No such file", err)


class RetentionCommandTests(CliTestCase):
    def test_prune_archives_old_entries(self):
        old_date = dt.date.today() - dt.timedelta(days=800)
        self.run_cli("add", "Ancient", "10", "Other", "-d", old_date.isoformat(), "--no-prune")
        self.run_cli("add", "Recent", "20", "Other", "--no-prune")

        code, out, _ = self.run_cli("prune", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("would be archived", out)
        self.assertEqual(self.db.totals().count, 2)

        code, out, _ = self.run_cli("prune")
        self.assertEqual(code, 0)
        self.assertIn("Archived 1 expense(s)", out)
        self.assertEqual(self.db.totals().count, 1)
        self.assertTrue(self.db.archive_path().exists())

    def test_auto_prune_runs_before_other_commands(self):
        old_date = dt.date.today() - dt.timedelta(days=800)
        self.run_cli("add", "Ancient", "10", "Other", "-d", old_date.isoformat(), "--no-prune")
        self.assertEqual(self.db.totals().count, 1)

        _, _, err = self.run_cli("list")
        self.assertIn("Archived 1 expense(s)", err)
        self.assertEqual(self.db.totals().count, 0)

    def test_no_prune_flag_keeps_old_entries(self):
        old_date = dt.date.today() - dt.timedelta(days=800)
        self.run_cli("add", "Ancient", "10", "Other", "-d", old_date.isoformat(), "--no-prune")
        self.run_cli("list", "--no-prune")
        self.assertEqual(self.db.totals().count, 1)


class ConfigCommandTests(CliTestCase):
    def test_shows_settings(self):
        _, out, _ = self.run_cli("config")
        self.assertIn("retention", out)
        self.assertIn("12 months", out)
        self.assertIn(str(self.db_path), out)

    def test_changes_currency_and_retention(self):
        code, out, _ = self.run_cli("config", "--currency", "\u00a3", "--retention-months", "6")
        self.assertEqual(code, 0)
        self.assertIn("Settings updated", out)
        self.assertEqual(self.db.currency_symbol, "\u00a3")
        self.assertEqual(self.db.retention_months, 6)

        self.run_cli("add", "Tea", "3", "Dining")
        _, out, _ = self.run_cli("summary")
        self.assertIn("\u00a33.00", out)


class NightCommandTests(CliTestCase):
    def test_interactive_session_records_entries(self):
        script = [
            "Coffee", "4.50", "Dining", "",
            "Groceries", "62.10", "Groceries", "weekly shop",
            "",
        ]
        answers = iter(script)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with unittest.mock.patch("builtins.input", lambda *_: next(answers)):
                code = main(["--db", str(self.db_path), "night", "-d", "2026-03-01"])

        self.assertEqual(code, 0)
        self.assertIn("Recorded 2 expense(s)", out.getvalue())
        self.assertEqual(self.db.totals().total_cents, 6660)
        self.assertEqual(self.db.list_expenses(category="Groceries")[0].note, "weekly shop")

    def test_bad_amount_is_reported_without_stopping(self):
        answers = iter(["Coffee", "abc", "Dining", "", "Tea", "3", "Dining", "", ""])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with unittest.mock.patch("builtins.input", lambda *_: next(answers)):
                code = main(["--db", str(self.db_path), "night"])

        self.assertEqual(code, 0)
        self.assertIn("Not saved", out.getvalue())
        self.assertEqual(self.db.totals().count, 1)

    def test_empty_session(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with unittest.mock.patch("builtins.input", lambda *_: ""):
                code = main(["--db", str(self.db_path), "night"])
        self.assertEqual(code, 0)
        self.assertIn("Nothing recorded", out.getvalue())


class ParserTests(CliTestCase):
    def test_no_command_prints_help(self):
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("usage:", out)


if __name__ == "__main__":
    unittest.main()
