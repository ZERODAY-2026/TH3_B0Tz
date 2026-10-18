"""Safety layer for LegalLens (Person C, H3-H9): labels, ambiguity and
jurisdiction flags, question routing, verdict refusal, escalation, the
forbidden-phrase filter and the fixed disclaimer.

Deterministic, no model calls (PLAN_PS2 section 6.2-6.3). Verdict and
off-topic questions are routed to a refusal template in CODE, before Gemma
is ever called, so an injected instruction inside a document cannot talk the
system into a legal conclusion (PLAN section 6.4).
"""
from __future__ import annotations

import re

from .types import Citation, Finding, Reply, SafeOutput

# --------------------------------------------------------------- constants

VAGUE_TERMS = (
    "reasonable", "unreasonable", "sole discretion", "as the owner may decide",
    "as the landlord may decide", "as the employer may decide",
    "from time to time", "as applicable", "as necessary", "at any time",
    "best efforts", "reasonable efforts", "satisfactory to",
)
_BLANK_PLACEHOLDER_RE = re.compile(r"_{3,}|\[\s*\]|\(\s*\)|\bTBD\b|\bN/?A\b", re.IGNORECASE)

JURISDICTION_TOPICS = (
    "security deposit", "deposit", "notice period", "non-compete",
    "non compete", "noncompete", "probation", "overtime", "stamp duty",
    "registration", "rent increase", "rent control",
)

FORBIDDEN_PHRASES = (
    "is illegal", "is void", "is unenforceable", "not enforceable",
    "don't sign", "do not sign", "should sign", "should not sign",
    "is enforceable", "is legal", "is valid", "clearly illegal",
    "this means you should", "you must sign", "you should not sign",
)

DISCLAIMER = (
    "LegalLens is for preliminary document understanding and issue spotting "
    "only. It is not a lawyer, gives no legal advice, and does not decide "
    "whether any clause is valid, legal or enforceable."
)

SILENT_TEXT = (
    "The document does not appear to say anything about this. "
    "You may want to ask the other party directly, or consult a "
    "qualified legal professional about this topic."
)

OFF_TOPIC_TEXT = "I can only answer questions about the document you uploaded."

_STOP_WORDS = re.compile(
    r"\b(is|this|that|the|a|an|clause|legal|enforceable|valid|void|illegal|"
    r"should|i|sign|can|they|do|does|it|of|to|for|in|on)\b"
)

# ------------------------------------------------------------ classification

_VERDICT_WORDS = r"(legal|lawful|enforceable|valid|void|illegal|unlawful|unenforceable|binding|allowed|fair)"
_VERDICT_RE = re.compile(
    rf"\b(is\s+this|is\s+it|is\s+that|are\s+these|are\s+they)\b.{{0,40}}\b{_VERDICT_WORDS}\b"
    # "Is the late fee legal?" -- the verdict word closes the question;
    # "What is the legal notice period?" (legal as an adjective) does not.
    rf"|\b(is|are|was|would|will)\b[^?]{{0,60}}\b{_VERDICT_WORDS}\s*\??\s*$"
    r"|\bshould\s+i\s+(sign|accept|agree)\b"
    r"|\bcan\s+they\s+(do\s+this|do\s+that)\b"
    r"|\bam\s+i\s+required\s+to\s+sign\b"
    r"|\b(hold|stand)\s+up\s+in\s+court\b"
    r"|\b(will|would)\s+i\s+win\b"
    r"|\bcan\s+i\s+(sue|take\s+(them|him|her)\s+to\s+court)\b",
    re.IGNORECASE,
)

_OFF_TOPIC_RE = re.compile(
    r"\bwrite\s+(me\s+)?(a\s+)?(poem|code|song|story|joke)\b"
    r"|\btell\s+me\s+a\s+joke\b"
    r"|\btranslate\s+this\b"
    r"|\bwho\s+are\s+you\b"
    r"|\bwhat('?s| is)\s+your\s+name\b"
    r"|\bwhat\s+model\s+are\s+you\b"
    r"|\bgenerate\s+(an?\s+)?(image|picture)\b"
    r"|\bwrite\s+(me\s+)?a\s+recipe\b",
    re.IGNORECASE,
)


