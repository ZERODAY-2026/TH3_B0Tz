"""Analysis pipeline for LegalLens (Person A).

Gemma extracts; code verifies. analyze() and ask() are the two entry
points D's UI and bench call. Long documents are analysed per chunk group
and merged; the summary is generated from VERIFIED findings only, with
per-sentence verification wired in (PLAN 6.1.6).
"""
from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from .config import LLMConfig
from .llm import StubGemma, _validate_findings_payload, generate, generate_json
from .types import Analysis, Citation, Document, Finding, Passage, Reply

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"

# How the model is expected to render passage references in summary text.
_CITE_RE = re.compile(r"\[(p\d+\.c\d+(?:\.\w+)?)\]")

# Fallback explain-style limits if prompts grow (H9 tuning knobs).
DOC_HINTS = {
    "rental": "rental/lease agreement; look for rent amount, deposit, notice period, "
              "maintenance responsibilities, penalties, lock-in, termination",
    "employment": "employment contract; look for salary, probation, notice period, "
                  "non-compete, confidentiality, bond/penalty, termination",
    "service": "service agreement; look for scope, payment terms, SLAs, liability, "
               "termination, penalties",
}
EXPECTED_CLAUSE_TYPES = ["obligation", "right", "deadline", "penalty", "termination"]


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")


def _doc_hint(doc: Document) -> str:
    name = (doc.source_name or "").lower()
    for key, hint in DOC_HINTS.items():
        if key in name:
            return hint
    return "general legal document; look for obligations, rights, deadlines, penalties, termination"


def _format_passages(passages: list[Passage], max_chars: int = 6000) -> str:
    """Format passages with IDs for the prompt, respecting context limits.

    Truncation is NEVER silent: a partial context passed off as complete is
    what PLAN 9 (long-document handling) forbids. If passages are dropped,
    the caller must know so it can warn or chunk instead.
    """
    parts: list[str] = []
    total = 0
    dropped = 0
    for p in passages:
        block = f"[{p.id}] (Page {p.page}){f' - {p.heading}' if p.heading else ''}\n{p.text}\n"
        if total + len(block) > max_chars:
            dropped += 1
            continue
        parts.append(block)
        total += len(block)
    if dropped:
        log.warning("context truncation: %d passage(s) dropped from prompt", dropped)
    return "\n".join(parts)


def _chunk_passages_for_context(passages: list[Passage],
                                max_chars: int = 6000) -> list[list[Passage]]:
    """Split passages into groups that fit within the context window."""
    groups: list[list[Passage]] = []
    current_group: list[Passage] = []
    current_size = 0
    for p in passages:
        p_size = len(p.text) + 50  # overhead for the [id] (Page n) line
        if current_size + p_size > max_chars and current_group:
            groups.append(current_group)
            current_group = []
            current_size = 0
        current_group.append(p)
        current_size += p_size
    if current_group:
        groups.append(current_group)
    return groups


# ---------------------------------------------------------------- extraction

def _finding_from_payload(rf: dict) -> Finding:
    return Finding(
        id=str(uuid.uuid4())[:8],
        kind=rf["kind"],
        party=rf.get("party"),
        plain_text=rf["plain_text"],
        quote=rf["quote"],
        passage_id=rf["passage_id"],
        label=rf["label"],
        confidence=rf.get("confidence", "medium"),
        flags=[],
        escalation_note=rf.get("escalation_note"),
    )


def _extract_findings(passages: list[Passage],
                      config: LLMConfig | None = None,
                      client=None) -> list[Finding]:
    """Extract findings from one group of passages using Gemma."""
    import json as _json

    prompt = _load_prompt("extract").format(
        doc_hint=_doc_hint_from_passages(passages),
        schema=_json.dumps(_FINDING_SCHEMA_SNIPPET, indent=2),
        passages=_format_passages(passages),
    )

    gen = _generator(config, client)
    if isinstance(gen, StubGemma):
        raw_findings = gen.generate(prompt, config)
        parsed = _json.loads(raw_findings) if isinstance(raw_findings, str) else raw_findings
        problem = _validate_findings_payload(parsed)
        if problem:
            raise ValueError(problem)
    else:
        parsed = generate_json(prompt, config, schema_check=_validate_findings_payload)

    if isinstance(parsed, dict):
        parsed = [parsed]
    findings = []
    for rf in parsed:
        try:
            findings.append(_finding_from_payload(rf))
        except (KeyError, ValueError) as e:
            # Skip malformed findings, never crash (and never guess a patch-up)
            log.warning("skipped malformed finding: %s", e)
    return findings


def _doc_hint_from_passages(passages: list[Passage]) -> str:
    joined = " ".join(p.text for p in passages).lower()
    for key, hint in DOC_HINTS.items():
        if key in joined:
            return hint
    # cheap sniff via common words
    if "landlord" in joined or "tenant" in joined:
        return DOC_HINTS["rental"]
    if "employer" in joined or "employee" in joined:
        return DOC_HINTS["employment"]
    return "general legal document; look for obligations, rights, deadlines, penalties, termination"


