"""A small local web interface for the next-step board.

The server binds to the loopback interface only. Mutating requests must carry
the ``X-Task-Planner`` header, which browsers will not attach to cross-site
form posts, so another page open in the same browser cannot quietly write to
the database.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from . import DEFAULT_WEB_PORT, __version__
from .parsing import ParseError, format_date, resolve_range, today
from .storage import Database, StorageError

STATIC_DIR = Path(__file__).resolve().parent / "static"
GUARD_HEADER = "X-Task-Planner"
MAX_BODY_BYTES = 1 << 20


class ApiError(Exception):
    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = status


def build_handler(database: Database):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TaskPlanner/%s" % __version__
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:  # pragma: no cover - noise
            if self.server.verbose:
                super().log_message(fmt, *args)

        def _host_is_local(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0].strip("[]").lower()
            return host in {"localhost", "127.0.0.1", "::1", ""}

        def _send(self, status: int, body: bytes, content_type: str, extra: Optional[Dict[str, str]] = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
            body = json.dumps(payload, default=str).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _read_json(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            if length > MAX_BODY_BYTES:
                raise ApiError("Request body is too large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise ApiError("Request body must be JSON") from None
            if not isinstance(payload, dict):
                raise ApiError("Request body must be a JSON object")
            return payload

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch("GET")

        def do_HEAD(self) -> None:  # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

        def do_PATCH(self) -> None:  # noqa: N802
            self._dispatch("PATCH")

        def do_DELETE(self) -> None:  # noqa: N802
            self._dispatch("DELETE")

        def _dispatch(self, method: str) -> None:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            query = parse_qs(parsed.query)

            try:
                if not self._host_is_local():
                    raise ApiError("This server only answers requests from this machine", HTTPStatus.FORBIDDEN)
                if method != "GET" and self.headers.get(GUARD_HEADER) is None:
                    raise ApiError("Missing %s header" % GUARD_HEADER, HTTPStatus.FORBIDDEN)

                if method == "GET" and path in {"/", "/index.html"}:
                    return self._serve_page()
                if method == "GET" and path == "/app.js":
                    return self._serve_static("app.js", "application/javascript; charset=utf-8")
                if method == "GET" and path == "/app.css":
                    return self._serve_static("app.css", "text/css; charset=utf-8")
                if method == "GET" and path == "/favicon.ico":
                    return self._send(HTTPStatus.NO_CONTENT, b"", "image/x-icon")
                if path.startswith("/api/"):
                    return self._api(method, path, query)
                raise ApiError("Not found", HTTPStatus.NOT_FOUND)
            except ApiError as error:
                self._send_json({"error": str(error)}, error.status)
            except (ParseError, StorageError) as error:
                self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            except Exception as error:  # pragma: no cover - defensive
                self._send_json({"error": "Unexpected error: %s" % error}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def _api(self, method: str, path: str, query: Dict[str, list]) -> None:
            if path == "/api/state" and method == "GET":
                return self._send_json(_state_payload(database, query))

            if path == "/api/tasks":
                if method == "GET":
                    tasks = database.list_tasks(
                        category=_first(query, "category"),
                        status=_first(query, "status"),
                        search=_first(query, "search"),
                        limit=_int(query, "limit"),
                    )
                    return self._send_json({"tasks": [task.to_dict() for task in tasks]})
                if method == "POST":
                    payload = self._read_json()
                    task = database.add_task(
                        title=payload.get("title", ""),
                        category=payload.get("category") or "",
                        due_on=payload.get("due_on") or payload.get("due") or None,
                        as_next=bool(payload.get("as_next")),
                    )
                    return self._send_json({"task": task.to_dict()}, HTTPStatus.CREATED)
                raise ApiError("Method not allowed", HTTPStatus.METHOD_NOT_ALLOWED)

            if path.startswith("/api/tasks/"):
                return self._task_item(method, path)

            if path == "/api/comments":
                if method == "GET":
                    start, end = resolve_range(
                        start=_first(query, "from"),
                        end=_first(query, "to"),
                        month=_first(query, "month"),
                        days=_int(query, "days"),
                    )
                    comments = database.list_comments(
                        category=_first(query, "category"),
                        task_id=_int(query, "task"),
                        start=start,
                        end=end,
                        limit=_int(query, "limit") or 80,
                    )
                    return self._send_json({"comments": [comment.to_dict() for comment in comments]})
                if method == "POST":
                    payload = self._read_json()
                    comment = database.add_comment(
                        payload.get("body") or payload.get("text") or "",
                        category=payload.get("category"),
                        task_id=payload.get("task_id") or payload.get("task"),
                        comment_on=payload.get("date") or payload.get("comment_on"),
                    )
                    return self._send_json({"comment": comment.to_dict()}, HTTPStatus.CREATED)
                raise ApiError("Method not allowed", HTTPStatus.METHOD_NOT_ALLOWED)

            if path.startswith("/api/comments/"):
                try:
                    comment_id = int(path.rsplit("/", 1)[1])
                except ValueError:
                    raise ApiError("Invalid comment id") from None
                if method == "DELETE":
                    if not database.delete_comment(comment_id):
                        raise ApiError("No comment with id %d" % comment_id, HTTPStatus.NOT_FOUND)
                    return self._send_json({"deleted": comment_id})
                raise ApiError("Method not allowed", HTTPStatus.METHOD_NOT_ALLOWED)

            if path == "/api/categories":
                if method == "GET":
                    return self._send_json({"categories": [c.to_dict() for c in database.categories()]})
                if method == "POST":
                    payload = self._read_json()
                    category = database.add_category(payload.get("name", ""))
                    return self._send_json(
                        {"category": category.to_dict(), "categories": [c.to_dict() for c in database.categories()]},
                        HTTPStatus.CREATED,
                    )
                raise ApiError("Method not allowed", HTTPStatus.METHOD_NOT_ALLOWED)

            raise ApiError("Not found", HTTPStatus.NOT_FOUND)

        def _task_item(self, method: str, path: str) -> None:
            parts = path.strip("/").split("/")
            # api / tasks / <id> [ / done | reopen | move ]
            if len(parts) < 3:
                raise ApiError("Invalid task path")
            try:
                task_id = int(parts[2])
            except ValueError:
                raise ApiError("Invalid task id") from None
            action = parts[3] if len(parts) > 3 else None

            if action == "done" and method == "POST":
                task = database.complete_task(task_id)
                promoted = database.next_step(task.category)
                return self._send_json(
                    {
                        "task": task.to_dict(),
                        "next_step": promoted.to_dict() if promoted else None,
                    }
                )
            if action == "reopen" and method == "POST":
                payload = self._read_json() if self.headers.get("Content-Length") else {}
                task = database.reopen_task(task_id, as_next=bool(payload.get("as_next")))
                return self._send_json({"task": task.to_dict()})
            if action == "move" and method == "POST":
                payload = self._read_json()
                task = database.move_task(task_id, payload.get("direction") or "down")
                return self._send_json({"task": task.to_dict()})
            if action is not None:
                raise ApiError("Not found", HTTPStatus.NOT_FOUND)

            if method == "GET":
                task = database.get_task(task_id)
                if task is None:
                    raise ApiError("No task with id %d" % task_id, HTTPStatus.NOT_FOUND)
                return self._send_json({"task": task.to_dict()})
            if method == "DELETE":
                if not database.delete_task(task_id):
                    raise ApiError("No task with id %d" % task_id, HTTPStatus.NOT_FOUND)
                return self._send_json({"deleted": task_id})
            if method == "PATCH":
                payload = self._read_json()
                task = database.update_task(
                    task_id,
                    title=payload.get("title"),
                    category=payload.get("category"),
                    due_on=payload.get("due_on") or payload.get("due"),
                    clear_due=bool(payload.get("clear_due")),
                )
                return self._send_json({"task": task.to_dict()})
            raise ApiError("Method not allowed", HTTPStatus.METHOD_NOT_ALLOWED)

        def _serve_page(self) -> None:
            html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
            self._send(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")

        def _serve_static(self, name: str, content_type: str) -> None:
            target = STATIC_DIR / name
            if not target.exists():
                raise ApiError("Not found", HTTPStatus.NOT_FOUND)
            self._send(HTTPStatus.OK, target.read_bytes(), content_type)

    return Handler


def _first(query: Dict[str, list], key: str) -> Optional[str]:
    values = query.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _int(query: Dict[str, list], key: str) -> Optional[int]:
    value = _first(query, key)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        raise ApiError("%s must be a number" % key) from None


def _state_payload(database: Database, query: Dict[str, list]) -> Dict[str, Any]:
    selected = _first(query, "category")
    boards = database.board()
    stats = database.stats()
    due = database.due_soon(days=7)
    comments = database.list_comments(limit=40)
    selected_board = None
    if selected:
        for board in boards:
            if board.category.name.lower() == selected.lower():
                selected_board = board
                break
    detail_tasks = []
    detail_comments = []
    if selected_board:
        detail_tasks = database.list_tasks(category=selected_board.category.name)
        detail_comments = database.list_comments(category=selected_board.category.name, limit=40)

    return {
        "version": __version__,
        "today": format_date(today()),
        "database_path": str(database.path),
        "port": DEFAULT_WEB_PORT,
        "stats": stats,
        "categories": [board.to_dict() for board in boards],
        "due_soon": [task.to_dict() for task in due],
        "recent_comments": [comment.to_dict() for comment in comments],
        "selected": selected_board.category.name if selected_board else None,
        "detail": {
            "tasks": [task.to_dict() for task in detail_tasks],
            "comments": [comment.to_dict() for comment in detail_comments],
        },
    }


def make_server(database: Database, host: str = "127.0.0.1", port: int = DEFAULT_WEB_PORT, verbose: bool = False) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), build_handler(database))
    server.daemon_threads = True
    server.verbose = verbose
    return server


def serve(
    database: Database,
    host: str = "127.0.0.1",
    port: int = DEFAULT_WEB_PORT,
    open_browser: bool = True,
    verbose: bool = False,
) -> int:
    try:
        server = make_server(database, host, port, verbose)
    except OSError as error:
        print("Could not start the server on %s:%d (%s)" % (host, port, error))
        print("Try a different port, for example: tasks web --port %d" % (port + 1))
        return 1

    url = "http://%s:%d/" % (host, server.server_port)
    print("Task planner is running at %s" % url)
    print("Expense tracker uses port 8765; this board uses %d so both can run together." % DEFAULT_WEB_PORT)
    print("Database: %s" % database.path)
    print("Press Ctrl+C to stop.", flush=True)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0
