"""A small local web interface for entering and reviewing expenses.

The server binds to the loopback interface only. Mutating requests must carry
the ``X-Expense-Tracker`` header, which browsers will not attach to
cross-site form posts, so another page open in the same browser cannot quietly
write to the database.
"""

from __future__ import annotations

import io
import json
import datetime as dt
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from . import __version__
from .parsing import (
    ParseError,
    add_months,
    format_amount,
    format_date,
    month_bounds,
    parse_date,
    resolve_range,
    today,
)
from .storage import Database, StorageError

STATIC_DIR = Path(__file__).resolve().parent / "static"
GUARD_HEADER = "X-Expense-Tracker"
MAX_BODY_BYTES = 1 << 20


class ApiError(Exception):
    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = status


def build_handler(database: Database):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ExpenseTracker/%s" % __version__
        protocol_version = "HTTP/1.1"

        # ------------------------------------------------------- plumbing

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

        # --------------------------------------------------------- routing

        def do_GET(self) -> None:  # noqa: N802 - required name
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

                if method == "GET" and (
                    path in {"/", "/index.html", "/orders"} or path.startswith("/orders/")
                ):
                    return self._serve_page()
                if method == "GET" and path == "/app.js":
                    return self._serve_static("app.js", "application/javascript; charset=utf-8")
                if method == "GET" and path == "/app.css":
                    return self._serve_static("app.css", "text/css; charset=utf-8")
                if method == "GET" and path == "/favicon.ico":
                    return self._send(HTTPStatus.NO_CONTENT, b"", "image/x-icon")
                if method == "GET" and path == "/export.csv":
                    return self._export_csv(query)
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
            symbol = database.currency_symbol

            if path == "/api/state" and method == "GET":
                return self._send_json(_state_payload(database, query))

            if path == "/api/expenses":
                if method == "GET":
                    start, end = _range_from_query(query)
                    expenses = database.list_expenses(
                        start=start,
                        end=end,
                        category=_first(query, "category"),
                        search=_first(query, "search"),
                        order_name=_first(query, "order"),
                        limit=_int(query, "limit"),
                    )
                    spend = sum(e.amount_cents for e in expenses if not e.is_income)
                    return self._send_json(
                        {
                            "expenses": [expense.to_dict(symbol) for expense in expenses],
                            "total_cents": spend,
                            "total_display": format_amount(spend, symbol),
                        }
                    )
                if method == "POST":
                    payload = self._read_json()
                    expense = database.add_expense(
                        item=payload.get("item", ""),
                        amount=payload.get("amount", ""),
                        category=payload.get("category") or "Other",
                        spent_on=payload.get("date") or None,
                        note=payload.get("note", ""),
                    )
                    return self._send_json({"expense": expense.to_dict(symbol)}, HTTPStatus.CREATED)
                raise ApiError("Method not allowed", HTTPStatus.METHOD_NOT_ALLOWED)

            if path.startswith("/api/expenses/"):
                try:
                    expense_id = int(path.rsplit("/", 1)[1])
                except ValueError:
                    raise ApiError("Invalid expense id") from None
                if method == "DELETE":
                    if not database.delete_expense(expense_id):
                        raise ApiError("No expense with id %d" % expense_id, HTTPStatus.NOT_FOUND)
                    return self._send_json({"deleted": expense_id})
                if method == "PATCH":
                    payload = self._read_json()
                    expense = database.update_expense(
                        expense_id,
                        item=payload.get("item"),
                        amount=payload.get("amount"),
                        category=payload.get("category"),
                        spent_on=payload.get("date"),
                        note=payload.get("note"),
                    )
                    return self._send_json({"expense": expense.to_dict(symbol)})
                raise ApiError("Method not allowed", HTTPStatus.METHOD_NOT_ALLOWED)

            if path == "/api/summary" and method == "GET":
                start, end = _range_from_query(query)
                group_by = _first(query, "by") or "category"
                buckets = database.summary(
                    group_by,
                    start=start,
                    end=end,
                    category=_first(query, "category"),
                    search=_first(query, "search"),
                    order_name=_first(query, "order"),
                    exclude_income=group_by == "category" and not _first(query, "category"),
                )
                return self._send_json(
                    {
                        "group_by": group_by,
                        "buckets": [bucket.to_dict(symbol) for bucket in buckets],
                        "total_cents": sum(bucket.total_cents for bucket in buckets),
                        "total_display": format_amount(
                            sum(bucket.total_cents for bucket in buckets), symbol
                        ),
                    }
                )

            if path == "/api/categories":
                if method == "GET":
                    return self._send_json({"categories": database.categories()})
                if method == "POST":
                    payload = self._read_json()
                    name = database.add_category(payload.get("name", ""))
                    return self._send_json(
                        {"category": name, "categories": database.categories()},
                        HTTPStatus.CREATED,
                    )
                raise ApiError("Method not allowed", HTTPStatus.METHOD_NOT_ALLOWED)

            if path == "/api/order-categories":
                if method == "GET":
                    return self._send_json({"categories": database.order_categories()})
                if method == "POST":
                    payload = self._read_json()
                    name = database.add_order_category(payload.get("name", ""))
                    return self._send_json(
                        {"category": name, "categories": database.order_categories()},
                        HTTPStatus.CREATED,
                    )
                raise ApiError("Method not allowed", HTTPStatus.METHOD_NOT_ALLOWED)

            if path == "/api/overhead":
                if method == "GET":
                    return self._send_json(database.overhead_snapshot(symbol))
                if method == "PATCH":
                    payload = self._read_json()
                    annual = payload.get("annual_overhead", payload.get("annual"))
                    monthly = payload.get(
                        "monthly_order_income", payload.get("expected_monthly_income")
                    )
                    if annual is None and monthly is None:
                        raise ApiError("Provide annual_overhead and/or monthly_order_income")
                    database.set_overhead_amounts(annual=annual, monthly=monthly)
                    return self._send_json(database.overhead_snapshot(symbol))
                raise ApiError("Method not allowed", HTTPStatus.METHOD_NOT_ALLOWED)

            if path == "/api/food-orders":
                if method == "GET":
                    start, end = _range_from_query(query)
                    orders = database.list_food_orders(
                        start=start, end=end, search=_first(query, "search")
                    )
                    return self._send_json(_order_list_payload(database, orders, symbol))
                if method == "POST":
                    payload = self._read_json()
                    order = database.create_food_order(
                        payload.get("name", ""),
                        order_date=payload.get("date") or None,
                        note=payload.get("note", ""),
                    )
                    return self._send_json({"order": order.to_dict(symbol)}, HTTPStatus.CREATED)
                raise ApiError("Method not allowed", HTTPStatus.METHOD_NOT_ALLOWED)

            if path.startswith("/api/food-orders/"):
                return self._food_order_api(method, path, symbol)

            if path == "/api/orders" and method == "GET":
                start, end = _range_from_query(query)
                orders = database.list_food_orders(start=start, end=end)
                return self._send_json(_order_list_payload(database, orders, symbol))

            raise ApiError("Not found", HTTPStatus.NOT_FOUND)

        def _food_order_api(self, method: str, path: str, symbol: str) -> None:
            parts = [part for part in path.split("/") if part]
            # api, food-orders, id, [entries, entry-id]
            try:
                order_id = int(parts[2])
            except (IndexError, ValueError):
                raise ApiError("Invalid food order id") from None

            if len(parts) == 3:
                if method == "GET":
                    order = database.get_food_order(order_id)
                    payload = order.to_dict(symbol)
                    payload["categories"] = database.order_categories()
                    payload["overhead"] = database.overhead_snapshot(symbol)
                    return self._send_json(payload)
                if method == "PATCH":
                    payload = self._read_json()
                    order = database.update_food_order(
                        order_id,
                        name=payload.get("name"),
                        order_date=payload.get("date"),
                        note=payload.get("note"),
                    )
                    return self._send_json({"order": order.to_dict(symbol)})
                if method == "DELETE":
                    if not database.delete_food_order(order_id):
                        raise ApiError("No food order with id %d" % order_id, HTTPStatus.NOT_FOUND)
                    return self._send_json({"deleted": order_id})
                raise ApiError("Method not allowed", HTTPStatus.METHOD_NOT_ALLOWED)

            if len(parts) >= 4 and parts[3] == "entries":
                if len(parts) == 4 and method == "POST":
                    payload = self._read_json()
                    entry = database.add_order_entry(
                        order_id,
                        kind=payload.get("kind") or "cost",
                        item=payload.get("item", ""),
                        amount=payload.get("amount", ""),
                        category=payload.get("category") or "",
                        hours=payload.get("hours") or 0,
                        spent_on=payload.get("date") or None,
                        note=payload.get("note", ""),
                    )
                    order = database.get_food_order(order_id)
                    return self._send_json(
                        {"entry": entry.to_dict(symbol), "order": order.to_dict(symbol)},
                        HTTPStatus.CREATED,
                    )
                if len(parts) == 5:
                    try:
                        entry_id = int(parts[4])
                    except ValueError:
                        raise ApiError("Invalid entry id") from None
                    if method == "DELETE":
                        if not database.delete_order_entry(entry_id):
                            raise ApiError("No order entry with id %d" % entry_id, HTTPStatus.NOT_FOUND)
                        return self._send_json({"deleted": entry_id})
                    if method == "PATCH":
                        payload = self._read_json()
                        entry = database.update_order_entry(
                            entry_id,
                            item=payload.get("item"),
                            amount=payload.get("amount"),
                            category=payload.get("category"),
                            hours=payload.get("hours"),
                            spent_on=payload.get("date"),
                            note=payload.get("note"),
                            kind=payload.get("kind"),
                        )
                        return self._send_json({"entry": entry.to_dict(symbol)})
                raise ApiError("Method not allowed", HTTPStatus.METHOD_NOT_ALLOWED)

            raise ApiError("Not found", HTTPStatus.NOT_FOUND)

        # ---------------------------------------------------------- static

        def _serve_page(self) -> None:
            html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
            self._send(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")

        def _serve_static(self, name: str, content_type: str) -> None:
            target = STATIC_DIR / name
            if not target.exists():
                raise ApiError("Not found", HTTPStatus.NOT_FOUND)
            self._send(HTTPStatus.OK, target.read_bytes(), content_type)

        def _export_csv(self, query: Dict[str, list]) -> None:
            start, end = _range_from_query(query)
            expenses = database.list_expenses(start=start, end=end, newest_first=False)
            buffer = io.StringIO()
            database.export_csv(buffer, expenses)
            body = buffer.getvalue().encode("utf-8")
            filename = "expenses-%s.csv" % format_date(today())
            self._send(
                HTTPStatus.OK,
                body,
                "text/csv; charset=utf-8",
                {"Content-Disposition": 'attachment; filename="%s"' % filename},
            )

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


def _range_from_query(query: Dict[str, list]) -> Tuple[Optional[dt.date], Optional[dt.date]]:
    return resolve_range(
        start=_first(query, "from"),
        end=_first(query, "to"),
        month=_first(query, "month"),
        year=_first(query, "year"),
        days=_int(query, "days"),
    )


def _order_list_payload(database: Database, orders, symbol: str) -> Dict[str, Any]:
    income = sum(order.income_cents for order in orders)
    cost = sum(order.expense_cents for order in orders)
    hours = sum(order.hours for order in orders)
    reserve = sum(order.overhead_reserve_cents for order in orders)
    after = income - cost - reserve
    return {
        "orders": [order.to_dict(symbol) for order in orders],
        "income_cents": income,
        "income_display": format_amount(income, symbol),
        "expense_cents": cost,
        "expense_display": format_amount(cost, symbol),
        "profit_cents": income - cost,
        "profit_display": format_amount(income - cost, symbol),
        "overhead_reserve_cents": reserve,
        "overhead_reserve_display": format_amount(reserve, symbol),
        "profit_after_reserve_cents": after,
        "profit_after_reserve_display": format_amount(after, symbol),
        "hours": hours,
        "overhead": database.overhead_snapshot(symbol),
    }


def _state_payload(database: Database, query: Dict[str, list]) -> Dict[str, Any]:
    symbol = database.currency_symbol
    reference = parse_date(_first(query, "date") or "today")
    month_start, month_end = month_bounds(reference.year, reference.month)
    window_start = add_months(today(), -database.retention_months)

    day_expenses = database.list_expenses(start=reference, end=reference)
    day_spend = database.totals(start=reference, end=reference, exclude_income=True)
    day_income = database.totals(start=reference, end=reference, category="Income")
    month_spend = database.totals(start=month_start, end=month_end, exclude_income=True)
    month_income = database.totals(start=month_start, end=month_end, category="Income")
    month_categories = database.summary(
        "category", start=month_start, end=month_end, exclude_income=True
    )
    monthly_trend = database.summary(
        "month", start=window_start, end=today(), exclude_income=True
    )
    window_spend = database.totals(start=window_start, end=today(), exclude_income=True)
    month_orders = database.order_profits(start=month_start, end=month_end)
    month_profit = sum(order.profit_cents for order in month_orders)
    span = database.date_span()

    return {
        "version": __version__,
        "currency": symbol,
        "today": format_date(today()),
        "date": format_date(reference),
        "categories": database.categories(),
        "order_names": database.order_names(),
        "retention_months": database.retention_months,
        "retention_cutoff": format_date(database.retention_cutoff()),
        "database_path": str(database.path),
        "day": {
            "date": format_date(reference),
            "expenses": [expense.to_dict(symbol) for expense in day_expenses],
            "total_cents": day_spend.total_cents,
            "total_display": format_amount(day_spend.total_cents, symbol),
            "income_cents": day_income.total_cents,
            "income_display": format_amount(day_income.total_cents, symbol),
        },
        "month": {
            "start": format_date(month_start),
            "end": format_date(month_end),
            "label": reference.strftime("%B %Y"),
            "total_cents": month_spend.total_cents,
            "total_display": format_amount(month_spend.total_cents, symbol),
            "income_cents": month_income.total_cents,
            "income_display": format_amount(month_income.total_cents, symbol),
            "profit_cents": month_profit,
            "profit_display": format_amount(month_profit, symbol),
            "categories": [bucket.to_dict(symbol) for bucket in month_categories],
            "orders": [order.to_dict(symbol) for order in month_orders],
        },
        "window": {
            "start": format_date(window_start),
            "end": format_date(today()),
            "total_cents": window_spend.total_cents,
            "total_display": format_amount(window_spend.total_cents, symbol),
            "months": [bucket.to_dict(symbol) for bucket in monthly_trend],
            "first_record": format_date(span[0]) if span else None,
            "last_record": format_date(span[1]) if span else None,
        },
    }


def make_server(database: Database, host: str = "127.0.0.1", port: int = 8765, verbose: bool = False) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), build_handler(database))
    server.daemon_threads = True
    server.verbose = verbose
    return server


def serve(
    database: Database,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    verbose: bool = False,
) -> int:
    try:
        server = make_server(database, host, port, verbose)
    except OSError as error:
        print("Could not start the server on %s:%d (%s)" % (host, port, error))
        print("Try a different port, for example: expenses web --port %d" % (port + 1))
        return 1

    url = "http://%s:%d/" % (host, server.server_port)
    print("Expense tracker is running at %s" % url)
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
