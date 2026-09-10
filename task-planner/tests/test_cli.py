import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from task_planner import cli
from task_planner.storage import Database


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._directory.name) / "tasks.db")

    def tearDown(self):
        self._directory.cleanup()

    def run_cli(self, *argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(["--db", self.db_path, *argv])
        return code, stdout.getvalue(), stderr.getvalue()


class BoardCommandTests(CliTestCase):
    def test_default_command_is_the_board(self):
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("Next step in each category", out)
        self.assertIn("Family", out)

    def test_add_done_and_comment(self):
        code, out, err = self.run_cli("add", "Book school tour", "-c", "Family", "-d", "2026-09-12")
        self.assertEqual(code, 0, err)
        self.assertIn("This is now the next step for Family", out)

        code, out, err = self.run_cli("add", "Submit form", "-c", "fam")
        self.assertEqual(code, 0, err)
        self.assertIn("Next step for Family is still", out)

        code, out, err = self.run_cli("comment", "left a voicemail", "-t", "1", "-d", "2026-09-10")
        self.assertEqual(code, 0, err)
        self.assertIn("2026-09-10", out)

        code, out, _ = self.run_cli("board")
        self.assertIn("Book school tour", out)
        self.assertIn("Submit form", out)
        self.assertIn("left a voicemail", out)

        code, out, _ = self.run_cli("done", "1")
        self.assertEqual(code, 0)
        self.assertIn("Next for Family: #2", out)

        code, out, _ = self.run_cli("board", "--json")
        payload = json.loads(out)
        family = next(item for item in payload["categories"] if item["name"] == "Family")
        self.assertEqual(family["next_step"]["title"], "Submit form")

    def test_unknown_category_abbreviation_is_created_on_add(self):
        code, out, err = self.run_cli("add", "Buy rice", "-c", "Groceries")
        self.assertEqual(code, 0, err)
        self.assertIn("Groceries", out)

    def test_comment_without_target_fails(self):
        code, _, err = self.run_cli("comment", "hello")
        self.assertEqual(code, 2)
        self.assertIn("category or --task", err)

    def test_done_missing_task(self):
        code, _, err = self.run_cli("done", "99")
        self.assertEqual(code, 2)
        self.assertIn("No task with id 99", err)

    def test_categories_add_and_list(self):
        code, out, err = self.run_cli("categories", "add", "School")
        self.assertEqual(code, 0, err)
        code, out, _ = self.run_cli("categories")
        self.assertIn("School", out)
        self.assertIn("NEXT STEP", out)

    def test_config_mentions_port(self):
        code, out, _ = self.run_cli("config")
        self.assertEqual(code, 0)
        self.assertIn("8766", out)
        self.assertIn(self.db_path, out)

    def test_list_and_edit(self):
        self.run_cli("add", "Pay rates", "-c", "Finance", "-d", "2026-09-20")
        code, out, _ = self.run_cli("list", "-c", "Finance")
        self.assertEqual(code, 0)
        self.assertIn("Pay rates", out)
        code, out, err = self.run_cli("edit", "1", "--due", "2026-09-22")
        self.assertEqual(code, 0, err)
        self.assertIn("2026-09-22", out)


class ResolveCategoryTests(unittest.TestCase):
    def test_prefix_match(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "tasks.db")
            self.assertEqual(cli._resolve_category(database, "fam"), "Family")
            self.assertEqual(cli._resolve_category(database, "CAREER"), "Career")