def classify_question(question: str) -> str:
    """Route a question before the model is ever called (PLAN 6.3, 6.4).

    'verdict_request' and 'off_topic' never reach Gemma; 'document_question'
    goes through retrieval + the qa prompt, where the silence logic handles
    anything the document doesn't cover (including ordinary off-topic
    general-knowledge questions like "capital of France" -- those are
    *not* forced into the legal-escalation refusal path, only things that
    ask the assistant to do something unrelated to reading the document).
    """
    q = question.strip()
    if _VERDICT_RE.search(q):
        return "verdict_request"
    if _OFF_TOPIC_RE.search(q):
        return "off_topic"
    return "document_question"


def _extract_topic(question: str) -> str:
    topic = _STOP_WORDS.sub(" ", question.lower())
    topic = re.sub(r"[^a-z0-9 ]", " ", topic)
    topic = " ".join(topic.split())
    return topic or "this clause"


def refusal_reply(question: str, kind: str) -> Reply:
    """Deterministic refusal template (PLAN 6.3). Specific, not generic:
    names the topic the user asked about and tells them what to bring to a
    qualified professional.
    """
    if kind == "off_topic":
        return Reply(
            text=OFF_TOPIC_TEXT,
            citations=[],
            silent=False,
            refused=True,
            escalation_note=None,
        )
    topic = _extract_topic(question)
    return Reply(
        text=(
            "I cannot determine that. This depends on your jurisdiction and "
            "specific circumstances. Consider asking a qualified legal "
            f"professional about {topic}, and bring the exact clause text with you."
        ),
        citations=[],
        silent=False,
        refused=True,
        escalation_note=f"classified as {kind}; verdicts are out of scope",
    )


# -------------------------------------------------------------- label rules

_WORD_RE = re.compile(r"[a-z]{4,}")
_STOP_CONTENT_WORDS = {
    "that", "this", "with", "from", "shall", "document", "states", "state",
    "applies", "apply", "appears", "clause", "says", "says.", "under",
    "within", "which", "will", "have", "been", "either", "party", "parties",
}


def _content_words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOP_CONTENT_WORDS}


def downgrade_label(f: Finding) -> Finding:
    """Code-side downgrade (PLAN 6.2): an explanation leaning on claims not
    present in its own quote cannot stay labelled STATED. Deterministic
    content-word-overlap heuristic -- no model call, no guessing which
    specific fact is unsupported, just a conservative "is this explanation
    actually anchored in its quote" check.
    """
    if f.label != "STATED":
        return f
    quote_words = _content_words(f.quote)
    plain_words = _content_words(f.plain_text)
    if not plain_words:
        return f
    overlap = plain_words & quote_words
    ratio = len(overlap) / len(plain_words)
    if ratio < 0.3:
        f.label = "INTERPRETATION"
        if "label_downgraded" not in f.flags:
            f.flags.append("label_downgraded")
    return f


def flag_ambiguity(f: Finding) -> list[str]:
    """Vague terms, undefined terms, blank placeholders (PLAN 6.3)."""
    haystack = f"{f.quote} {f.plain_text}".lower()
    hit = any(term in haystack for term in VAGUE_TERMS) or bool(
        _BLANK_PLACEHOLDER_RE.search(f.quote)
    )
    if hit and "ambiguous" not in f.flags:
        f.flags.append("ambiguous")
    return f.flags


def flag_jurisdiction(f: Finding) -> list[str]:
    """Topics whose rules differ by state/country get flagged, never
    concluded (PLAN 6.3)."""
    haystack = f"{f.quote} {f.plain_text}".lower()
    hit = any(topic in haystack for topic in JURISDICTION_TOPICS)
    if hit:
        if "jurisdiction_dependent" not in f.flags:
            f.flags.append("jurisdiction_dependent")
        if not f.escalation_note:
            f.escalation_note = (
                "This may depend on where you are; local rules are not "
                "addressed here. Consider checking local tenancy/employment "
                "rules or asking a qualified professional."
            )
    return f.flags