_FINDING_SCHEMA_SNIPPET = {
    "kind": "obligation | right | deadline | penalty | termination | ambiguity | risk",
    "party": "who it applies to, as written, or null",
    "plain_text": "plain-language explanation",
    "quote": "VERBATIM quote copied character by character",
    "passage_id": "e.g. p3.c2",
    "label": "STATED | INTERPRETATION | CONCERN",
    "confidence": "high | medium | low",
}


# ------------------------------------------------------------------ summary

def _generate_summary(findings: list[Finding],
                      config: LLMConfig | None = None,
                      client=None) -> tuple[str, list[str]]:
    """Generate a grounded summary from VERIFIED findings only (6.1.6)."""
    verified = [f for f in findings if "unverified" not in f.flags]
    if not verified:
        return "", []
    findings_text = "\n".join(
        f"- [{f.passage_id}] ({f.kind}, {f.label}): {f.plain_text} | Quote: \"{f.quote}\""
        for f in verified
    )
    prompt = _load_prompt("summarize").format(findings=findings_text)
    gen = _generator(config, client)
    raw = gen.generate(prompt, config) if isinstance(gen, StubGemma) else generate(prompt, config)
    raw = raw.strip()
    citations = [m.group(1) for m in _CITE_RE.finditer(raw)]
    return raw, sorted(set(citations))


# ----------------------------------------------------------------- coverage

def _compute_coverage(findings: list[Finding]) -> dict:
    found_kinds = {f.kind for f in findings if "unverified" not in f.flags}
    return {
        "found": sorted(found_kinds & set(EXPECTED_CLAUSE_TYPES)),
        "not_found": sorted(set(EXPECTED_CLAUSE_TYPES) - found_kinds),
        "additional": sorted(found_kinds - set(EXPECTED_CLAUSE_TYPES)),
    }


# ------------------------------------------------------------------ analyze

def analyze(doc: Document, config: LLMConfig | None = None, client=None) -> Analysis:
    """Full document analysis: extract -> verify -> summarise -> cover.

    Verification is C's code, called through the module boundary so the
    stub is used until C's verify.py lands (same pattern as B's retrieve).
    """
    _scan_for_injection(doc)

    groups = _chunk_passages_for_context(doc.passages)

    all_findings: list[Finding] = []
    for group in groups:
        all_findings.extend(_extract_findings(group, config, client))

    # De-duplicate across chunk-group overlaps: same passage + kind -> first
    seen: set[tuple[str, str]] = set()
    deduped: list[Finding] = []
    for f in all_findings:
        key = (f.passage_id, f.kind)
        if key not in seen:
            seen.add(key)
            deduped.append(f)

    verified = _verify_findings(deduped, doc)
    _apply_safety_labels(verified)

    summary, summary_citations = _generate_summary(verified, config, client)
    analysis = Analysis(
        summary=summary,
        summary_citations=summary_citations,
        findings=deduped,
        coverage=_compute_coverage(deduped),
    )

    # 6.1.6: verify the summary itself — failing sentences are DROPPED
    # by C's check, never repaired; we just take the pruned text back.
    sv = _verify_summary(analysis, doc)
    if sv is not None and getattr(sv, "pruned_summary", None) is not None:
        analysis.summary = sv.pruned_summary
        analysis.summary_citations = [m.group(1) for m in _CITE_RE.finditer(sv.pruned_summary)]

    return analysis


def _verify_findings(findings: list[Finding], doc: Document) -> list[Finding]:
    """Route every finding through C's verifier; fall back to a permissive
    local stub until verify.py lands (stub marked clearly, tests assert
    against the real contract)."""
    try:
        from .verify import verify as c_verify
    except ImportError:
        log.info("verify.py not landed; using permissive stub (DEV ONLY)")
        for f in findings:
            f.flags.append("unverified_stub")
        return [f for f in findings]  # keep all, flagged
    verified: list[Finding] = []
    for f in findings:
        result = c_verify(f, doc)
        if result.ok:
            verified.append(f)
        elif result.repaired_quote:
            f.quote = result.repaired_quote
            f.flags.append("quote_corrected")
            verified.append(f)
        else:
            f.flags.append("unverified")
            # keep but mark; UI hides from main list
    return verified


def _verify_summary(analysis: Analysis, doc: Document):
    try:
        from .verify import verify as c_verify
    except ImportError:
        return None
    return c_verify(analysis, doc)


def _scan_for_injection(doc: Document) -> None:
    """Pre-scan document text for instruction-like strings (C's
    injection.py, PLAN 6.4); surfaces as a warning on the Document the UI
    already knows how to show (extraction_warnings is used for exactly this
    kind of user-facing notice). No-op until injection.py lands."""
    try:
        from .injection import scan_document
    except ImportError:
        return
    for warning in scan_document(doc):
        if warning not in doc.extraction_warnings:
            doc.extraction_warnings.append(warning)


