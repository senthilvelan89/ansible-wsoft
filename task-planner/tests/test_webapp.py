import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from task_planner.storage import Database
from task_planner.webapp import GUARD_HEADER, make_server


class WebAppTestCase(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.db = Database(self.root / "tasks.db")
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
        html = body.decode("utf-8")
        self.assertIn("Task Planner", html)
        self.assertIn("Next step in each category", html)
        self.assertLess(html.index("Next step in each category"), html.index("Add a step"))
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
            "/api/tasks",
            "POST",
            {"title": "Book tour", "category": "Family"},
            guard=False,
        )
        self.assertEqual(status, 403)
        self.assertIn(GUARD_HEADER, payload["error"])
        self.assertIsNone(self.db.next_step("Family"))

    def test_non_local_host_header_is_rejected(self):
        status, payload = self.json_request("/api/state", headers={"Host": "evil.example.com"})
        self.assertEqual(status, 403)
        self.assertIn("only answers requests from this machine", payload["error"])


class ApiTests(WebAppTestCase):
    def test_create_complete_comment_and_state(self):
        status, created = self.json_request(
            "/api/tasks",
            "POST",
            {"title": "Book school tour", "category": "Family", "due_on": "2026-09-12"},
        )
        self.assertEqual(status, 201)
        task_id = created["task"]["id"]

        status, _ = self.json_request(
            "/api/tasks",
            "POST",
            {"title": "Submit form", "category": "Family"},
        )
        self.assertEqual(status, 201)

        status, comment = self.json_request(
            "/api/comments",
            "POST",
            {"body": "left a voicemail", "task_id": task_id, "date": "2026-09-10"},
        )
        self.assertEqual(status, 201)
        self.assertEqual(comment["comment"]["comment_on"], "2026-09-10")

        status, state = self.json_request("/api/state")
        self.assertEqual(status, 200)
        family = next(item for item in state["categories"] if item["name"] == "Family")
        self.assertEqual(family["next_step"]["title"], "Book school tour")
        self.assertEqual(family["upcoming"][0]["title"], "Submit form")
        self.assertEqual(family["latest_comment"]["body"], "left a voicemail")

        status, done = self.json_request("/api/tasks/%d/done" % task_id, "POST", {})
        self.assertEqual(status, 200)
        self.assertEqual(done["next_step"]["title"], "Submit form")

        status, state = self.json_request("/api/state?category=Family")
        self.assertEqual(state["selected"], "Family")
        statuses = {item["title"]: item["status"] for item in state["detail"]["tasks"]}
        self.assertEqual(statuses["Book school tour"], "done")
        self.assertEqual(statuses["Submit form"], "open")
        self.assertEqual(state["detail"]["tasks"][0]["title"], "Submit form")

    def test_blank_title_returns_400(self):
        status, payload = self.json_request("/api/tasks", "POST", {"title": "  ", "category": "Family"})
        self.assertEqual(status, 400)
        self.assertIn("title", payload["error"].lower())

    def test_delete_missing_task_returns_404(self):
        status, _ = self.json_request("/api/tasks/999", "DELETE")
        self.assertEqual(status, 404)

    def test_categories_endpoint(self):
        status, payload = self.json_request("/api/categories", "POST", {"name": "School"})
        self.assertEqual(status, 201)
        names = [item["name"] for item in payload["categories"]]
        self.assertIn("School", names)

    def test_insert_as_next(self):
        self.json_request("/api/tasks", "POST", {"title": "Later", "category": "Career"})
        status, created = self.json_request(
            "/api/tasks",
            "POST",
            {"title": "Do this first", "category": "Career", "as_next": True},
        )
        self.assertEqual(status, 201)
        status, state = self.json_request("/api/state")
        career = next(item for item in state["categories"] if item["name"] == "Career")
        self.assertEqual(career["next_step"]["title"], "Do this first")
