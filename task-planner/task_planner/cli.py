"""Command line interface for the task planner."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

from . import DEFAULT_WEB_PORT, __version__
from .parsing import ParseError, describe_range, format_date, resolve_range, today
from .reports import render_board, render_comments, render_table, render_tasks
from .storage import Database, StorageError

PROGRAM = "tasks"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="See the next step in every category, with dated comments so nothing gets skipped.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  tasks                                 next step in every category\n"
            "  tasks add \"Book school tour\" -c Family -d 2026-09-12\n"
            "  tasks done 4                          mark that next step complete\n"
            "  tasks comment 4 \"left a voicemail\" -d today\n"
            "  tasks web                             open the browser interface on port 8766\n"
        ),
    )
    parser.add_argument("--version", action="version", version="%s %s" % (PROGRAM, __version__))
    _add_global_arguments(parser)

    common = argparse.ArgumentParser(add_help=False)
    _add_global_arguments(common, default=argparse.SUPPRESS)

    subparsers = parser.add_subparsers(dest="command")

    def add_command(name, **kwargs):
        kwargs.setdefault("parents", [common])
        return subparsers.add_parser(name, **kwargs)

    board = add_command("board", aliases=["next"], help="show the next step in every category")
    board.add_argument("--json", action="store_true", help="print JSON instead of text")
    board.set_defaults(handler=command_board)

    add = add_command("add", help="queue a step in a category")
    add.add_argument("title", help="what needs doing, e.g. \"Book school tour\"")
    add.add_argument("-c", "--category", required=True, help="category this belongs to")
    add.add_argument("-d", "--due", help="due date (today, tomorrow, YYYY-MM-DD)")
    add.add_argument("--next", action="store_true", dest="as_next", help="insert as the next step, ahead of the queue")
    add.set_defaults(handler=command_add)

    done = add_command("done", aliases=["complete"], help="mark a task done and promote the following step")
    done.add_argument("id", type=int, help="task id, as shown by `tasks board`")
    done.set_defaults(handler=command_done)

    reopen = add_command("reopen", help="put a completed task back on the queue")
    reopen.add_argument("id", type=int)
    reopen.add_argument("--next", action="store_true", dest="as_next", help="make it the next step")
    reopen.set_defaults(handler=command_reopen)

    listing = add_command("list", aliases=["ls"], help="list tasks")
    listing.add_argument("-c", "--category", help="only this category")
    listing.add_argument("-s", "--status", choices=["open", "done"], help="filter by status")
    listing.add_argument("--search", help="match text in the title")
    listing.add_argument("-l", "--limit", type=int, help="show at most this many")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(handler=command_list)

    edit = add_command("edit", help="change an existing task")
    edit.add_argument("id", type=int)
    edit.add_argument("-i", "--title")
    edit.add_argument("-c", "--category")
    edit.add_argument("-d", "--due")
    edit.add_argument("--clear-due", action="store_true", help="remove the due date")
    edit.set_defaults(handler=command_edit)

    delete = add_command("delete", aliases=["rm"], help="remove a task")
    delete.add_argument("id", type=int, nargs="+")
    delete.add_argument("-f", "--force", action="store_true", help="do not ask for confirmation")
    delete.set_defaults(handler=command_delete)

    move = add_command("move", help="reorder an open task in its category")
    move.add_argument("id", type=int)
    move.add_argument("direction", choices=["up", "down", "sooner", "later"], help="up/sooner makes it the earlier step")
    move.set_defaults(handler=command_move)

    comment = add_command("comment", help="add a dated comment on a task or category")
    comment.add_argument("text", help="what happened or what to remember")
    comment.add_argument("-c", "--category", help="attach to a category")
    comment.add_argument("-t", "--task", type=int, help="attach to a task id")
    comment.add_argument("-d", "--date", default="today", help="date to track against (default: today)")
    comment.set_defaults(handler=command_comment)

    comments = add_command("comments", help="show dated comments")
    _add_range_arguments(comments)
    comments.add_argument("-c", "--category")
    comments.add_argument("-t", "--task", type=int)
    comments.add_argument("-l", "--limit", type=int, default=50)
    comments.add_argument("--json", action="store_true")
    comments.set_defaults(handler=command_comments)

    note_delete = add_command("uncomment", help="delete a comment")
    note_delete.add_argument("id", type=int)
    note_delete.set_defaults(handler=command_uncomment)

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
    category_delete.add_argument("--move-to", help="category to move existing tasks into")
    category_delete.set_defaults(action="delete")
    categories.set_defaults(handler=command_categories, action=None)

    web = add_command("web", help="serve the browser interface on this machine")
    web.add_argument("-p", "--port", type=int, default=DEFAULT_WEB_PORT, help="port to listen on (default: %d)" % DEFAULT_WEB_PORT)
    web.add_argument("--host", default="127.0.0.1", help="interface to bind (default: 127.0.0.1)")
    web.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    web.set_defaults(handler=command_web)

    config = add_command("config", help="show where the database lives")
    config.set_defaults(handler=command_config)

    return parser


def _add_global_arguments(parser: argparse.ArgumentParser, default=None) -> None:
    parser.add_argument(
        "--db",
        metavar="PATH",
        default=default,
        help="use a specific database file",
    )


def _add_range_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("date range")
    group.add_argument("-m", "--month", help="a month such as 2026-08, august, this or last")
    group.add_argument("-y", "--year", type=int, help="a whole calendar year")
    group.add_argument("--days", type=int, help="the last N days including today")
    group.add_argument("--from", dest="start", help="start date (inclusive)")
    group.add_argument("--to", dest="end", help="end date (inclusive)")


# ---------------------------------------------------------------- commands


def command_board(args, database: Database) -> int:
    boards = database.board()
    stats = database.stats()
    if args.json:
        print(
            json.dumps(
                {
                    "today": format_date(today()),
                    "stats": stats,
                    "categories": [board.to_dict() for board in boards],
                },
                indent=2,
            )
        )
        return 0

    print("Next step in each category  (%s)" % format_date(today()))
    print(
        "%d categories · %d with a next step · %d missing · %d overdue · %d due today"
        % (
            stats["categories"],
            stats["with_next_step"],
            stats["missing_next_step"],
            stats["overdue"],
            stats["due_today"],
        )
    )
    print()
    print(render_board(boards))
    missing = [board.category.name for board in boards if board.next_step is None]
    if missing:
        print("Needs a next step: %s" % ", ".join(missing))
    return 0


def command_add(args, database: Database) -> int:
    category = _resolve_category(database, args.category, create=True)
    task = database.add_task(args.title, category, due_on=args.due, as_next=args.as_next)
    next_step = database.next_step(task.category)
    print("Queued #%d in %s: %s" % (task.id, task.category, task.title))
    if task.due_on:
        print("Due %s" % format_date(task.due_on))
    if next_step and next_step.id == task.id:
        print("This is now the next step for %s." % task.category)
    elif next_step:
        print("Next step for %s is still #%d %s." % (task.category, next_step.id, next_step.title))
    return 0


def command_done(args, database: Database) -> int:
    task = database.get_task(args.id)
    if task is None:
        raise StorageError("No task with id %d" % args.id)
    next_before = database.next_step(task.category)
    skipped = next_before is not None and next_before.id != task.id
    completed = database.complete_task(args.id)
    print("Done #%d  %s  (%s)" % (completed.id, completed.title, completed.category))
    if skipped:
        print("Note: that was not the next step for %s. Next was #%d %s." % (
            task.category, next_before.id, next_before.title
        ))
    promoted = database.next_step(completed.category)
    if promoted:
        print("Next for %s: #%d  %s" % (completed.category, promoted.id, promoted.title))
    else:
        print("No next step left in %s — add one so this category is not skipped." % completed.category)
    return 0


def command_reopen(args, database: Database) -> int:
    task = database.reopen_task(args.id, as_next=args.as_next)
    print("Reopened #%d  %s  (%s)" % (task.id, task.title, task.category))
    next_step = database.next_step(task.category)
    if next_step:
        print("Next for %s: #%d  %s" % (task.category, next_step.id, next_step.title))
    return 0


def command_list(args, database: Database) -> int:
    category = _resolve_category(database, args.category) if args.category else None
    tasks = database.list_tasks(
        category=category,
        status=args.status,
        search=args.search,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps([task.to_dict() for task in tasks], indent=2))
        return 0
    title = "Tasks"
    if category:
        title += " in %s" % category
    if args.status:
        title += " (%s)" % args.status
    print(title)
    print()
    print(render_tasks(tasks, show_category=not category))
    return 0


def command_edit(args, database: Database) -> int:
    category = _resolve_category(database, args.category, create=True) if args.category else None
    task = database.update_task(
        args.id,
        title=args.title,
        category=category,
        due_on=args.due,
        clear_due=args.clear_due,
    )
    print("Updated #%d  %s  (%s)  due %s" % (
        task.id,
        task.title,
        task.category,
        format_date(task.due_on) or "none",
    ))
    return 0


def command_delete(args, database: Database) -> int:
    removed = 0
    for task_id in args.id:
        task = database.get_task(task_id)
        if task is None:
            print("No task with id %d" % task_id, file=sys.stderr)
            continue
        if not args.force:
            answer = input("Delete #%d %s (%s)? [y/N] " % (task.id, task.title, task.category)).strip().lower()
            if answer not in {"y", "yes"}:
                print("Kept #%d" % task.id)
                continue
        database.delete_task(task_id)
        removed += 1
        print("Deleted #%d" % task_id)
    return 0 if removed or not args.id else 1


def command_move(args, database: Database) -> int:
    direction = "up" if args.direction in {"up", "sooner"} else "down"
    task = database.move_task(args.id, direction)
    next_step = database.next_step(task.category)
    print("Moved #%d %s" % (task.id, "sooner" if direction == "up" else "later"))
    if next_step:
        print("Next for %s: #%d  %s" % (task.category, next_step.id, next_step.title))
    return 0


def command_comment(args, database: Database) -> int:
    if not args.category and not args.task:
        raise ParseError("Pass --category or --task so the comment has a place to live")
    category = _resolve_category(database, args.category) if args.category else None
    comment = database.add_comment(
        args.text,
        category=category,
        task_id=args.task,
        comment_on=args.date,
    )
    attached = "#%d %s" % (comment.task_id, comment.task_title) if comment.task_id else comment.category
    print("Comment #%d on %s  [%s]" % (comment.id, attached, format_date(comment.comment_on)))
    print(comment.body)
    return 0


def command_comments(args, database: Database) -> int:
    start, end = resolve_range(
        start=getattr(args, "start", None),
        end=getattr(args, "end", None),
        month=getattr(args, "month", None),
        year=getattr(args, "year", None),
        days=getattr(args, "days", None),
    )
    category = _resolve_category(database, args.category) if args.category else None
    comments = database.list_comments(
        category=category,
        task_id=args.task,
        start=start,
        end=end,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps([comment.to_dict() for comment in comments], indent=2))
        return 0
    print("Comments (%s)" % describe_range(start, end))
    print()
    print(render_comments(comments))
    return 0


def command_uncomment(args, database: Database) -> int:
    if not database.delete_comment(args.id):
        raise StorageError("No comment with id %d" % args.id)
    print("Deleted comment #%d" % args.id)
    return 0


def command_categories(args, database: Database) -> int:
    action = getattr(args, "action", None) or "list"
    if action == "add":
        category = database.add_category(args.name)
        print("Category %r is available." % category.name)
        return 0
    if action == "rename":
        category = database.rename_category(args.old, args.new)
        print("Renamed to %r." % category.name)
        return 0
    if action == "delete":
        moved = database.delete_category(args.name, move_to=args.move_to)
        if args.move_to:
            print("Deleted %r and moved tasks to %r." % (args.name, args.move_to))
        else:
            print("Deleted %r." % args.name)
        return 0 if moved is not None else 1

    boards = database.board()
    rows = []
    for board in boards:
        next_title = board.next_step.title if board.next_step else "(none)"
        rows.append(
            [
                board.category.name,
                str(board.open_count),
                str(board.done_count),
                next_title,
            ]
        )
    print(render_table(["CATEGORY", "OPEN", "DONE", "NEXT STEP"], rows, ["left", "right", "right", "left"]))
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
    stats = database.stats()
    rows = [
        ["database", str(database.path)],
        ["categories", str(stats["categories"])],
        ["open tasks", str(stats["open_tasks"])],
        ["with next step", str(stats["with_next_step"])],
        ["missing next step", str(stats["missing_next_step"])],
        ["overdue", str(stats["overdue"])],
        ["web", "http://127.0.0.1:%d/  (tasks web)" % DEFAULT_WEB_PORT],
    ]
    print(render_table(["SETTING", "VALUE"], rows))
    return 0


# ----------------------------------------------------------------- helpers


def _resolve_category(database: Database, text: Optional[str], create: bool = False) -> str:
    if text is None:
        raise ParseError("Category is required")
    candidate = text.strip()
    if not candidate:
        raise ParseError("Category is required")

    known = [category.name for category in database.categories()]
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
    if create:
        return candidate
    raise StorageError("Unknown category %r" % candidate)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "handler", None):
        args.handler = command_board
        args.json = False
        args.command = "board"

    try:
        database = Database(args.db)
        return args.handler(args, database)
    except (ParseError, StorageError) as error:
        print("Error: %s" % error, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
