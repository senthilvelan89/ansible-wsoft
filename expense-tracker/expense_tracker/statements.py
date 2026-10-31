"""Read bank statements and map merchants onto expense categories.

Typical monthly flow: on the 5th, drop in every account's previous-month PDF
(or CSV/OFX/QIF). Known merchants are filed from clues. Anything unclear is
left for you to assign — and that answer can be remembered as a new clue.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .parsing import ParseError, format_amount, format_date, parse_amount, parse_month, today
from .pdf_text import extract_pdf_text, looks_like_pdf
from .storage import INCOME_CATEGORY, Database, StorageError

SKIP_CATEGORY = "SKIP"

_MONTH_ABBR = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_MONTH_PAT = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
_WEEKDAY_PAT = (
    r"mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:rs(?:day)?)?|"
    r"fri(?:day)?|sat(?:urday)?|sun(?:day)?"
)
_DATE_NUMERIC = re.compile(
    r"\b(?P<a>\d{1,4})[/\-.](?P<b>\d{1,2})[/\-.](?P<c>\d{2,4})\b"
)
_DATE_NAMED = re.compile(
    r"\b(?:(?:%s)\s+)?(?P<d>\d{1,2})[.\s\-]+(?P<mon>%s)[.\s\-]+(?P<y>\d{2,4})\b"
    % (_WEEKDAY_PAT, _MONTH_PAT),
    re.I,
)
_DATE_NAMED_SHORT = re.compile(
    r"\b(?:(?:%s)\s+)?(?P<d>\d{1,2})[.\s\-]+(?P<mon>%s)\b" % (_WEEKDAY_PAT, _MONTH_PAT),
    re.I,
)
_DATE_MONTH_FIRST = re.compile(
    r"\b(?P<mon>%s)[.\s\-]+(?P<d>\d{1,2})(?:,)?[.\s\-]+(?P<y>\d{2,4})\b" % _MONTH_PAT,
    re.I,
)
_AMOUNT = re.compile(
    r"(?<![\w.])(?P<sign>[+\-\u2212\u2013])?\s*(?P<cur>\$|aud)?\s*"
    r"(?P<num>\d{1,3}(?:,\d{3})*(?:\.\d{2})|\d+\.\d{2})"
    r"(?:\s*(?P<suf>cr|dr))?",
    re.I,
)
_OFX_TRN = re.compile(
    r"<STMTTRN>(?P<body>.*?)</STMTTRN>",
    re.I | re.S,
)
_OFX_FIELD = re.compile(r"<(?P<k>[A-Z0-9.]+)>(?P<v>[^<\r\n]*)", re.I)
_NOISE_WORDS = {
    "eftpos",
    "visa",
    "debit",
    "credit",
    "purchase",
    "aus",
    "card",
    "pos",
    "withdrawal",
    "deposit",
    "payment",
    "direct",
    "transfer",
    "tfr",
    "osko",
    "payid",
    "value",
    "date",
    "transaction",
    "description",
    "details",
    "narrative",
    "amount",
    "balance",
    "debit",
    "credit",
}
_CREDIT_HINTS = (
    "salary",
    "wage",
    "payroll",
    "refund",
    "reversal",
    "interest",
    "dividend",
    "deposit",
    "employer",
)
_SKIP_HINTS = (
    "opening balance",
    "closing balance",
    "brought forward",
    "balance brought",
    "balance carried",
)


@dataclass
class RawLine:
    spent_on: dt.date
    description: str
    amount_cents: int
    credit: bool
    source: str
    raw: str = ""


@dataclass
class ProposedLine:
    fingerprint: str
    date: str
    item: str
    amount_cents: int
    amount_display: str
    credit: bool
    source: str
    raw: str
    status: str
    category: str
    clue: str
    remember: str
    reason: str
    expense_id: Optional[int] = None

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class Preview:
    month_start: Optional[dt.date]
    month_end: Optional[dt.date]
    files: List[str] = field(default_factory=list)
    lines: List[ProposedLine] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self, symbol: str = "$") -> Dict[str, object]:
        counts = {"ready": 0, "review": 0, "skip": 0, "duplicate": 0}
        for line in self.lines:
            counts[line.status] = counts.get(line.status, 0) + 1
        return {
            "month": {
                "start": format_date(self.month_start) if self.month_start else None,
                "end": format_date(self.month_end) if self.month_end else None,
                "label": self.month_start.strftime("%B %Y") if self.month_start else "all dates",
            },
            "files": self.files,
            "counts": counts,
            "lines": [line.to_dict() for line in self.lines],
            "errors": self.errors,
        }


@dataclass
class CommitResult:
    imported: int = 0
    skipped: int = 0
    remembered: int = 0
    expense_ids: List[int] = field(default_factory=list)


def default_statement_month(reference: Optional[dt.date] = None) -> Tuple[dt.date, dt.date]:
    """Previous calendar month — the 5th-of-the-month drop-off."""

    return parse_month("last", reference or today())


def parse_statement_date(value, default_year: Optional[int] = None) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = ("" if value is None else str(value)).strip()
    if not text:
        raise ParseError("A statement date is required")

    named = _DATE_NAMED.search(text)
    if named:
        year = _century(named.group("y"))
        month = _MONTH_ABBR[named.group("mon").lower()]
        return dt.date(year, month, int(named.group("d")))

    month_first = _DATE_MONTH_FIRST.search(text)
    if month_first:
        year = _century(month_first.group("y"))
        month = _MONTH_ABBR[month_first.group("mon").lower()]
        return dt.date(year, month, int(month_first.group("d")))

    numeric = _DATE_NUMERIC.search(text)
    if numeric:
        a, b, c = int(numeric.group("a")), int(numeric.group("b")), int(numeric.group("c"))
        if a >= 1000:
            return dt.date(a, b, c)
        year = _century(c)
        day, month = a, b
        if a > 12 and b <= 12:
            day, month = a, b
        elif b > 12 and a <= 12:
            day, month = b, a
        # Australian statements are day/month.
        return dt.date(year, month, day)

    short = _DATE_NAMED_SHORT.search(text)
    if short and default_year:
        month = _MONTH_ABBR[short.group("mon").lower()]
        return dt.date(int(default_year), month, int(short.group("d")))

    raise ParseError("Could not read a date from %r" % value)


def parse_statement_file(path: Path) -> List[RawLine]:
    data = Path(path).read_bytes()
    return parse_statement_bytes(data, Path(path).name)


def parse_statement_bytes(
    data: bytes, filename: str, default_year: Optional[int] = None
) -> List[RawLine]:
    name = filename or "statement"
    lower = name.lower()
    if lower.endswith((".ofx", ".qfx", ".ofc")) or b"<OFX" in data[:400] or b"<ofx" in data[:400]:
        return _parse_ofx(data, name)
    if lower.endswith(".qif") or data.lstrip().startswith(b"!Type"):
        return _parse_qif(data, name)
    if lower.endswith((".csv", ".txt")) or _looks_like_csv(data):
        lines = _parse_csv(data, name)
        if lines:
            return lines
    if looks_like_pdf(data, name):
        text = extract_pdf_text(data)
        if not text.strip():
            raise StorageError(
                "%s looks like a PDF but no text could be read. "
                "These CommBank/ANZ 'Transactions.pdf' files are often a picture. "
                "Export CSV from the bank instead (Account → Transactions → Export → CSV)."
                % name
            )
        lines = parse_statement_text(text, name, default_year)
        if lines:
            return lines
        raise StorageError(_empty_parse_message(name, text))
    text = data.decode("utf-8-sig", errors="replace")
    lines = parse_statement_text(text, name, default_year)
    if lines:
        return lines
    raise StorageError(_empty_parse_message(name, text))


def parse_statement_text(text: str, filename: str, default_year: Optional[int] = None) -> List[RawLine]:
    year = _infer_year(text, default_year)
    seen = set()
    lines: List[RawLine] = []
    for parsed in _parse_line_by_line(text, filename, year) + _parse_date_spans(
        text, filename, year
    ):
        key = (parsed.spent_on, parsed.amount_cents, _normalise(parsed.description))
        if key in seen:
            continue
        seen.add(key)
        lines.append(parsed)
    lines.sort(key=lambda row: (row.spent_on, row.description))
    return lines


def _parse_line_by_line(text: str, filename: str, year: Optional[int]) -> List[RawLine]:
    lines: List[RawLine] = []
    current_year = year
    for raw_line in text.splitlines():
        collapsed = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not collapsed:
            continue
        lower = collapsed.lower()
        if any(hint in lower for hint in _SKIP_HINTS):
            continue
        parsed = _line_from_text(collapsed, filename, current_year)
        if parsed is None:
            continue
        current_year = parsed.spent_on.year
        lines.append(parsed)
    return lines


def _parse_date_spans(text: str, filename: str, year: Optional[int]) -> List[RawLine]:
    """Pair each date with the description and amounts until the next date.

    CommBank 'Transactions.pdf' prints the date on one line, the merchant on
    the next, and the amount after that.
    """

    dates = _find_dates(text, year)
    if not dates:
        return []
    lines: List[RawLine] = []
    for index, (start, end, spent_on, raw_date) in enumerate(dates):
        block_end = dates[index + 1][0] if index + 1 < len(dates) else len(text)
        block = text[end:block_end]
        if any(hint in block.lower() for hint in _SKIP_HINTS):
            continue
        amounts = []
        for match in _AMOUNT.finditer(block):
            parsed_amount = _cents_from_match(match)
            if parsed_amount is None:
                continue
            amounts.append(parsed_amount)
        if not amounts:
            continue
        txn_cents, suffix, _ = amounts[0]
        description = _clean_description(_AMOUNT.sub(" ", block))
        description = _strip_header_noise(description)
        if not description:
            description = raw_date
        credit = suffix == "cr" or any(hint in description.lower() for hint in _CREDIT_HINTS)
        if suffix == "dr" or txn_cents < 0:
            credit = False
        lines.append(
            RawLine(
                spent_on=spent_on,
                description=description,
                amount_cents=abs(int(txn_cents)),
                credit=credit,
                source=filename,
                raw=("%s %s" % (raw_date, block)).strip(),
            )
        )
    return lines


def propose_lines(
    database: Database,
    raw_lines: Sequence[RawLine],
    start: Optional[dt.date] = None,
    end: Optional[dt.date] = None,
    symbol: str = "$",
    ignore_imported: bool = False,
) -> List[ProposedLine]:
    clues = database.list_statement_clues()
    fingerprints = [fingerprint_for(line.spent_on, line.amount_cents, line.description) for line in raw_lines]
    already = {} if ignore_imported else database.find_imported_fingerprints(fingerprints)
    proposed: List[ProposedLine] = []
    for line in raw_lines:
        if start and line.spent_on < start:
            continue
        if end and line.spent_on > end:
            continue
        mark = fingerprint_for(line.spent_on, line.amount_cents, line.description)
        item = _clean_description(line.description)
        remember = suggest_pattern(item)
        category = ""
        clue = ""
        status = "review"
        reason = "No clue matched — pick a category"

        match = _best_clue(item, clues)
        if match:
            clue = match["pattern"]
            remember = match["pattern"]
            if match["skip"] or match["category"].upper() == SKIP_CATEGORY:
                status = "skip"
                category = SKIP_CATEGORY
                reason = "Clue %r is marked skip" % match["pattern"]
            else:
                category = match["category"]
                status = "ready"
                reason = "Matched clue %r" % match["pattern"]
        elif line.credit:
            category = INCOME_CATEGORY
            status = "review"
            reason = "Looks like money in — confirm it is Income, or pick another category"

        if mark in already:
            status = "duplicate"
            reason = "Already imported from a previous statement"
            existing = already[mark]
            category = existing.get("category") or category

        amount_cents = _stored_amount(line.amount_cents, line.credit, category)
        proposed.append(
            ProposedLine(
                fingerprint=mark,
                date=format_date(line.spent_on),
                item=item or line.description,
                amount_cents=amount_cents,
                amount_display=format_amount(amount_cents, symbol),
                credit=line.credit,
                source=line.source,
                raw=line.raw,
                status=status,
                category=category,
                clue=clue,
                remember=remember,
                reason=reason,
                expense_id=already.get(mark, {}).get("expense_id") if mark in already else None,
            )
        )
    proposed.sort(key=lambda row: (row.date, row.item))
    return proposed


def preview_files(
    database: Database,
    files: Sequence[Tuple[str, bytes]],
    month: Optional[str] = "last",
    all_dates: bool = False,
    ignore_imported: bool = False,
) -> Preview:
    start = end = None
    if not all_dates:
        start, end = parse_month(month or "last")
    preview = Preview(month_start=start, month_end=end)
    raw: List[RawLine] = []
    for filename, data in files:
        preview.files.append(filename)
        try:
            parsed = parse_statement_bytes(
                data, filename, default_year=start.year if start else None
            )
        except (ParseError, StorageError, OSError, ValueError) as error:
            preview.errors.append("%s" % error)
            continue
        if not parsed:
            preview.errors.append("%s: no transactions found" % filename)
            continue
        raw.extend(parsed)
    preview.lines = propose_lines(
        database,
        raw,
        start=start,
        end=end,
        symbol=database.currency_symbol,
        ignore_imported=ignore_imported,
    )
    return preview


def commit_proposals(database: Database, items: Sequence[Dict[str, object]]) -> CommitResult:
    result = CommitResult()
    for raw in items:
        action = str(raw.get("action") or "import").strip().lower()
        fingerprint = str(raw.get("fingerprint") or "").strip()
        if not fingerprint:
            raise StorageError("Each decision needs a fingerprint")
        if database.find_imported_fingerprints([fingerprint]):
            result.skipped += 1
            continue
        remember = str(raw.get("remember") or "").strip()
        category = str(raw.get("category") or "").strip()
        if remember:
            skip = action == "skip" or category.upper() == SKIP_CATEGORY
            database.upsert_statement_clue(
                remember, "" if skip else category or "Other", skip=skip
            )
            result.remembered += 1
        if action == "skip" or category.upper() == SKIP_CATEGORY:
            database.record_statement_import(
                fingerprint=fingerprint,
                source=str(raw.get("source") or ""),
                spent_on=str(raw.get("date") or today()),
                description=str(raw.get("item") or ""),
                amount_cents=int(raw.get("amount_cents") or 0),
                category=SKIP_CATEGORY,
                expense_id=None,
            )
            result.skipped += 1
            continue
        if action != "import":
            raise StorageError("Unknown statement action %r" % action)
        if not category:
            raise StorageError("Pick a category for %s" % (raw.get("item") or fingerprint))
        date_value = parse_statement_date(raw.get("date"))
        amount = raw.get("amount_cents")
        if amount in (None, ""):
            amount = raw.get("amount")
        cents = int(amount) if isinstance(amount, int) and not isinstance(amount, bool) else parse_amount(amount)
        source = str(raw.get("source") or "").strip()
        note_parts = [str(raw.get("note") or "").strip(), ("from %s" % source) if source else ""]
        note = " · ".join(part for part in note_parts if part)
        expense = database.add_expense(
            item=str(raw.get("item") or "Statement entry"),
            amount=cents,
            category=category,
            spent_on=date_value,
            note=note,
        )
        database.record_statement_import(
            fingerprint=fingerprint,
            source=source,
            spent_on=format_date(date_value),
            description=expense.item,
            amount_cents=expense.amount_cents,
            category=expense.category,
            expense_id=expense.id,
        )
        result.imported += 1
        result.expense_ids.append(expense.id)
    return result


def suggest_pattern(description: str) -> str:
    tokens = re.findall(r"[a-z0-9&']+", (description or "").lower())
    useful = [
        token
        for token in tokens
        if token not in _NOISE_WORDS and not token.isdigit() and len(token) > 2
    ]
    if not useful:
        return ""
    return " ".join(useful[:2])


def fingerprint_for(spent_on: dt.date, amount_cents: int, description: str) -> str:
    return "%s|%d|%s" % (format_date(spent_on), int(amount_cents), _normalise(description)[:80])


def clues_csv_path() -> Optional[Path]:
    here = Path(__file__).resolve()
    for path in (here.parents[1] / "statement-clues.csv", here.parent / "statement-clues.csv"):
        if path.exists():
            return path
    return None


def load_default_clues() -> List[Tuple[str, str, bool]]:
    path = clues_csv_path()
    rows: List[Tuple[str, str, bool]] = []
    if path is None:
        return rows
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            pattern = (raw.get("pattern") or raw.get("clue") or "").strip()
            category = (raw.get("category") or raw.get("name") or "").strip()
            if not pattern:
                continue
            skip = category.upper() == SKIP_CATEGORY or str(raw.get("skip") or "").strip() in {"1", "true", "yes"}
            rows.append((pattern, "" if skip else category, skip))
    return rows


def _best_clue(description: str, clues: Sequence[Dict[str, object]]) -> Optional[Dict[str, object]]:
    hay = " %s " % _normalise(description)
    best = None
    best_len = 0
    for clue in clues:
        pattern = _normalise(str(clue.get("pattern") or ""))
        if not pattern:
            continue
        # Pad both sides so short clues like "bp" do not match inside "suburb".
        if " %s " % pattern in hay and len(pattern) > best_len:
            best = clue
            best_len = len(pattern)
    return best


def _stored_amount(amount_cents: int, credit: bool, category: str) -> int:
    cents = abs(int(amount_cents))
    if credit and (not category or category.lower() == INCOME_CATEGORY.lower()):
        return cents
    if credit:
        return -cents
    return cents


def _find_dates(text: str, default_year: Optional[int]) -> List[Tuple[int, int, dt.date, str]]:
    found: List[Tuple[int, int, dt.date, str]] = []
    for regex in (_DATE_NAMED, _DATE_MONTH_FIRST, _DATE_NUMERIC, _DATE_NAMED_SHORT):
        for match in regex.finditer(text):
            try:
                value = parse_statement_date(match.group(0), default_year)
            except (ParseError, ValueError):
                continue
            found.append((match.start(), match.end(), value, match.group(0)))
    found.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    resolved: List[Tuple[int, int, dt.date, str]] = []
    last_end = -1
    for start, end, value, raw in found:
        if start < last_end:
            continue
        resolved.append((start, end, value, raw))
        last_end = end
    return resolved


def _infer_year(text: str, default_year: Optional[int]) -> Optional[int]:
    if default_year:
        return int(default_year)
    years = re.findall(r"\b(20\d{2})\b", text or "")
    if years:
        return int(years[0])
    return today().year


def _cents_from_match(match) -> Optional[Tuple[int, str, int]]:
    sign = match.group("sign") or ""
    if sign in {"\u2212", "\u2013", "-"}:
        sign = "-"
    elif sign != "+":
        sign = ""
    try:
        cents = parse_amount(sign + match.group("num"))
    except ParseError:
        return None
    suffix = (match.group("suf") or "").strip().lower()
    return cents, suffix, match.start()


def _excerpt(text: str, limit: int = 700) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in (text or "").splitlines()]
    lines = [line for line in lines if line.strip()][:18]
    body = "\n".join(lines)
    if len(body) > limit:
        body = body[:limit].rstrip() + "…"
    return body


def _empty_parse_message(name: str, text: str) -> str:
    excerpt = _excerpt(text)
    letters = sum(1 for ch in text if ch.isalpha())
    if letters < 12:
        return (
            "%s: this PDF has no readable transaction text (likely a scan). "
            "Export CSV from the bank instead — Account → Transactions → Export → CSV."
            % name
        )
    return (
        "%s: no transactions found. Extracted text starts with:\n%s\n"
        "If that is not a transaction list, export CSV from the bank instead."
        % (name, excerpt)
    )


def _strip_header_noise(text: str) -> str:
    cleaned = re.sub(
        r"\b(date|description|debit|credit|balance|completed|pending|transactions?|"
        r"details|money out|money in|account|statement|page \d+|aud)\b",
        " ",
        text or "",
        flags=re.I,
    )
    return _clean_description(cleaned)


def _line_from_text(line: str, filename: str, default_year: Optional[int]) -> Optional[RawLine]:
    dates = _find_dates(line, default_year)
    if not dates:
        return None
    date_start, date_end, date_value, _raw_date = dates[0]

    amounts = []
    for match in _AMOUNT.finditer(line):
        if match.start() < date_end:
            continue
        parsed_amount = _cents_from_match(match)
        if parsed_amount is None:
            continue
        amounts.append(parsed_amount)
    if not amounts:
        return None

    # Last figure on a bank line is usually the running balance.
    if len(amounts) >= 2:
        txn_cents, suffix, _ = amounts[0]
        if len(amounts) >= 3:
            debit, credit_amt = amounts[0][0], amounts[1][0]
            if debit and not credit_amt:
                txn_cents, suffix = debit, amounts[0][1]
            elif credit_amt and not debit:
                txn_cents, suffix = credit_amt, amounts[1][1] or "cr"
            else:
                txn_cents, suffix = amounts[0][0], amounts[0][1]
        else:
            txn_cents, suffix, _ = amounts[0]
    else:
        txn_cents, suffix, _ = amounts[0]

    body = (line[:date_start] + " " + line[date_end:]).strip()
    body = _AMOUNT.sub(" ", body)
    description = _strip_header_noise(body)
    if not description:
        return None

    credit = suffix == "cr" or any(hint in description.lower() for hint in _CREDIT_HINTS)
    if suffix == "dr" or txn_cents < 0:
        credit = False
    return RawLine(
        spent_on=date_value,
        description=description,
        amount_cents=abs(int(txn_cents)),
        credit=credit,
        source=filename,
        raw=line,
    )


def _parse_csv(data: bytes, filename: str) -> List[RawLine]:
    text = data.decode("utf-8-sig", errors="replace")
    sample = text.lstrip()
    if not sample or sample.startswith("%PDF"):
        return []
    try:
        dialect = csv.Sniffer().sniff(sample[:4096], delimiters=",;|\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        return []
    headers = {((name or "").strip().lower()): name for name in reader.fieldnames if name}
    date_key = _first_header(headers, ("date", "transaction date", "value date", "posted", "trans date"))
    desc_key = _first_header(
        headers,
        ("description", "narrative", "details", "memo", "particulars", "transaction", "payee", "name"),
    )
    amount_key = _first_header(headers, ("amount", "transaction amount", "value", "aud"))
    debit_key = _first_header(headers, ("debit", "withdrawal", "money out", "spent"))
    credit_key = _first_header(headers, ("credit", "deposit", "money in", "received"))
    if not date_key or not (amount_key or debit_key or credit_key):
        return []

    lines: List[RawLine] = []
    for raw in reader:
        date_text = (raw.get(date_key) or "").strip()
        if not date_text:
            continue
        try:
            spent_on = parse_statement_date(date_text)
        except (ParseError, ValueError):
            continue
        description = (raw.get(desc_key) or "").strip() if desc_key else ""
        credit = False
        cents = 0
        if amount_key and (raw.get(amount_key) or "").strip():
            try:
                cents = parse_amount(raw[amount_key])
            except ParseError:
                continue
            credit = cents < 0
            cents = abs(cents)
        else:
            debit_text = (raw.get(debit_key) or "").strip() if debit_key else ""
            credit_text = (raw.get(credit_key) or "").strip() if credit_key else ""
            try:
                if debit_text:
                    cents = abs(parse_amount(debit_text))
                    credit = False
                elif credit_text:
                    cents = abs(parse_amount(credit_text))
                    credit = True
                else:
                    continue
            except ParseError:
                continue
        if not description:
            description = "Statement entry"
        lower = description.lower()
        if any(hint in lower for hint in _SKIP_HINTS):
            continue
        if any(hint in lower for hint in _CREDIT_HINTS):
            credit = True
        lines.append(
            RawLine(
                spent_on=spent_on,
                description=description,
                amount_cents=cents,
                credit=credit,
                source=filename,
                raw="%s %s" % (date_text, description),
            )
        )
    return lines


def _parse_ofx(data: bytes, filename: str) -> List[RawLine]:
    text = data.decode("latin-1", errors="replace")
    lines: List[RawLine] = []
    for match in _OFX_TRN.finditer(text):
        fields = {item.group("k").upper(): item.group("v").strip() for item in _OFX_FIELD.finditer(match.group("body"))}
        posted = fields.get("DTPOSTED") or fields.get("DTUSER") or ""
        posted = re.sub(r"[^0-9].*$", "", posted)
        if len(posted) < 8:
            continue
        try:
            spent_on = dt.date(int(posted[0:4]), int(posted[4:6]), int(posted[6:8]))
            cents = parse_amount(fields.get("TRNAMT") or "0")
        except (ParseError, ValueError):
            continue
        description = fields.get("NAME") or fields.get("MEMO") or fields.get("PAYEEID") or "Statement entry"
        if fields.get("MEMO") and fields.get("NAME") and fields["MEMO"] not in description:
            description = "%s %s" % (description, fields["MEMO"])
        credit = cents < 0 or (fields.get("TRNTYPE") or "").upper() in {"CREDIT", "DEP", "INT", "DIV"}
        # OFX amounts are signed: negative is usually a debit (money out) in bank OFX.
        trntype = (fields.get("TRNTYPE") or "").upper()
        if trntype in {"DEBIT", "CHECK", "FEE", "ATM", "POS"}:
            credit = False
        elif trntype in {"CREDIT", "DEP", "INT", "DIV", "DIRECTDEP"}:
            credit = True
        else:
            credit = cents > 0
        lines.append(
            RawLine(
                spent_on=spent_on,
                description=description,
                amount_cents=abs(cents),
                credit=credit,
                source=filename,
                raw=description,
            )
        )
    return lines


def _parse_qif(data: bytes, filename: str) -> List[RawLine]:
    text = data.decode("utf-8-sig", errors="replace")
    lines: List[RawLine] = []
    current: Dict[str, str] = {}
    for raw in text.splitlines():
        if not raw:
            continue
        code, value = raw[0], raw[1:].strip()
        if code == "^":
            line = _qif_row(current, filename)
            if line:
                lines.append(line)
            current = {}
            continue
        current[code] = value
    line = _qif_row(current, filename)
    if line:
        lines.append(line)
    return lines


def _qif_row(fields: Dict[str, str], filename: str) -> Optional[RawLine]:
    if "D" not in fields or "T" not in fields:
        return None
    try:
        spent_on = parse_statement_date(fields["D"])
        cents = parse_amount(fields["T"])
    except (ParseError, ValueError):
        return None
    description = fields.get("P") or fields.get("M") or fields.get("N") or "Statement entry"
    return RawLine(
        spent_on=spent_on,
        description=description,
        amount_cents=abs(cents),
        credit=cents < 0 or any(hint in description.lower() for hint in _CREDIT_HINTS),
        source=filename,
        raw=description,
    )


def _looks_like_csv(data: bytes) -> bool:
    sample = data.lstrip()[:200].lower()
    if sample.startswith(b"%pdf") or sample.startswith(b"ofx") or sample.startswith(b"<ofx"):
        return False
    head = sample.decode("utf-8", errors="ignore").splitlines()[:2]
    if not head:
        return False
    return "," in head[0] and any(word in head[0] for word in ("date", "description", "amount", "debit"))


def _first_header(headers: Dict[str, str], names: Iterable[str]) -> Optional[str]:
    for name in names:
        if name in headers:
            return headers[name]
    return None


def _clean_description(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "")).strip(" -|,;")
    cleaned = re.sub(r"\b(?:AUD|USD|CR|DR)\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -|,;")
    return cleaned[:200]


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _century(year) -> int:
    value = int(year)
    if value < 100:
        return 2000 + value
    return value
