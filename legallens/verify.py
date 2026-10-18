"""Grounding verification for LegalLens (Person C, H1-H4).

Deterministic, no model calls. The model proposes; this module disposes
(PLAN_PS2 section 3). Every Finding's quote must be verbatim-grounded in its
cited passage; every number/date in an explanation must also appear in the
quote it is attached to; every Reply's citations must be grounded the same
way; every Analysis summary sentence must carry a citation whose passage
backs its numbers.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

from .types import Analysis, Document, Finding, Reply, VerifyResult

# ----------------------------------------------------------------- normalise

_QUOTE_MAP = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-",
}
_WS_RE = re.compile(r"\s+")


def _normalize_with_map(s: str) -> tuple[str, list[int]]:
    """Unicode NFKC, unify curly quotes/dashes, collapse whitespace, casefold.

    Also returns, for every character of the normalised string, the index
    of the raw character it came from, so a span found in normalised text
    maps back to the exact source text (used for near-match repair).
    This is the single normalisation both the substring check and the
    near-match repair run against, so "exact match" and "near match" agree
    on what counts as the same text (PLAN 6.1).
    """
    out: list[str] = []
    idx: list[int] = []
    pending_space = False
    for i, ch in enumerate(s):
        piece = unicodedata.normalize("NFKC", ch)
        piece = "".join(_QUOTE_MAP.get(c, c) for c in piece).casefold()
        for c in piece:
            if c.isspace():
                pending_space = bool(out)
                continue
            if pending_space:
                out.append(" ")
                idx.append(i - 1)
                pending_space = False
            out.append(c)
            idx.append(i)
    return "".join(out), idx


def _normalize(s: str) -> str:
    return _normalize_with_map(s)[0]


# ------------------------------------------------------------- near-match

_ANCHOR_MIN = 8      # shortest shared run worth anchoring a window on
_MAX_ANCHORS = 5


def _find_best_span(normalized_quote: str, normalized_passage: str) -> tuple[float, int, int]:
    """Best SequenceMatcher ratio of the quote against any passage window
    of +/-15% its length. Returns (ratio, start, end) in the normalised
    passage's coordinates; (0.0, -1, -1) if nothing usable.

    A window scoring >= NEAR_MATCH_THRESHOLD shares nearly all of the
    quote in order, so it must contain one of the quote's long matching
    runs. Only windows aligned to those runs are scored, and quick_ratio()
    (an upper bound) skips hopeless ones -- a full sliding scan took ~30 s
    on a 1.5k-char clause for a single fabricated quote.
    """
    qlen = len(normalized_quote)
    plen = len(normalized_passage)
    if qlen == 0 or plen == 0:
        return (0.0, -1, -1)
    if plen <= qlen:
        ratio = difflib.SequenceMatcher(None, normalized_quote, normalized_passage).ratio()
        return (ratio, 0, plen)

    blocks = difflib.SequenceMatcher(
        None, normalized_quote, normalized_passage, autojunk=False
    ).get_matching_blocks()
    anchors = sorted((b for b in blocks if b.size >= _ANCHOR_MIN),
                     key=lambda b: b.size, reverse=True)[:_MAX_ANCHORS]
    if not anchors:
        return (0.0, -1, -1)

    lo_span, hi_span = max(1, int(qlen * 0.85)), int(qlen * 1.15)
    slack = qlen - lo_span
    best = (0.0, -1, -1)
    seen: set[tuple[int, int]] = set()
    sm = difflib.SequenceMatcher(None, autojunk=False)
    sm.set_seq2(normalized_quote)
    for a in anchors:
        aligned = a.b - a.a          # passage index where the quote would start
        for start in range(max(0, aligned - slack), min(plen - 1, aligned + slack) + 1):
            for span in range(lo_span, hi_span + 1):
                end = start + span
                if end > plen or (start, end) in seen:
                    continue
                seen.add((start, end))
                sm.set_seq1(normalized_passage[start:end])
                if sm.real_quick_ratio() <= best[0] or sm.quick_ratio() <= best[0]:
                    continue
                ratio = sm.ratio()
                if ratio > best[0]:
                    best = (ratio, start, end)
    return best


NEAR_MATCH_THRESHOLD = 0.95


# ------------------------------------------------------ number/date tokens

_MONTHS = ("january|february|march|april|may|june|july|august|september|"
           "october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|"
           "oct|nov|dec")
_UNIT_SINGULAR = {
    "day": "day", "days": "day",
    "month": "month", "months": "month",
    "year": "year", "years": "year",
    "week": "week", "weeks": "week",
    "hour": "hour", "hours": "hour",
}

_CURRENCY_RE = re.compile(r"rs\.?\s?([\d,]+(?:\.\d+)?)", re.IGNORECASE)
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s?%")
_UNIT_COUNT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s+(day|days|month|months|year|years|week|weeks|hour|hours)\b",
    re.IGNORECASE,
)
_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})\b")
_WRITTEN_DATE_RE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTHS})\.?\s+(\d{{4}})\b", re.IGNORECASE
)
_BARE_NUMBER_RE = re.compile(r"(?<![\d.,])\d{2,}(?:,\d{3})*(?:\.\d+)?(?![\d%])")


def _extract_tokens(text: str) -> set[tuple[str, str]]:
    """Return a set of (category, canonical_value) tokens found in text.

    Categories: 'currency', 'percent', 'count' (value carries the unit,
    normalised to singular, e.g. '30|day'), 'date'. A bare number not
    attached to a unit/currency/date pattern is also captured under
    'number' so a changed standalone amount ("Rs. 500" explained as just
    "500" elsewhere, or vice versa) is still comparable.
    """
    tokens: set[tuple[str, str]] = set()
    for m in _CURRENCY_RE.finditer(text):
        tokens.add(("currency", m.group(1).replace(",", "")))
    for m in _PERCENT_RE.finditer(text):
        tokens.add(("percent", m.group(1)))
    for m in _UNIT_COUNT_RE.finditer(text):
        unit = _UNIT_SINGULAR[m.group(2).lower()]
        tokens.add(("count", f"{m.group(1)}|{unit}"))
    for m in _NUMERIC_DATE_RE.finditer(text):
        tokens.add(("date", f"{m.group(1)}/{m.group(2)}/{m.group(3)}"))
    for m in _WRITTEN_DATE_RE.finditer(text):
        tokens.add(("date", f"{m.group(1)} {m.group(2).lower()} {m.group(3)}"))
    for m in _BARE_NUMBER_RE.finditer(text):
        tokens.add(("number", m.group(0).replace(",", "")))
    return tokens


def _numbers_consistent(plain_text: str, quote: str) -> tuple[bool, str]:
    """Every number/date/currency/percent token in plain_text must also
    appear among the quote's tokens. A 'count' token additionally fails if
    the quote has a count token with the same unit but a different value
    (the "30 days" vs "3 months" case: different unit entirely, so the
    month-count token simply has no match in the quote's token set).
    """
    plain_tokens = _extract_tokens(plain_text)
    quote_tokens = _extract_tokens(quote)
    missing = plain_tokens - quote_tokens
    # A bare 'number' token is allowed to satisfy against the numeric part
    # of a currency/count/date token sharing the same digits, so trivial
    # formatting differences (plain text drops "Rs." but keeps the figure)
    # don't false-positive.
    if missing:
        quote_values = {v.split("|")[0] for _, v in quote_tokens}
        missing = {(cat, val) for cat, val in missing
                   if not (cat == "number" and val in quote_values)}
    if missing:
        readable = ", ".join(f"{cat}:{val}" for cat, val in sorted(missing))
        return False, f"number/date mismatch: {readable} not found in quote"
    return True, ""


# ------------------------------------------------------------------ finding

def _verify_finding(f: Finding, doc: Document) -> VerifyResult:
    passage = doc.passage(f.passage_id)
    if passage is None:
        return VerifyResult(ok=False, reason=f"passage {f.passage_id!r} not found")

    norm_quote = _normalize(f.quote)
    norm_passage, raw_index = _normalize_with_map(passage.text)

    if not norm_quote:
        return VerifyResult(ok=False, reason="empty quote")

    # Numbers/dates are checked against the FULL cited passage, not just the
    # model's quoted span: a model may quote a short fragment of a clause
    # and still explain the clause around it faithfully (e.g. quoting
    # "...Rs. 500 per day" while the explanation adds "after 5 days" from
    # earlier in the same sentence). What must never happen is a number in
    # plain_text that isn't anywhere in the passage -- on either path below.
    numbers_ok, numbers_reason = _numbers_consistent(f.plain_text, passage.text)

    if norm_quote in norm_passage:
        if numbers_ok:
            return VerifyResult(ok=True)
        return VerifyResult(ok=False, reason=numbers_reason)

    ratio, start, end = _find_best_span(norm_quote, norm_passage)
    if ratio >= NEAR_MATCH_THRESHOLD and start >= 0:
        if not numbers_ok:
            # A repaired quote must not launder a distorted explanation.
            return VerifyResult(ok=False, reason=f"near match, but {numbers_reason}")
        repaired = passage.text[raw_index[start]:raw_index[end - 1] + 1].strip()
        return VerifyResult(ok=False, repaired_quote=repaired, reason="near match repaired")

    return VerifyResult(ok=False, reason="quote not found in passage")


# -------------------------------------------------------------------- reply

def _verify_reply(r: Reply, doc: Document) -> VerifyResult:
    if r.silent:
        return VerifyResult(ok=True)

    if not r.citations:
        if r.refused:
            return VerifyResult(ok=True)
        return VerifyResult(ok=False, reason="no citations to verify an answer against")

    all_passage_text = []
    for c in r.citations:
        passage = doc.passage(c.passage_id)
        if passage is None:
            return VerifyResult(ok=False, reason=f"citation passage {c.passage_id!r} not found")
        norm_quote = _normalize(c.quote)
        norm_passage = _normalize(passage.text)
        if not norm_quote or norm_quote not in norm_passage:
            ratio, _, _ = _find_best_span(norm_quote, norm_passage) if norm_quote else (0.0, -1, -1)
            if ratio < NEAR_MATCH_THRESHOLD:
                return VerifyResult(
                    ok=False,
                    reason=f"citation quote not found in passage {c.passage_id!r}",
                )
        # Number check against the full cited passage (see _verify_finding).
        all_passage_text.append(passage.text)

    ok, reason = _numbers_consistent(r.text, " ".join(all_passage_text))
    if not ok:
        return VerifyResult(ok=False, reason=reason)
    return VerifyResult(ok=True)


# ----------------------------------------------------------------- summary

# Split only when the sentence-ending punctuation is followed by a space and
# an uppercase letter or an opening bracket -- "Rs. 15,000" is not a sentence
# boundary (the next character is a digit), but "...[p1.c1]. A late fee..." is.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[])")
_CITE_RE = re.compile(r"\[(p\d+\.c\d+(?:\.\w+)?)\]")


def _verify_summary(a: Analysis, doc: Document) -> VerifyResult:
    """Per-sentence check (PLAN 6.1.6): a sentence with no citation, or whose
    numbers aren't covered by the passages it cites, is dropped -- never
    repaired. Always returns pruned_summary so the caller's "did anything
    change" check is simple, even when nothing was dropped.
    """
    if not a.summary.strip():
        return VerifyResult(ok=True, pruned_summary=a.summary)

    sentences = [s for s in _SENTENCE_SPLIT_RE.split(a.summary.strip()) if s.strip()]
    kept: list[str] = []
    dropped = 0
    for sentence in sentences:
        cited_ids = _CITE_RE.findall(sentence)
        if not cited_ids:
            dropped += 1
            continue
        cited_text = " ".join(
            doc.passage(pid).text for pid in cited_ids if doc.passage(pid) is not None
        )
        if not cited_text:
            dropped += 1
            continue
        ok, _ = _numbers_consistent(sentence, cited_text)
        if ok:
            kept.append(sentence)
        else:
            dropped += 1

    pruned = " ".join(kept)
    if dropped:
        return VerifyResult(
            ok=False,
            reason=f"{dropped} summary sentence(s) dropped (uncited or number mismatch)",
            pruned_summary=pruned,
        )
    return VerifyResult(ok=True, pruned_summary=pruned)


# -------------------------------------------------------------------- entry

def verify(item: Finding | Reply | Analysis, doc: Document) -> VerifyResult:
    """Dispatch to the right checker for whatever C's pipeline hands it."""
    if isinstance(item, Finding):
        return _verify_finding(item, doc)
    if isinstance(item, Reply):
        return _verify_reply(item, doc)
    if isinstance(item, Analysis):
        return _verify_summary(item, doc)
    raise TypeError(f"verify() does not support {type(item).__name__}")
