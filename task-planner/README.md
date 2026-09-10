# Task Planner

A personal next-step board that runs entirely on your Mac. You keep several
categories of work; this tool makes the **next step in each category**
impossible to miss, with dated comments so you can see what happened and when.

It is built the same way as the expense tracker: a local SQLite file, a command
line tool, and a small browser interface. The expense tracker listens on
**port 8765**. This planner listens on **port 8766**, so both can run at the
same time.

No installation, no dependencies, no accounts, no network access. It only needs
the Python 3 that ships with macOS.

---

## Checkout and run on your Mac

The planner is on branch `cursor/add-task-planner-1e93` (pull request #5). It is
not on `main` yet.

**If you do not have the repo yet:**

```bash
cd ~
git clone https://github.com/senthilvelan89/ansible-wsoft.git
cd ansible-wsoft
git fetch origin cursor/add-task-planner-1e93
git checkout cursor/add-task-planner-1e93
```

**If you already cloned the repo:**

```bash
cd ~/ansible-wsoft          # or wherever you cloned it
git fetch origin cursor/add-task-planner-1e93
git checkout cursor/add-task-planner-1e93
```

Then start it:

```bash
cd task-planner
chmod +x tasks              # only needed once
./tasks                     # next step in each category, in Terminal
./tasks web                 # browser UI at http://127.0.0.1:8766
```

Leave that Terminal window open. Press `Ctrl+C` to stop the web server.

If macOS says Python is missing, install the Apple developer command line tools
with `xcode-select --install`, which includes Python 3.

This planner uses **port 8766**. The expense tracker uses **port 8765**, so both
can run at the same time. The expense tracker lives on a different branch
(`cursor/add-expense-tracker-tool-93de`); keep that clone in another folder if
you want both apps at once.

Your data is stored in `~/.task-planner/tasks.db` on this Mac. Nothing is sent
anywhere.

---

## Getting started

Open Terminal and go to this folder:

```bash
cd path/to/task-planner
chmod +x tasks          # only needed once
./tasks                 # shows the board (next step per category)
```

If macOS says Python is missing, install the Apple developer command line tools
with `xcode-select --install`, which includes Python 3.

Optionally make the command available everywhere:

```bash
echo "alias tasks='$(pwd)/tasks'" >> ~/.zshrc
source ~/.zshrc
```

Finance is created for you. Add the rest of your work categories yourself so the
board only shows what you actually run:

```bash
./tasks categories add Work
```

---

## The point of the board

When you look at the board you should only need to answer: **what is the next
step in this category?** Everything else waits in a queue behind that step, so
later work cannot jump the line and get forgotten.

```bash
tasks                  # or: tasks board
```

```
Next step in each category  (2026-09-10)
8 categories · 3 with a next step · 5 missing · 1 overdue · 1 due today

Family  (2 open)
----------------
  NEXT  #1  Book school tour  [2026-09-12]
  then  #2  Submit enrolment form  [no date]
  note  2026-09-10  left a voicemail with admissions

Finance  (1 open)
-----------------
  NEXT  #3  Review last month's expenses  [2026-09-10 today]

Career  (0 open)
----------------
  NEXT  (none)  add a next step so this category is not skipped
```

Categories with no next step are called out so they are not skipped.

---

## Queue a step

```bash
tasks add "Book school tour" -c Family -d 2026-09-12
tasks add "Submit enrolment form" -c Family
tasks add "Call the agent today" -c Property --next
```

`--next` inserts the step at the front of that category's queue. Without it,
the new step waits behind whatever is already next.

Mark the current next step done and the following one is promoted:

```bash
tasks done 1
# Next for Family: #2  Submit enrolment form
```

```bash
tasks list -c Family
tasks edit 2 --due tomorrow
tasks move 2 up
tasks delete 2
```

---

## Dated comments

Comments always have a date, so you can reconstruct what happened on a given
day without relying on memory.

```bash
tasks comment "left a voicemail with admissions" -t 1 -d today
tasks comment "waiting on rate lock" -c Property -d yesterday
tasks comments --days 14
tasks comments -c Family --month this
```

---

## The browser interface

```bash
tasks web
```

This starts a small server on your Mac and opens
<http://127.0.0.1:8766>. Each category is a card with the next step highlighted.
You can mark it done, queue the following step, and add a comment with a date.
Press `Ctrl+C` in Terminal to stop it.

The expense tracker stays on 8765; this board stays on 8766. Use
`tasks web --port 8767` if you ever need a different port.

The server listens on the loopback interface only, so nothing outside your Mac
can reach it, and it never sends your data anywhere.

---

## Categories

```bash
tasks categories
tasks categories add School
tasks categories rename Admin Paperwork
tasks categories delete School --move-to Family
```

---

## Settings

The database is at `~/.task-planner/tasks.db`. Everything is in that one file,
so a backup is a copy of that file.

```bash
tasks config
```

Set `TASK_PLANNER_DB` to point at a different database file, or
`TASK_PLANNER_HOME` to move the whole folder.

`tasks --help` and `tasks <command> --help` list everything.

## Running the tests

```bash
python3 -m unittest discover -s tests -t .
```
