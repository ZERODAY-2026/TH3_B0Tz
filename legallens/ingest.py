"""Document ingestion for LegalLens (Person B, PLAN_PS2 section 9, H1-H3).

ingest(path) turns a local PDF or .txt file into a Document of clause-level
Passages with stable, human-readable IDs ("p3.c2" = page 3, clause 2). It
never raises on bad input: an empty, damaged, password-protected or scanned
file comes back as a Document with no passages and a plain-language entry in
extraction_warnings, which the UI shows as is.

Everything runs locally (pypdf, with pdfplumber as a fallback for pages
pypdf reads poorly). Logs carry counts only, never document text.

Offsets: Passage.start/end index into document_text(doc), the passages
joined by blank lines, so document_text(doc)[p.start:p.end] == p.text.
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .types import Document, Passage

log = logging.getLogger(__name__)

MAX_BYTES = 25 * 1024 * 1024      # refuse anything bigger than a long contract
MAX_PASSAGE_CHARS = 1500           # longer clauses are split at sentence ends
MIN_PASSAGE_CHARS = 25             # shorter fragments merge into a neighbour
FALLBACK_PARA_CHARS = 800          # paragraph grouping when there are no clause markers
SCANNED_CHARS_PER_PAGE = 30        # below this a page is treated as image-only
PASSAGE_SEP = "\n\n"

TEXT_SUFFIXES = {".txt", ".text"}

WARN_MISSING = "The file could not be found."
WARN_EMPTY = "This file is empty."
WARN_TOO_BIG = "This file is larger than 25 MB, which is too large for one agreement."
WARN_UNSUPPORTED = "Only PDF and .txt files are supported."
WARN_ENCRYPTED = "This PDF is password-protected. Remove the password and open it again."
WARN_DAMAGED = "This PDF is damaged and could not be read."
WARN_SCANNED = ("This PDF looks like a scanned image: it has no text LegalLens can read. "
                "Export the original as text, or open a .txt copy.")
WARN_NO_TEXT = "No readable text was found in this file."
WARN_ENCODING = ("This text file is not UTF-8. It was read as Windows-1252, "
                 "so a few characters may be wrong.")


@dataclass
class _Line:
    page: int
    text: str          # stripped; "" marks a paragraph break


# ------------------------------------------------------------------ public API

def ingest(path: str | Path) -> Document:
    """Read a local PDF or .txt file into clause-level passages."""
    p = Path(path)
    name = p.name
    if not p.is_file():
        return _empty(name, b"", [WARN_MISSING])
    data = p.read_bytes()
    if not data.strip():
        return _empty(name, data, [WARN_EMPTY])
    if len(data) > MAX_BYTES:
        return _empty(name, data, [WARN_TOO_BIG])

    warnings: list[str] = []
    suffix = p.suffix.lower()
    if suffix == ".pdf" or data[:5] == b"%PDF-":
        pages = _pdf_pages(data, warnings)
    elif suffix in TEXT_SUFFIXES:
        pages = _text_pages(data, warnings)
    else:
        return _empty(name, data, [WARN_UNSUPPORTED])

    if pages is None:                       # fatal PDF problem, warning already set
        return _empty(name, data, warnings)

    pages = [_clean_page(t) for t in pages]
    pages = _strip_running_lines(pages)
    passages = _chunk(pages)
    if not passages and not warnings:
        warnings.append(WARN_NO_TEXT)

    log.info("ingested %s: %d page(s), %d passage(s), %d warning(s)",
             suffix or "file", len(pages), len(passages), len(warnings))
    return Document(doc_id=_doc_id(data), source_name=name,
                    passages=passages, extraction_warnings=warnings)


def document_text(doc: Document) -> str:
    """The text Passage offsets refer to."""
    return PASSAGE_SEP.join(p.text for p in doc.passages)


# ------------------------------------------------------------------- readers

def _pdf_pages(data: bytes, warnings: list[str]) -> list[str] | None:
    # pypdf logs repair notes ("EOF marker not found") for damaged files; the
    # user gets one plain warning instead.
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                if not reader.decrypt(""):    # empty owner password is common
                    warnings.append(WARN_ENCRYPTED)
                    return None
            except Exception:                 # e.g. AES without the crypto extra
                warnings.append(WARN_ENCRYPTED)
                return None
        texts = []
        for page in reader.pages:
            try:
                texts.append(page.extract_text() or "")
            except Exception:
                texts.append("")
    except Exception:
        warnings.append(WARN_DAMAGED)
        return None

    weak = [i for i, t in enumerate(texts) if len(t.strip()) < SCANNED_CHARS_PER_PAGE]
    if weak:
        for i, t in _pdfplumber_pages(data, weak).items():
            if len(t.strip()) > len(texts[i].strip()):
                texts[i] = t
        weak = [i for i, t in enumerate(texts) if len(t.strip()) < SCANNED_CHARS_PER_PAGE]

    if texts and len(weak) == len(texts):
        warnings.append(WARN_SCANNED)
        return None
    blank = [i + 1 for i in weak if not texts[i].strip()]
    if blank:
        listed = ", ".join(map(str, blank[:10])) + ("…" if len(blank) > 10 else "")
        warnings.append(f"Page{'s' if len(blank) > 1 else ''} {listed} had no readable "
                        "text (possibly scanned) and were skipped.")
    return texts


def _pdfplumber_pages(data: bytes, indexes: list[int]) -> dict[int, str]:
    """Second opinion for pages pypdf read poorly (layout-heavy pages)."""
    try:
        import pdfplumber
    except ImportError:
        return {}
    out: dict[int, str] = {}
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for i in indexes:
                if i < len(pdf.pages):
                    out[i] = pdf.pages[i].extract_text() or ""
    except Exception:
        pass
    return out


def _text_pages(data: bytes, warnings: list[str]) -> list[str]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
        warnings.append(WARN_ENCODING)
    return text.split("\f")                  # form feed = explicit page break


# ------------------------------------------------------------------- cleanup

_LIGATURE_FREE = str.maketrans({" ": " ", " ": " ", " ": " ", " ": " ",
                                "​": "", "﻿": "", "­": ""})


def _clean_page(text: str) -> str:
    text = unicodedata.normalize("NFKC", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = text.translate(_LIGATURE_FREE)
    # rejoin words hyphenated across a line break: "agree-\nment" -> "agreement"
    text = re.sub(r"([a-z])-\n([a-z])", r"\1\2", text)
    return text


_PAGE_NO_RE = re.compile(r"^(?:page\s*)?[-–—(]?\s*\d{1,4}\s*[-–—)]?(?:\s*(?:of|/)\s*\d{1,4})?$", re.I)


def _strip_running_lines(pages: list[str]) -> list[str]:
    """Drop page numbers and headers/footers repeated across pages, so a
    footer like "Rental Agreement - Page 3 of 7" never splits a clause."""
    split = [p.split("\n") for p in pages]

    def edges(lines: list[str]) -> list[int]:
        idx = [i for i, l in enumerate(lines) if l.strip()]
        return idx[:2] + idx[-2:]

    def key(line: str) -> str:
        return re.sub(r"\d+", "#", line.strip().lower())

    counts: dict[str, int] = {}
    for lines in split:
        for k in {key(lines[i]) for i in edges(lines)}:
            counts[k] = counts.get(k, 0) + 1
    threshold = max(2, (len(pages) + 1) // 2)
    repeated = {k for k, n in counts.items() if n >= threshold} if len(pages) > 1 else set()

    out = []
    for lines in split:
        drop = {i for i in edges(lines)
                if _PAGE_NO_RE.match(lines[i].strip()) or key(lines[i]) in repeated}
        out.append("\n".join(l for i, l in enumerate(lines) if i not in drop))
    return out


# ------------------------------------------------------------------ chunking

# "4." "4)" "4.1" "12.3.1" "Article 4" "CLAUSE 12:" "Section IV" "Schedule A"
_MARKER_RE = re.compile(
    r"""^(?:
        (?P<word>(?:article|clause|section|schedule|annexure|annex|appendix)\s+[0-9IVXLC]+[A-Z]?)\s*[.:)\-–—]?
      | (?P<dotted>\d{1,2}(?:\.\d{1,2}){1,3})\.?
      | (?P<num>\d{1,2})[.)]
    )(?=\s|$)""", re.I | re.X)
_CAPS_HEADING_RE = re.compile(r"^[A-Z][A-Z0-9 ,&/'()\-–]{2,70}$")
_SENTENCE_END_RE = re.compile(r"(?<=[.;:!?])\s+(?=[A-Z(\"'“])")


def _lines(pages: list[str]) -> list[_Line]:
    out: list[_Line] = []
    for n, text in enumerate(pages, start=1):
        for raw in text.split("\n"):
            s = re.sub(r"\s+", " ", raw).strip()
            if s or (out and out[-1].text):
                out.append(_Line(n, s))
        if out and out[-1].text:
            out.append(_Line(n, ""))          # page end is a paragraph break
    return out


def _marker(line: str) -> tuple[bool, str | None]:
    """(starts a clause?, heading text if the line carries one)."""
    if _CAPS_HEADING_RE.match(line) and sum(c.isalpha() for c in line) >= 3:
        return True, line.title()
    m = _MARKER_RE.match(line)
    if not m:
        return False, None
    raw_rest = line[m.end():].strip()
    rest = raw_rest.strip(" .:-–—")
    # "1.5 times the rent" is a wrapped line, not clause 1.5
    if m.group("dotted") and rest and not (rest[0].isupper() or rest[0] in "(\"'“"):
        return False, None
    if rest and _looks_like_heading(rest) and not re.search(r"[.;]\s|[.;]$", raw_rest):
        return True, rest.title() if rest.isupper() else rest
    return True, None


def _looks_like_heading(s: str) -> bool:
    """'TERMINATION', 'Notice Period', 'Position and Start Date' — but not the
    wrapped first line of a sentence like 'The Landlord shall be responsible for'."""
    words = s.split()
    if not words or len(words) > 8 or len(s) > 60:
        return False
    if s.isupper():
        return True
    caps = sum(1 for w in words if w[0].isupper() or not w[0].isalpha())
    return caps / len(words) >= 0.6


def _chunk(pages: list[str]) -> list[Passage]:
    lines = _lines(pages)
    if not any(l.text for l in lines):
        return []
    marks = sum(1 for l in lines if l.text and _marker(l.text)[0])
    blocks = _clause_blocks(lines) if marks >= 2 else _paragraph_blocks(lines)
    blocks = _merge_small(blocks)
    return _to_passages(blocks)


def _clause_blocks(lines: list[_Line]) -> list[tuple[int, str | None, str]]:
    """(page, heading, text) per clause. A heading-only line ("4. TERMINATION")
    becomes the heading of the clauses under it instead of a passage."""
    blocks: list[tuple[int, str | None, str]] = []
    section: str | None = None
    pending: str | None = None          # words of a heading-only line, kept for the next clause
    cur: dict | None = None

    def flush():
        nonlocal cur, section, pending
        if cur is None:
            return
        if cur["heading_line"] and len(cur["parts"]) == 1:
            section, pending = cur["head"], cur["parts"][0]
        else:
            blocks.append((cur["page"], cur["head"], " ".join(cur["parts"])))
        cur = None

    def start(ln: _Line, head: str | None, heading_line: bool):
        nonlocal cur, pending
        parts = [pending, ln.text] if pending else [ln.text]
        pending = None
        cur = {"page": ln.page, "head": head, "parts": parts, "heading_line": heading_line}

    for ln in lines:
        if not ln.text:
            continue
        starts, heading = _marker(ln.text)
        if starts:
            flush()
            start(ln, heading or section, heading is not None)
        elif cur is None:
            start(ln, section, False)
        else:
            cur["parts"].append(ln.text)
    flush()
    if pending:
        blocks.append((lines[-1].page or 1, section, pending))
    return blocks


def _paragraph_blocks(lines: list[_Line]) -> list[tuple[int, str | None, str]]:
    """No clause numbering: group blank-line paragraphs up to ~800 chars."""
    paras: list[tuple[int, str]] = []
    page, parts = 0, []
    for ln in lines + [_Line(0, "")]:
        if ln.text:
            if not parts:
                page = ln.page
            parts.append(ln.text)
        elif parts:
            paras.append((page, " ".join(parts)))
            parts = []
    blocks: list[tuple[int, str | None, str]] = []
    for pg, text in paras:
        if blocks and len(blocks[-1][2]) + len(text) < FALLBACK_PARA_CHARS:
            blocks[-1] = (blocks[-1][0], None, blocks[-1][2] + " " + text)
        else:
            blocks.append((pg, None, text))
    return blocks


def _merge_small(blocks):
    out: list[tuple[int, str | None, str]] = []
    carry: tuple[int, str | None, str] | None = None
    for pg, head, text in blocks:
        if carry:
            pg, head, text = carry[0], carry[1] or head, carry[2] + " " + text
            carry = None
        if len(text) < MIN_PASSAGE_CHARS:
            carry = (pg, head, text)
            continue
        out.append((pg, head, text))
    if carry:
        if out:
            p0, h0, t0 = out[-1]
            out[-1] = (p0, h0, t0 + " " + carry[2])
        else:
            out.append(carry)
    return out


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_PASSAGE_CHARS:
        return [text]
    parts, cur = [], ""
    for sent in _SENTENCE_END_RE.split(text):
        if cur and len(cur) + 1 + len(sent) > MAX_PASSAGE_CHARS:
            parts.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
        while len(cur) > MAX_PASSAGE_CHARS:            # one giant sentence
            cut = cur.rfind(" ", 0, MAX_PASSAGE_CHARS) or MAX_PASSAGE_CHARS
            parts.append(cur[:cut])
            cur = cur[cut:].strip()
    if cur:
        parts.append(cur)
    return parts


def _to_passages(blocks) -> list[Passage]:
    passages: list[Passage] = []
    per_page: dict[int, int] = {}
    offset = 0
    for page, heading, text in blocks:
        per_page[page] = per_page.get(page, 0) + 1
        base = f"p{page}.c{per_page[page]}"
        for i, part in enumerate(_split_long(text)):
            pid = base if i == 0 else f"{base}.{i + 1}"
            if passages:
                offset += len(PASSAGE_SEP)
            passages.append(Passage(id=pid, page=page, heading=heading, text=part,
                                    start=offset, end=offset + len(part)))
            offset += len(part)
    return passages


def _doc_id(data: bytes) -> str:
    return "doc-" + hashlib.sha256(data).hexdigest()[:12]


def _empty(name: str, data: bytes, warnings: list[str]) -> Document:
    return Document(doc_id=_doc_id(data), source_name=name, passages=[],
                    extraction_warnings=warnings)


# ----------------------------------------------------------------------- CLI

def _main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m legallens.ingest FILE")
        return 2
    doc = ingest(argv[0])
    print(f"{doc.source_name}: {len(doc.passages)} passage(s)  [{doc.doc_id}]")
    for w in doc.extraction_warnings:
        print(f"  ! {w}")
    for p in doc.passages:
        head = f" · {p.heading}" if p.heading else ""
        print(f"  {p.id:<9} p{p.page}{head}  ({len(p.text)} chars)  {p.text[:70]}{'…' if len(p.text) > 70 else ''}")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