def _apply_safety_labels(findings: list[Finding]) -> None:
    """Route verified findings through C's label-downgrade and ambiguity /
    jurisdiction flagging (safety.py) before they reach the summary prompt
    or the UI. No-op until safety.py lands."""
    try:
        from .safety import detect_conflicts, downgrade_label, flag_ambiguity, flag_jurisdiction
    except ImportError:
        return
    for f in findings:
        downgrade_label(f)
        flag_ambiguity(f)
        flag_jurisdiction(f)
    detect_conflicts(findings)


# --------------------------------------------------------------------- ask

def ask(doc: Document, question: str,
        config: LLMConfig | None = None, client=None) -> Reply:
    """Answer a question about the document using retrieved passages.

    Safety routing happens in CODE before the model is ever called:
    verdict requests and off-topic questions never reach Gemma
    (PLAN 6.3 — the prompt's refusal wording is only a backstop).
    """
    kind = _classify_question_stub(question)
    if kind in ("verdict_request", "off_topic"):
        return _refusal_reply(question, kind)

    passages = _retrieve_stub(doc, question, k=3)

    prompt = _load_prompt("qa").format(
        passages=_format_passages(passages),
        question=question,
    )
    import json as _json

    gen = _generator(config, client)
    if isinstance(gen, StubGemma):
        raw = gen.generate(prompt, config)
        parsed = _json.loads(raw) if isinstance(raw, str) else raw
    else:
        parsed = generate_json(prompt, config)

    reply = Reply(
        text=str(parsed.get("text", "")),
        citations=[Citation(passage_id=c["passage_id"], quote=c["quote"])
                   for c in parsed.get("citations", []) if isinstance(c, dict)],
        silent=bool(parsed.get("silent", False)),
        refused=bool(parsed.get("refused", False)),
        escalation_note=parsed.get("escalation_note"),
    )

    # The model never certifies its own citations: verify before returning.
    # PLAN 6.1.4 — unverified citations means the fixed silent text, never
    # the model's answer with citations stripped (text may still be ungrounded).
    v = _verify_reply(reply, doc)
    if v is not None and not v.ok and not reply.silent:
        return Reply(
            text=SILENT_TEXT,
            citations=[],
            silent=True,
            refused=False,
            escalation_note="retrieved passages did not support a verifiable answer",
        )
    return reply


SILENT_TEXT = (
    "The document does not appear to say anything about this. "
    "You may want to ask the other party directly, or consult a "
    "qualified legal professional about this topic."
)


def _verify_reply(reply: Reply, doc: Document):
    try:
        from .verify import verify as c_verify
    except ImportError:
        return None
    return c_verify(reply, doc)


def _classify_question_stub(question: str) -> str:
    """Route through C's classify_question(); local fallback until it lands."""
    try:
        from .safety import classify_question
        return classify_question(question)
    except ImportError:
        pass
    q = question.lower()
    if re.search(r"\b(legal|enforceable|valid|void|illegal)\b.*\?|\bshould i sign\b", q):
        return "verdict_request"
    if re.search(r"\b(legal|enforceable|valid|void|illegal)\b", q) or "should i sign" in q:
        return "verdict_request"
    return "document_question"


def _refusal_reply(question: str, kind: str) -> Reply:
    try:
        from .safety import refusal_reply
        return refusal_reply(question, kind)
    except ImportError:
        pass
    topic = re.sub(r"[^a-z0-9 ]", " ",
                   re.sub(r"\b(is|this|that|the|clause|legal|enforceable|valid|should|i|sign)\b",
                          " ", question.lower()))
    topic = " ".join(topic.split()) or "this clause"
    return Reply(
        text=("I cannot determine that. This depends on your jurisdiction and "
              "specific circumstances. Consider asking a qualified legal "
              f"professional about {topic}, and bring the exact clause text with you."),
        citations=[],
        silent=False,
        refused=True,
        escalation_note=f"classified as {kind}; verdicts are out of scope",
    )


def _retrieve_stub(doc: Document, query: str, k: int = 3) -> list[Passage]:
    """Naive lexical fallback until B's retrieve() lands; real one replaces
    this via the same import boundary."""
    try:
        from .retrieve import retrieve as b_retrieve
        results = b_retrieve(doc, query, k=k)
        return [p for p, _ in results]
    except ImportError:
        pass
    q_terms = {w for w in re.findall(r"[a-z]{4,}", query.lower())}
    scored = sorted(
        ((len(q_terms & {w for w in re.findall(r"[a-z]{4,}", p.text.lower())}), -i, p)
         for i, p in enumerate(doc.passages)),
        reverse=True,
    )
    return [p for _, _, p in scored[:k]]


def _generator(config, client):
    """Explicit client wins; otherwise a real client (config decides)."""
    if client is not None:
        return client
    return "real"
