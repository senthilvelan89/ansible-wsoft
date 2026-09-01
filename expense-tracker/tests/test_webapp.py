import datetime as dt
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from expense_tracker.storage import Database
from expense_tracker.webapp import GUARD_HEADER, make_server


class WebAppTestCase(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.db = Database(self.root / "expenses.db")
        self.server = make_server(self.db, host="127.0.0.1", port=0)
        self.base = "http://127.0.0.1:%d" % self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self._directory.cleanup()

    def request(self, path, method="GET", payload=None, guard=True, headers=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if guard:
            request.add_header(GUARD_HEADER, "1")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read()
                return response.status, body, response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers

    def json_request(self, path, method="GET", payload=None, **kwargs):
        status, body, _ = self.request(path, method, payload, **kwargs)
        return status, json.loads(body.decode("utf-8")) if body else {}


class PageTests(WebAppTestCase):
    def test_serves_the_page_and_assets(self):
        status, body, headers = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("Expense Tracker", body.decode("utf-8"))
        self.assertIn("text/html", headers["Content-Type"])

        for path, expected in [("/app.js", "javascript"), ("/app.css", "text/css")]:
            status, _, headers = self.request(path)
            self.assertEqual(status, 200)
            self.assertIn(expected, headers["Content-Type"])

    def test_unknown_path_is_404(self):
        status, _ = self.json_request("/nope")
        self.assertEqual(status, 404)


class SecurityTests(WebAppTestCase):
    def test_writes_require_the_guard_header(self):
        status, payload = self.json_request(
            "/api/expenses",
            "POST",
            {"item": "Coffee", "amount": "4.50", "category": "Dining"},
            guard=False,
        )
        self.assertEqual(status, 403)
        self.assertIn(GUARD_HEADER, payload["error"])
        self.assertEqual(self.db.totals().count, 0)

    def test_non_local_host_header_is_rejected(self):
        status, payload = self.json_request("/api/state", headers={"Host": "evil.example.com"})
        self.assertEqual(status, 403)
        self.assertIn("only answers requests from this machine", payload["error"])


class ApiTests(WebAppTestCase):
    def test_create_read_update_delete(self):
        status, created = self.json_request(
            "/api/expenses",
            "POST",
            {"date": "2026-03-01", "item": "Coffee", "amount": "4.50", "category": "Dining", "note": "oat"},
        )
        self.assertEqual(status, 201)
        expense_id = created["expense"]["id"]
        self.assertEqual(created["expense"]["amount_display"], "$4.50")

        status, listing = self.json_request("/api/expenses?month=2026-03")
        self.assertEqual(status, 200)
        self.assertEqual(len(listing["expenses"]), 1)
        self.assertEqual(listing["total_display"], "$4.50")

        status, updated = self.json_request(
            "/api/expenses/%d" % expense_id, "PATCH", {"amount": "6.00", "category": "Groceries"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["expense"]["amount_cents"], 600)
        self.assertEqual(updated["expense"]["category"], "Groceries")
        self.assertEqual(updated["expense"]["item"], "Coffee")

        status, _ = self.json_request("/api/expenses/%d" % expense_id, "DELETE")
        self.assertEqual(status, 200)
        self.assertEqual(self.db.totals().count, 0)

    def test_invalid_amount_returns_400(self):
        status, payload = self.json_request(
            "/api/expenses", "POST", {"item": "Coffee", "amount": "abc", "category": "Dining"}
        )
        self.assertEqual(status, 400)
        self.assertIn("amount", payload["error"].lower())

    def test_missing_item_returns_400(self):
        status, payload = self.json_request(
            "/api/expenses", "POST", {"item": "  ", "amount": "4.50", "category": "Dining"}
        )
        self.assertEqual(status, 400)
        self.assertIn("item description", payload["error"])

    def test_delete_missing_expense_returns_404(self):
        status, _ = self.json_request("/api/expenses/999", "DELETE")
        self.assertEqual(status, 404)

    def test_summary_endpoint(self):
        self.db.add_expense("Coffee", "4.50", "Dining", "2026-03-01")
        self.db.add_expense("Groceries", "80", "Groceries", "2026-03-02")

        status, payload = self.json_request("/api/summary?month=2026-03")
        self.assertEqual(status, 200)
        self.assertEqual(payload["total_cents"], 8450)
        self.assertEqual(payload["buckets"][0]["key"], "Groceries")

        status, payload = self.json_request("/api/summary?month=2026-03&by=day")
        self.assertEqual([bucket["key"] for bucket in payload["buckets"]], ["2026-03-01", "2026-03-02"])

    def test_categories_endpoint(self):
        status, payload = self.json_request("/api/categories")
        self.assertEqual(status, 200)
        self.assertIn("Dining", payload["categories"])

        status, payload = self.json_request("/api/categories", "POST", {"name": "Pets"})
        self.assertEqual(status, 201)
        self.assertIn("Pets", payload["categories"])

    def test_state_endpoint_summarises_day_month_and_window(self):
        today = dt.date.today()
        self.db.add_expense("Coffee", "4.50", "Dining", today)
        self.db.add_expense("Old thing", "10", "Other", today - dt.timedelta(days=400))

        status, payload = self.json_request("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(payload["retention_months"], 12)
        self.assertEqual(payload["day"]["total_display"], "$4.50")
        self.assertEqual(len(payload["day"]["expenses"]), 1)
        self.assertEqual(payload["month"]["total_cents"], 450)
        self.assertEqual(payload["window"]["total_cents"], 450, "entries older than 12 months are excluded")
        self.assertIn("Dining", payload["categories"])

    def test_state_endpoint_honours_requested_date(self):
        self.db.add_expense("Coffee", "4.50", "Dining", "2026-03-01")
        status, payload = self.json_request("/api/state?date=2026-03-01")
        self.assertEqual(status, 200)
        self.assertEqual(payload["day"]["date"], "2026-03-01")
        self.assertEqual(len(payload["day"]["expenses"]), 1)

    def test_bad_range_returns_400(self):
        status, payload = self.json_request("/api/expenses?from=2026-02-01&to=2026-01-01")
        self.assertEqual(status, 400)
        self.assertIn("after end date", payload["error"])

    def test_malformed_json_returns_400(self):
        request = urllib.request.Request(
            self.base + "/api/expenses", data=b"{not json", method="POST"
        )
        request.add_header(GUARD_HEADER, "1")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                self.fail("expected an error, got %d" % response.status)
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 400)


class ExportTests(WebAppTestCase):
    def test_csv_download(self):
        self.db.add_expense("Coffee", "4.50", "Dining", "2026-03-01")
        status, body, headers = self.request("/export.csv?month=2026-03")
        self.assertEqual(status, 200)
        self.assertIn("text/csv", headers["Content-Type"])
        self.assertIn("attachment", headers["Content-Disposition"])

        lines = body.decode("utf-8").strip().splitlines()
        self.assertEqual(lines[0], "id,date,item,category,amount,note,created_at")
        self.assertIn("Coffee", lines[1])


if __name__ == "__main__":
    unittest.main()
