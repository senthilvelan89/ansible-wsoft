"""Extract readable text from a bank-statement PDF using only the stdlib.

macOS often has ``pdftotext`` (Poppler/Xpdf). When that is present we use it
because it keeps column layout. Otherwise we walk PDF content streams, inflate
FlateDecode data, and pull out ``Tj`` / ``TJ`` strings. Scanned image-only
PDFs cannot be read without extra tools; those should be exported from the
bank as CSV instead.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import zlib
from pathlib import Path
from typing import List

_STREAM_RE = re.compile(rb"stream(?:\r\n|\n|\r)(.*?)\r?\nendstream", re.DOTALL)
_LITERAL_RE = re.compile(rb"\((?:\\.|[^\\)])*\)")
_TOKEN_RE = re.compile(
    rb"("
    rb"\((?:\\.|[^\\)])*\)"  # literal string
    rb"|<[^>]*>"  # hex string
    rb"|/(?:[^\s\[\]()<>/%]+)"  # name
    rb"|\[|\]"
    rb"|BT|ET|Tj|TJ|T\*|Td|TD|Tm|'"
    rb"|[+-]?(?:\d+\.\d+|\d+\.|\.\d+|\d+)"
    rb")"
)
def extract_pdf_text(data: bytes) -> str:
    """Return layout-ish text from PDF bytes, or an empty string on failure."""

    if not data or not data.lstrip().startswith(b"%PDF"):
        return ""

    from_tool = _pdftotext(data)
    if from_tool.strip():
        return from_tool

    return _extract_from_streams(data)


def _pdftotext(data: bytes) -> str:
    binary = shutil.which("pdftotext")
    if not binary:
        return ""
    with tempfile.TemporaryDirectory(prefix="expense-pdf-") as folder:
        source = Path(folder) / "statement.pdf"
        source.write_bytes(data)
        try:
            completed = subprocess.run(
                [binary, "-layout", "-enc", "UTF-8", "-nopgbrk", str(source), "-"],
                check=False,
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if completed.returncode != 0:
            return ""
        text = completed.stdout.decode("utf-8", errors="replace")
        return text.strip() and text or ""


def _extract_from_streams(data: bytes) -> str:
    chunks: List[str] = []
    literals: List[str] = []
    for match in _STREAM_RE.finditer(data):
        payload = match.group(1)
        decoded = _inflate(payload)
        text = _strings_from_content(decoded)
        if text.strip():
            chunks.append(text)
        dumped = _all_literals(decoded)
        if dumped.strip():
            literals.append(dumped)
    joined = "\n".join(chunks).strip()
    if len(joined) >= 40:
        return joined
    fallback = "\n".join(literals).strip()
    return joined or fallback


def _all_literals(content: bytes) -> str:
    parts = []
    for match in _LITERAL_RE.finditer(content):
        piece = _decode_pdf_string(match.group(0))
        if piece.strip():
            parts.append(piece)
    return " ".join(parts)


def _inflate(payload: bytes) -> bytes:
    for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
        try:
            return zlib.decompress(payload, wbits)
        except zlib.error:
            continue
    return payload


def _strings_from_content(content: bytes) -> str:
    tokens = _TOKEN_RE.findall(content)
    parts: List[str] = []
    pending: List[bytes] = []

    def flush_array() -> str:
        texts = []
        for item in pending:
            if item.startswith(b"(") or item.startswith(b"<"):
                piece = _decode_pdf_string(item)
                if piece:
                    texts.append(piece)
        pending.clear()
        return "".join(texts)

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == b"T*":
            parts.append("\n")
        elif token in {b"Tj", b"'"}:
            if pending:
                text = flush_array()
            elif i:
                text = _decode_pdf_string(tokens[i - 1])
            else:
                text = ""
            if text:
                parts.append(text)
            if token == b"'":
                parts.append("\n")
        elif token == b"TJ":
            text = flush_array()
            if text:
                parts.append(text)
        elif token == b"[":
            pending = []
            i += 1
            while i < len(tokens) and tokens[i] != b"]":
                pending.append(tokens[i])
                i += 1
            continue
        elif token in {b"Td", b"TD"} and i >= 2:
            try:
                ty = float(tokens[i - 1])
            except ValueError:
                ty = 0.0
            if abs(ty) >= 6:
                parts.append("\n")
            elif parts and not parts[-1].endswith((" ", "\n")):
                parts.append(" ")
        elif token == b"Tm" and i >= 6:
            try:
                ty = float(tokens[i - 1])
                tx = float(tokens[i - 2])
            except ValueError:
                ty = tx = 0.0
            if abs(ty) >= 8 and parts:
                parts.append("\n")
            elif tx and parts and not parts[-1].endswith((" ", "\n")):
                parts.append(" ")
        i += 1

    text = "".join(parts)
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _decode_pdf_string(token: bytes) -> str:
    if not token:
        return ""
    if token.startswith(b"(") and token.endswith(b")"):
        return _unescape_literal(token[1:-1])
    if token.startswith(b"<") and token.endswith(b">"):
        return _decode_hex(token[1:-1])
    return ""


def _unescape_literal(raw: bytes) -> str:
    out = bytearray()
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch != 0x5C:  # backslash
            out.append(ch)
            i += 1
            continue
        i += 1
        if i >= len(raw):
            break
        nxt = raw[i]
        mapping = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}
        if nxt in mapping:
            out.append(mapping[nxt])
            i += 1
        elif nxt in {ord("("), ord(")"), ord("\\")}:
            out.append(nxt)
            i += 1
        elif 0x30 <= nxt <= 0x37:
            digits = raw[i : i + 3]
            take = 0
            value = 0
            for byte in digits:
                if 0x30 <= byte <= 0x37:
                    value = value * 8 + (byte - 0x30)
                    take += 1
                else:
                    break
            out.append(value & 0xFF)
            i += take
        else:
            out.append(nxt)
            i += 1
    return _bytes_to_text(bytes(out))


def _decode_hex(raw: bytes) -> str:
    hex_digits = re.sub(rb"[^0-9A-Fa-f]", b"", raw)
    if len(hex_digits) % 2:
        hex_digits += b"0"
    try:
        return _bytes_to_text(bytes.fromhex(hex_digits.decode("ascii")))
    except ValueError:
        return ""


def _bytes_to_text(raw: bytes) -> str:
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", errors="replace")
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le", errors="replace")
    if b"\x00" in raw[:8] and len(raw) % 2 == 0:
        return raw.decode("utf-16-be", errors="replace")
    return raw.decode("latin-1", errors="replace")


def looks_like_pdf(data: bytes, filename: str = "") -> bool:
    if data.lstrip().startswith(b"%PDF"):
        return True
    return filename.lower().endswith(".pdf")
