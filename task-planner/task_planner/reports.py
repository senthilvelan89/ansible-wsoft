"""Plain text rendering of the board, queues and comments."""

from __future__ import annotations

from typing import Optional, Sequence

from .parsing import format_date, today
from .storage import CategoryBoard, Comment, Task


def render_table(headers: Sequence[str], rows: Sequence[Sequence[str]], aligns: Optional[Sequence[str]] = None) -> str:
    """Render a simple fixed width table."""

    if not rows:
        return ""
    columns = len(headers)
    aligns = list(aligns or ["left"] * columns)
    widths = [len(str(header)) for header in headers]
    for row in rows:
        for index in range(columns):
            widths[index] = max(widths[index], len(str(row[index])))

    def line(values: Sequence[str]) -> str:
        cells = []
        for index in range(columns):
            text = str(values[index])
            if aligns[index] == "right":
                cells.append(text.rjust(widths[index]))
            else:
                cells.append(text.ljust(widths[index]))
        return "  ".join(cells).rstrip()

    separator = "  ".join("-" * width for width in widths)
    body = [line(headers), separator]
    body.extend(line(row) for row in rows)
    return "\n".join(body)


def due_label(task: Task, reference=None) -> str:
    if task.due_on is None:
        return "no date"
    ref = reference or today()
    stamp = format_date(task.due_on)
    if task.status == "done":
        return stamp
    if task.due_on < ref:
        return "%s overdue" % stamp
    if task.due_on == ref:
        return "%s today" % stamp
    return stamp


def render_board(categories: Sequence[CategoryBoard], reference=None) -> str:
    if not categories:
        return "No categories yet. Add one with `tasks categories add Career`."

    ref = reference or today()
    blocks = []
    for board in categories:
        header = "%s  (%d open)" % (board.category.name, board.open_count)
        blocks.append(header)
        blocks.append("-" * len(header))
        if board.next_step is None:
            blocks.append("  NEXT  (none)  add a next step so this category is not skipped")
        else:
            task = board.next_step
            blocks.append("  NEXT  #%d  %s  [%s]" % (task.id, task.title, due_label(task, ref)))
            for upcoming in board.upcoming:
                blocks.append("  then  #%d  %s  [%s]" % (upcoming.id, upcoming.title, due_label(upcoming, ref)))
        if board.latest_comment:
            comment = board.latest_comment
            blocks.append("  note  %s  %s" % (format_date(comment.comment_on), comment.body))
        blocks.append("")
    return "\n".join(blocks).rstrip() + "\n"


def render_tasks(tasks: Sequence[Task], show_category: bool = True) -> str:
    if not tasks:
        return "No tasks in this view."

    headers = ["ID", "STATUS", "DUE", "TITLE"]
    aligns = ["right", "left", "left", "left"]
    if show_category:
        headers.insert(1, "CATEGORY")
        aligns.insert(1, "left")

    rows = []
    for task in tasks:
        row = [str(task.id), task.status, due_label(task), task.title]
        if show_category:
            row.insert(1, task.category)
        rows.append(row)
    return render_table(headers, rows, aligns)


def render_comments(comments: Sequence[Comment]) -> str:
    if not comments:
        return "No comments yet."

    rows = []
    for comment in comments:
        attached = comment.task_title or "(category)"
        rows.append(
            [
                str(comment.id),
                format_date(comment.comment_on) or "",
                comment.category,
                attached,
                comment.body,
            ]
        )
    return render_table(
        ["ID", "DATE", "CATEGORY", "TASK", "COMMENT"],
        rows,
        ["right", "left", "left", "left", "left"],
    )
