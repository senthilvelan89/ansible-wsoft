"""Command line interface for the expense tracker."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from . import __version__
from .parsing import (
    ParseError,
    describe_range,
    format_amount,
    format_date,
    parse_amount,
    parse_date,
    resolve_range,
    today,
)
from .reports import render_expenses, render_summary, render_table
from .storage import Database, StorageError

PROGRAM = "expenses"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Track daily expenses by category and keep a rolling 12 month history.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  expenses night                       log everything you spent today, one line at a time\n"
            "  expenses add Coffee 4.50 Dining      log a single expense\n"
            "  expenses add Petrol 60 Transport -d yesterday\n"
            "  expenses summary --month this        spend per category this month\n"
            "  expenses list --days 7               the last seven days of expenses\n"
            "  expenses web                         open the browser interface\n"
        ),
    )
    parser.add_argument("--version", action="version", version="%s %s" % (PROGRAM, __version__))
    _add_global_arguments(parser)

    # The same global flags are accepted after the subcommand, since that is
    # where people naturally reach for them. SUPPRESS keeps an unused
    # subcommand copy from overwriting a value given before the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    _add_global_arguments(common, default=argparse.SUPPRESS)

    subparsers = parser.add_subparsers(dest="command")

    def add_command(name, **kwargs):
        kwargs.setdefault("parents", [common])
        return subparsers.add_parser(name, **kwargs)

    add = add_command("add", help="record one expense")
    add.add_argument("item", help="what you bought, e.g. \"Weekly groceries\"")
    add.add_argument("amount", help="how much it cost, e.g. 42.30")
    add.add_argument("category", nargs="?", default="Other", help="category name (default: Other)")
    add.add_argument("-d", "--date", default="today", help="date of the expense (default: today)")
    add.add_argument("-n", "--note", default="", help="optional note")
    add.set_defaults(handler=command_add)

    night = add_command(
        "night",
        help="interactive nightly entry: add each of the day's expenses in one sitting",
    )
    night.add_argument("-d", "--date", default="today", help="date to log against (default: today)")
    night.set_defaults(handler=command_night)

    listing = add_command("list", aliases=["ls"], help="show recorded expenses")
    _add_range_arguments(listing)
    listing.add_argument("-c", "--category", help="only this category")
    listing.add_argument("-s", "--search", help="match text in the item or note")
    listing.add_argument("-l", "--limit", type=int, help="show at most this many entries")
    listing.add_argument("--oldest-first", action="store_true", help="sort oldest to newest")
    listing.add_argument("--json", action="store_true", help="print JSON instead of a table")
    listing.set_defaults(handler=command_list)

    summary = add_command("summary", help="totals grouped by category, month or day")
    _add_range_arguments(summary)
    summary.add_argument(
        "-b",
        "--by",
        default="category",
        choices=["category", "month", "day", "item"],
        help="what to group by (default: category)",
    )
    summary.add_argument("-c", "--category", help="only this category")
    summary.add_argument("-s", "--search", help="match text in the item or note")
    summary.add_argument("--json", action="store_true", help="print JSON instead of a table")
    summary.set_defaults(handler=command_summary)

    edit = add_command("edit", help="change an existing expense")
    edit.add_argument("id", type=int, help="expense id, as shown by `expenses list`")
    edit.add_argument("-i", "--item")
    edit.add_argument("-a", "--amount")
    edit.add_argument("-c", "--category")
    edit.add_argument("-d", "--date")
    edit.add_argument("-n", "--note")
    edit.set_defaults(handler=command_edit)

    delete = add_command("delete", aliases=["rm"], help="remove an expense")
    delete.add_argument("id", type=int, nargs="+", help="one or more expense ids")
    delete.add_argument("-f", "--force", action="store_true", help="do not ask for confirmation")
    delete.set_defaults(handler=command_delete)

    categories = add_command("categories", aliases=["cat"], help="manage categories")
    category_actions = categories.add_subparsers(dest="action")
    category_list = category_actions.add_parser("list", help="list categories (default)")
    category_list.set_defaults(action="list")
    category_add = category_actions.add_parser("add", help="create a category")
    category_add.add_argument("name")
    category_add.set_defaults(action="add")
    category_rename = category_actions.add_parser("rename", help="rename a category")
    category_rename.add_argument("old")
    category_rename.add_argument("new")
    category_rename.set_defaults(action="rename")
    category_delete = category_actions.add_parser("delete", aliases=["rm"], help="delete a category")
    category_delete.add_argument("name")
    category_delete.add_argument("--move-to", help="category to move existing expenses into")
    category_delete.set_defaults(action="delete")
    categories.set_defaults(handler=command_categories, action=None)

    export = add_command("export", help="write expenses to CSV or JSON")
    _add_range_arguments(export)
    export.add_argument("-o", "--out", help="file to write (default: stdout)")
    export.add_argument("--format", default="csv", choices=["csv", "json"])
    export.set_defaults(handler=command_export)

    importer = add_command("import", help="load expenses from a CSV file")
    importer.add_argument("path", help="CSV with date,item,category,amount,note columns")
    importer.set_defaults(handler=command_import)

    prune = add_command(
        "prune", help="archive expenses that have aged out of the retention window"
    )
    prune.add_argument("--dry-run", action="store_true", help="show what would be archived")
    prune.set_defaults(handler=command_prune)

    web = add_command("web", help="serve the browser interface on this machine")
    web.add_argument("-p", "--port", type=int, default=8765, help="port to listen on (default: 8765)")
    web.add_argument("--host", default="127.0.0.1", help="interface to bind (default: 127.0.0.1)")
    web.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    web.set_defaults(handler=command_web)

    config = add_command("config", help="show or change settings")
    config.add_argument("--currency", help="currency symbol used when displaying amounts")
    config.add_argument(
        "--retention-months",
        type=int,
        help="how many months of history to keep (default: 12)",
    )
    config.set_defaults(handler=command_config)

    return parser


def _add_global_arguments(parser: argparse.ArgumentParser, default=None) -> None:
    parser.add_argument(
        "--db",
        metavar="PATH",
        default=default,
        help="use a specific database file",
    )
    parser.add_argument(
        "--no-prune",
        action="store_true",
        default=default if default is argparse.SUPPRESS else False,
        help="skip the automatic archiving of entries older than the retention window",
    )


def _add_range_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("date range")
    group.add_argument("-m", "--month", help="a month such as 2026-08, august, this or last")
    group.add_argument("-y", "--year", type=int, help="a whole calendar year")
    group.add_argument("--days", type=int, help="the last N days including today")
    group.add_argument("--from", dest="start", help="start date (inclusive)")
    group.add_argument("--to", dest="end", help="end date (inclusive)")


# ---------------------------------------------------------------- commands


def command_add(args, database: Database) -> int:
    expense = database.add_expense(
        item=args.item,
        amount=args.amount,
        category=_resolve_category(database, args.category),
        spent_on=args.date,
        note=args.note,
    )
    symbol = database.currency_symbol
    print(
        "Added #%d  %s  %s  %s  %s"
        % (
            expense.id,
            format_date(expense.spent_on),
            expense.item,
            expense.category,
            format_amount(expense.amount_cents, symbol),
        )
    )
    day_total = database.totals(start=expense.spent_on, end=expense.spent_on)
    print(
        "Total for %s: %s"
        % (format_date(expense.spent_on), format_amount(day_total.total_cents, symbol))
    )
    return 0


def command_night(args, database: Database) -> int:
    date_value = parse_date(args.date)
    symbol = database.currency_symbol
    categories = database.categories()

    print("Logging expenses for %s. Press Enter on an empty item when you are done." % format_date(date_value))
    print("Categories: %s" % ", ".join(categories))
    print()

    added = 0
    last_category = None
    while True:
        try:
            item = input("Item (blank to finish): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not item:
            break

        try:
            amount_text = input("  Amount: ").strip()
            default_category = last_category or "Other"
            prompt = "  Category [%s]: " % default_category
            category_text = input(prompt).strip() or default_category
            note = input("  Note (optional): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        try:
            category = _resolve_category(database, category_text)
            expense = database.add_expense(
                item=item,
                amount=amount_text,
                category=category,
                spent_on=date_value,
                note=note,
            )
        except (ParseError, StorageError) as error:
            print("  Not saved: %s" % error)
            continue

        added += 1
        last_category = expense.category
        print(
            "  Saved #%d %s under %s"
            % (expense.id, format_amount(expense.amount_cents, symbol), expense.category)
        )

    print()
    if added:
        day_total = database.totals(start=date_value, end=date_value)
        print(
            "Recorded %d expense(s). Total for %s: %s"
            % (added, format_date(date_value), format_amount(day_total.total_cents, symbol))
        )
        buckets = database.summary("category", start=date_value, end=date_value)
        print()
        print(render_summary(buckets, symbol, title="Spend by category today"))
    else:
        print("Nothing recorded.")
    return 0


def command_list(args, database: Database) -> int:
    start, end = _range_from_args(args)
    expenses = database.list_expenses(
        start=start,
        end=end,
        category=_resolve_category(database, args.category) if args.category else None,
        search=args.search,
        limit=args.limit,
        newest_first=not args.oldest_first,
    )
    symbol = database.currency_symbol
    if args.json:
        print(json.dumps([expense.to_dict(symbol) for expense in expenses], indent=2))
        return 0
    print("Expenses (%s)" % describe_range(start, end))
    print()
    print(render_expenses(expenses, symbol))
    return 0


def command_summary(args, database: Database) -> int:
    start, end = _range_from_args(args)
    buckets = database.summary(
        args.by,
        start=start,
        end=end,
        category=_resolve_category(database, args.category) if args.category else None,
        search=args.search,
    )
    symbol = database.currency_symbol
    if args.json:
        payload = {
            "range": {
                "start": format_date(start) if start else None,
                "end": format_date(end) if end else None,
            },
            "group_by": args.by,
            "buckets": [bucket.to_dict(symbol) for bucket in buckets],
            "total_cents": sum(bucket.total_cents for bucket in buckets),
        }
        print(json.dumps(payload, indent=2))
        return 0

    labels = {"category": "CATEGORY", "month": "MONTH", "day": "DAY", "item": "ITEM"}
    title = "Spend by %s (%s)" % (args.by, describe_range(start, end))
    print(render_summary(buckets, symbol, title=title, label=labels[args.by]))
    return 0


def command_edit(args, database: Database) -> int:
    category = _resolve_category(database, args.category) if args.category else None
    expense = database.update_expense(
        args.id,
        item=args.item,
        amount=args.amount,
        category=category,
        spent_on=args.date,
        note=args.note,
    )
    symbol = database.currency_symbol
    print(
        "Updated #%d  %s  %s  %s  %s"
        % (
            expense.id,
            format_date(expense.spent_on),
            expense.item,
            expense.category,
            format_amount(expense.amount_cents, symbol),
        )
    )
    return 0


def command_delete(args, database: Database) -> int:
    symbol = database.currency_symbol
    removed = 0
    for expense_id in args.id:
        expense = database.get_expense(expense_id)
        if expense is None:
            print("No expense with id %d" % expense_id, file=sys.stderr)
            continue
        if not args.force:
            description = "%s  %s  %s  %s" % (
                format_date(expense.spent_on),
                expense.item,
                expense.category,
                format_amount(expense.amount_cents, symbol),
            )
            answer = input("Delete #%d (%s)? [y/N] " % (expense.id, description)).strip().lower()
            if answer not in {"y", "yes"}:
                print("Kept #%d" % expense.id)
                continue
        database.delete_expense(expense_id)
        removed += 1
        print("Deleted #%d" % expense_id)
    return 0 if removed or not args.id else 1


def command_categories(args, database: Database) -> int:
    action = getattr(args, "action", None) or "list"
    if action == "add":
        name = database.add_category(args.name)
        print("Category %r is available." % name)
        return 0
    if action == "rename":
        moved = database.rename_category(args.old, args.new)
        print("Renamed %r to %r (%d expense(s) updated)." % (args.old, args.new, moved))
        return 0
    if action == "delete":
        moved = database.delete_category(args.name, args.move_to)
        if moved:
            print("Deleted %r and moved %d expense(s) to %r." % (args.name, moved, args.move_to))
        else:
            print("Deleted %r." % args.name)
        return 0

    symbol = database.currency_symbol
    totals = {bucket.key.lower(): bucket for bucket in database.summary("category")}
    rows: List[List[str]] = []
    for name in database.categories():
        bucket = totals.get(name.lower())
        rows.append(
            [
                name,
                str(bucket.count) if bucket else "0",
                format_amount(bucket.total_cents, symbol) if bucket else format_amount(0, symbol),
            ]
        )
    print(render_table(["CATEGORY", "ENTRIES", "TOTAL"], rows, ["left", "right", "right"]))
    return 0


def command_export(args, database: Database) -> int:
    start, end = _range_from_args(args)
    expenses = database.list_expenses(start=start, end=end, newest_first=False)
    symbol = database.currency_symbol

    if args.format == "json":
        payload = json.dumps([expense.to_dict(symbol) for expense in expenses], indent=2)
        if args.out:
            Path(args.out).expanduser().write_text(payload + "\n", encoding="utf-8")
            print("Wrote %d expense(s) to %s" % (len(expenses), args.out))
        else:
            print(payload)
        return 0

    if args.out:
        target = Path(args.out).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="", encoding="utf-8") as handle:
            database.export_csv(handle, expenses)
        print("Wrote %d expense(s) to %s" % (len(expenses), target))
    else:
        database.export_csv(sys.stdout, expenses)
    return 0


def command_import(args, database: Database) -> int:
    path = Path(args.path).expanduser()
    if not path.exists():
        raise StorageError("No such file: %s" % path)
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        imported = database.import_csv(handle)
    print("Imported %d expense(s) from %s" % (imported, path))
    return 0


def command_prune(args, database: Database) -> int:
    result = database.prune(dry_run=args.dry_run)
    symbol = database.currency_symbol
    if not result.count:
        print(
            "Nothing to archive. Everything on or after %s is inside the %d month window."
            % (format_date(result.cutoff), database.retention_months)
        )
        return 0
    if args.dry_run:
        print(
            "%d expense(s) totalling %s are older than %s and would be archived."
            % (result.count, format_amount(result.total_cents, symbol), format_date(result.cutoff))
        )
        return 0
    print(
        "Archived %d expense(s) totalling %s (dated before %s) to %s"
        % (
            result.count,
            format_amount(result.total_cents, symbol),
            format_date(result.cutoff),
            result.archive_path,
        )
    )
    return 0


def command_web(args, database: Database) -> int:
    from .webapp import serve

    return serve(
        database,
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
    )


def command_config(args, database: Database) -> int:
    changed = False
    if args.currency:
        database.set_setting("currency_symbol", args.currency)
        changed = True
    if args.retention_months:
        if args.retention_months < 1:
            raise ParseError("--retention-months must be at least 1")
        database.set_setting("retention_months", str(args.retention_months))
        changed = True

    span = database.date_span()
    totals = database.totals()
    rows = [
        ["database", str(database.path)],
        ["archive", str(database.archive_path())],
        ["currency", database.currency_symbol],
        ["retention", "%d months (keeping entries on or after %s)" % (
            database.retention_months,
            format_date(database.retention_cutoff()),
        )],
        ["expenses", "%d recorded, total %s" % (
            totals.count,
            format_amount(totals.total_cents, database.currency_symbol),
        )],
        ["history", "%s to %s" % (format_date(span[0]), format_date(span[1])) if span else "empty"],
        ["last prune", database.get_setting("last_prune_at", "never") or "never"],
    ]
    if changed:
        print("Settings updated.")
        print()
    print(render_table(["SETTING", "VALUE"], rows))
    return 0


# ----------------------------------------------------------------- helpers


def _range_from_args(args) -> tuple:
    return resolve_range(
        start=getattr(args, "start", None),
        end=getattr(args, "end", None),
        month=getattr(args, "month", None),
        year=getattr(args, "year", None),
        days=getattr(args, "days", None),
    )


def _resolve_category(database: Database, text: Optional[str]) -> str:
    """Map user input onto an existing category when it is unambiguous."""

    if text is None:
        return "Other"
    candidate = text.strip()
    if not candidate:
        return "Other"

    known = database.categories()
    if candidate.isdigit():
        index = int(candidate) - 1
        if 0 <= index < len(known):
            return known[index]

    lowered = candidate.lower()
    for name in known:
        if name.lower() == lowered:
            return name
    prefix_matches = [name for name in known if name.lower().startswith(lowered)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    return candidate


def _auto_prune(database: Database, stream=None) -> None:
    """Keep the rolling window tidy without the user having to think about it."""

    stream = stream or sys.stderr
    with contextlib.suppress(Exception):
        last = database.get_setting("last_prune_at")
        if last and last[:10] == format_date(today()):
            return
        result = database.prune()
        if result.count:
            print(
                "Archived %d expense(s) older than %s to %s"
                % (result.count, format_date(result.cutoff), result.archive_path),
                file=stream,
            )
        else:
            database.set_setting("last_prune_at", dt.datetime.now().replace(microsecond=0).isoformat(sep=" "))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "handler", None):
        parser.print_help()
        return 0

    try:
        database = Database(args.db)
        if not args.no_prune and args.command != "prune":
            _auto_prune(database)
        return args.handler(args, database)
    except (ParseError, StorageError) as error:
        print("Error: %s" % error, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