def detect_conflicts(findings: list[Finding]) -> list[Finding]:
    """Flag findings of the same kind whose quotes carry a conflicting
    count token for the same topic (e.g. two different notice periods) --
    a cheap, deterministic proxy for "conflicting clauses" (PLAN 6.3).
    """
    from .verify import _extract_tokens  # local import: avoid a hard cycle at module load

    by_kind: dict[str, list[Finding]] = {}
    for f in findings:
        by_kind.setdefault(f.kind, []).append(f)

    flagged: list[Finding] = []
    for kind, group in by_kind.items():
        if len(group) < 2:
            continue
        token_sets = [
            {val for cat, val in _extract_tokens(f.quote) if cat == "count"}
            for f in group
        ]
        for i, f in enumerate(group):
            for j, other_tokens in enumerate(token_sets):
                if i == j or not token_sets[i] or not other_tokens:
                    continue
                units_i = {v.split("|")[1] for v in token_sets[i]}
                units_j = {v.split("|")[1] for v in other_tokens}
                if units_i & units_j and token_sets[i] != other_tokens:
                    if "conflicting" not in f.flags:
                        f.flags.append("conflicting")
                    flagged.append(f)
                    break
    return flagged


# -------------------------------------------------------- forbidden phrases

# "This agreement is valid for 11 months", "is legal tender", "legally
# refundable" are factual, not verdicts: phrases match on word boundaries,
# and a verdict adjective followed by a period/scope word is let through.
_FACTUAL_FOLLOW = r"(?!\s+(?:for|from|until|till|up\s+to|through|between|only|tender|notice|heir|guardian|representative|age)\b)"
_VERDICT_ADJ = ("illegal", "void", "unenforceable", "enforceable", "legal", "valid")


def _phrase_pattern(phrase: str) -> re.Pattern:
    body = r"\s+".join(re.escape(w) for w in phrase.split())
    tail = _FACTUAL_FOLLOW if phrase.split()[-1] in _VERDICT_ADJ else ""
    return re.compile(rf"(?<![\w-]){body}(?![\w-]){tail}", re.IGNORECASE)


_FORBIDDEN_RES = [(p, _phrase_pattern(p)) for p in FORBIDDEN_PHRASES]


def filter_forbidden_phrases(text: str) -> tuple[str, list[str]]:
    """Scan for verdict-style wording that must never appear in output
    (PLAN 6.3 / 16). Hits are reported for the test suite and for logging;
    the offending phrase is redacted from the returned text so a model slip
    never reaches the screen even if a caller forgets to check `hits`.
    """
    hits: list[str] = []
    out = text
    for phrase, pattern in _FORBIDDEN_RES:
        if pattern.search(out):
            hits.append(phrase)
            out = pattern.sub("[redacted]", out)
    return out, hits


# ------------------------------------------------------------- apply_safety

def apply_safety(item, doc) -> SafeOutput:
    """Final safety pass before an Analysis or Reply reaches the user
    (PLAN section 6; apply_safety in the H0 contract, PLAN_PS2 section 5.2).
    """
    from .types import Analysis  # local import avoids a cycle with types

    blocked: list[str] = []

    if isinstance(item, Analysis):
        for f in item.findings:
            downgrade_label(f)
            flag_ambiguity(f)
            flag_jurisdiction(f)
        detect_conflicts(item.findings)

        clean_summary, hits = filter_forbidden_phrases(item.summary)
        item.summary = clean_summary
        blocked.extend(hits)
        for f in item.findings:
            clean_text, hits = filter_forbidden_phrases(f.plain_text)
            f.plain_text = clean_text
            blocked.extend(hits)

    elif isinstance(item, Reply):
        clean_text, hits = filter_forbidden_phrases(item.text)
        item.text = clean_text
        blocked.extend(hits)

    else:
        raise TypeError(f"apply_safety() does not support {type(item).__name__}")

    return SafeOutput(item=item, disclaimer=DISCLAIMER, blocked_phrases=blocked)
