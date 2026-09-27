# Expense Tracker

A personal expense tracker that runs entirely on your Mac. Enter what you spent
each night, get it categorised, and pull up totals whenever you want. Your data
lives in a single SQLite file in your home folder, a rolling **12 months** of
history is kept, and anything older is archived to CSV rather than thrown away.

There are two ways to use it, both backed by the same database:

- a **command line tool** for fast nightly entry, and
- a **browser interface** if you prefer clicking and charts.

No installation, no dependencies, no accounts, no network access. It only needs
the Python 3 that ships with macOS.

---

## Getting started

Open Terminal and go to this folder:

```bash
cd path/to/expense-tracker
chmod +x expenses          # only needed once
./expenses config          # creates the database and shows where it lives
```

If macOS says Python is missing, install the Apple developer command line tools
with `xcode-select --install`, which includes Python 3.

Optionally make the command available everywhere so you can just type
`expenses` from any folder:

```bash
echo "alias expenses='$(pwd)/expenses'" >> ~/.zshrc
source ~/.zshrc
```

---

## The nightly routine

At the end of the day run:

```bash
expenses night
```

It asks for each expense in turn and keeps going until you press Enter on an
empty item, then shows the day's total and a category breakdown:

```
Logging expenses for 2026-09-01. Press Enter on an empty item when you are done.
Categories: Dining, Education, Entertainment, Groceries, ...

Item (blank to finish): Coffee with Sam
  Amount: 4.50
  Category [Other]: Dining
  Note (optional):
  Saved #2 $4.50 under Dining
Item (blank to finish): Metro card top up
  Amount: 30
  Category [Dining]: Transport
  Note (optional): monthly pass
  Saved #3 $30.00 under Transport
Item (blank to finish):

Recorded 2 expense(s). Total for 2026-09-01: $34.50
```

To log an expense in a single line instead:

```bash
expenses add "Weekly groceries" 82.40 Groceries
expenses add "Cinema tickets" 24 Entertainment -d yesterday
expenses add "Parking" 6.50 Transport -d 2026-08-28 -n "airport run"
```

The category can be abbreviated as long as it is unambiguous, so `din` becomes
`Dining`. Unknown categories are created on the spot.

---

## Getting your money back out

```bash
expenses summary                     # spend per category, all time
expenses summary --month this        # this month
expenses summary --month 2026-07     # a specific month
expenses summary --days 30           # the last 30 days
expenses summary --by month          # month by month totals
expenses summary --by day --month this
expenses summary --by item --category Dining
```

```
Spend by category (2026-08-01 to 2026-08-31)
CATEGORY        TOTAL   SHARE  COUNT
-------------  ------  ------  -----  ------------------------
Groceries      $82.40   58.5%      1  ████████████████████████
Transport      $30.00   21.3%      1  █████████
Entertainment  $24.00   17.0%      1  ███████
Dining          $4.50    3.2%      1  █

TOTAL: $140.90 across 4 expense(s)
```

To see the individual entries:

```bash
expenses list --days 7
expenses list --month last --category Groceries
expenses list --search "uber"
expenses list --from 2026-01-01 --to 2026-03-31
```

Every listing shows an ID you can use to fix mistakes:

```bash
expenses edit 12 --amount 45.90        # wrong number
expenses edit 12 --category Groceries  # wrong bucket
expenses edit 12 --date 2026-08-29     # wrong day
expenses delete 12
```

---

## The browser interface

```bash
expenses web
```

This starts a small server on your Mac and opens
<http://127.0.0.1:8765>. You get a form for date, item, cost and category, the
list of everything entered for the selected day, a category breakdown for the
month and a bar chart of the last 12 months. Press `Ctrl+C` in Terminal to stop
it.

The server listens on the loopback interface only, so nothing outside your Mac
can reach it, and it never sends your data anywhere.

---

## Categories

Twelve sensible categories exist from the start: Groceries, Dining, Transport,
Housing, Utilities, Health, Shopping, Entertainment, Travel, Education,
Personal and Other. Adjust them however you like:

```bash
expenses categories                                # list with totals
expenses categories add Pets
expenses categories rename Dining "Eating out"     # moves existing entries too
expenses categories delete Pets --move-to Other
```

---

## History, backups and the 12 month window

The database is at `~/.expense-tracker/expenses.db`. Everything is in that one
file, so a backup is a copy of that file.

The tool keeps 12 months of history. When an entry ages past that window it is
appended to `~/.expense-tracker/archive/expenses-archive.csv` and removed from
the active database. This happens automatically the first time you run a
command each day, and you can always trigger or preview it yourself:

```bash
expenses prune --dry-run    # show what would be archived
expenses prune              # archive it now
```

Nothing is ever deleted without being written to the archive CSV first, so old
years remain readable in Excel or Numbers.

Want a different window? `expenses config --retention-months 24`.

To take your data elsewhere:

```bash
expenses export -o ~/Desktop/expenses.csv
expenses export --month 2026-08 -o ~/Desktop/august.csv
expenses export --format json
expenses import ~/Desktop/expenses.csv
```

An imported CSV needs `date`, `item` and `amount` columns; `category` and
`note` are used when present.

---

## Settings

```bash
expenses config                          # where things live, what is stored
expenses config --currency £             # change the displayed symbol
expenses config --retention-months 24    # keep more history
```

```
SETTING     VALUE
----------  -----------------------------------------------------------
database    /Users/you/.expense-tracker/expenses.db
archive     /Users/you/.expense-tracker/archive/expenses-archive.csv
currency    $
retention   12 months (keeping entries on or after 2025-09-01)
expenses    4 recorded, total $140.90
history     2026-08-30 to 2026-09-01
last prune  2026-09-01 21:14:02
```

---

## Notes for the curious

- Amounts are stored as whole cents, so totals never drift the way floating
  point arithmetic does.
- Dates accept `today`, `yesterday`, `2026-08-30`, `08-30` and `-3` (three days
  ago).
- Months accept `this`, `last`, `2026-07`, `july` and `july 2025`.
- Set `EXPENSE_TRACKER_DB` to point at a different database file, or
  `EXPENSE_TRACKER_HOME` to move the whole folder, for example onto iCloud
  Drive so it syncs between machines.
- `expenses --help` and `expenses <command> --help` list everything.

## Running the tests

```bash
python3 -m unittest discover -s tests -t .
```
