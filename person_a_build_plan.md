# Person A — Build Plan: Gemma + Analysis Pipeline

> **Role:** You are the critical path. You own the local LLM client, all prompts, the analysis pipeline, Q&A, and summary generation.  
> **Files you own:** `legallens/llm.py`, `legallens/prompts/`, `legallens/analyze.py`  
> **Branch prefix:** `a/gemma-*`  
> **Load:** Heaviest — if you finish early, help C with safety wording. If you're behind, someone pairs with you.

---

## Pre-Hackathon Checklist (before H0)

- [ ] Accept the Gemma licence on [Hugging Face](https://huggingface.co/google/gemma-3n-E4B) or [Kaggle](https://www.kaggle.com/models/google/gemma)
- [ ] Download model weights (Gemma 3n E4B, 4-bit GGUF — ~4–5 GB)
- [ ] Install `llama.cpp` or `ollama` on your machine
- [ ] Verify you have ≥16 GB RAM and know your GPU/CPU specs
- [ ] Have Python 3.11+ installed

---

## H0–H1: Kickoff (with everyone)

### What you do
1. **Read** the plan (§1–§6) and participant guide pages 6–10 with the team
2. **Agree** on the types and signatures in §5 — especially `Finding`, `Analysis`, `Reply`
3. **Pick the runtime and variant:**

```
Decision matrix (fill during H0–H1):
┌─────────────────┬───────────┬───────────┬───────────────┐
│ Option          │ RAM (GB)  │ tok/sec   │ JSON reliable?│
├─────────────────┼───────────┼───────────┼───────────────┤
│ llama.cpp E4B Q4│           │           │               │
│ llama.cpp E2B Q4│           │           │               │
│ Ollama E4B      │           │           │               │
│ Ollama E2B      │           │           │               │
└─────────────────┴───────────┴───────────┴───────────────┘
Winner: ____________  Reason: ____________
```

4. **Measure** on the demo laptop: RAM at idle, RAM loaded, tokens/sec, load time
5. **Record** in `bench/results/h1_model_benchmarks.json`:

```json
{
  "model": "gemma-3n-e4b-q4_K_M",
  "runtime": "llama-server",
  "context_window": 8192,
  "ram_idle_gb": 0,
  "ram_loaded_gb": 0,
  "load_time_sec": 0,
  "tokens_per_sec": 0,
  "hardware": "CPU: ..., RAM: ... GB, GPU: ...",
  "os": "Windows 11 / Linux / macOS"
}
```

6. **Lock the decision** — no changing the model after H1.

> [!IMPORTANT]
> `.env` and model weights must be gitignored from the very first commit. Never commit weights.

---

## H1–H2: Local Gemma Client (`llm.py`)

### Goal
A prompt returns text locally with the network off.

### Build steps

**Step 1: Create `legallens/llm.py`**

```python
"""Local Gemma client — all inference stays on 127.0.0.1."""

import json
import os
import requests
from dataclasses import dataclass

# Kill-switches (also set in launch script)
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("DO_NOT_TRACK", "1")

BASE_URL = "http://127.0.0.1:8080"  # llama-server default

@dataclass
class LLMConfig:
    base_url: str = BASE_URL
    max_tokens: int = 2048
    temperature: float = 0.1     # low for deterministic JSON
    context_window: int = 8192
    max_retries: int = 2


def generate(prompt: str, config: LLMConfig = LLMConfig()) -> str:
    """Send prompt to local Gemma, return raw text response.

    Uses llama-server's OpenAI-compatible chat endpoint so the model's
    built-in Gemma chat template is applied — the raw /completion endpoint
    does NOT apply it, and Gemma without its template degrades badly.
    """
    resp = requests.post(
        f"{config.base_url}/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def generate_json(prompt: str, schema: dict, config: LLMConfig = LLMConfig()) -> dict:
    """Send prompt, parse JSON response, retry on malformed output (max 2)."""
    last_error = None
    for attempt in range(config.max_retries + 1):
        raw = generate(prompt if attempt == 0 else
                       f"{prompt}\n\n[RETRY: previous output was invalid JSON. Error: {last_error}. Return ONLY valid JSON.]",
                       config)
        # Strip markdown code fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            parsed = json.loads(cleaned)
            # TODO: validate against schema (add jsonschema validation)
            return parsed
        except json.JSONDecodeError as e:
            last_error = str(e)
            continue

    raise ValueError(f"Failed to get valid JSON after {config.max_retries + 1} attempts. Last error: {last_error}")


def health_check(config: LLMConfig = LLMConfig()) -> bool:
    """Check if the local model server is responding."""
    try:
        resp = requests.get(f"{config.base_url}/health", timeout=5)
        return resp.status_code == 200
    except requests.ConnectionError:
        return False
```

**Step 2: Smoke test (network off)**

```bash
# Terminal 1: start the server
llama-server -m ./models/gemma-3n-e4b-q4.gguf --host 127.0.0.1 --port 8080 -c 8192

# Terminal 2: test (disable network first!)
python -c "
from legallens.llm import generate, health_check
assert health_check(), 'Server not running'
result = generate('What is a lease agreement? Answer in one sentence.')
print(result)
print('✅ Smoke test passed')
"
```

**Step 3: JSON-mode smoke test**

```bash
python -c "
from legallens.llm import generate_json
result = generate_json(
    'Return a JSON object with keys: name (string), age (integer). Example person.',
    schema={'type': 'object', 'properties': {'name': {'type': 'string'}, 'age': {'type': 'integer'}}}
)
print(result)
print('✅ JSON mode works')
"
```

### ✅ Done when
- `health_check()` returns True
- `generate()` returns coherent text
- `generate_json()` returns valid parsed JSON
- All with the network adapter disabled

### Commit: `a/gemma-llm-client`

---

## H2–H4: Extraction Prompt + JSON Schema Validation

### Goal
`analyze()` returns validated `Finding` objects with quotes and passage IDs on one sample.

### Build steps

**Step 1: Create prompt templates in `legallens/prompts/`**

Create `legallens/prompts/extract.txt`:
```
You are a document analysis assistant. You read legal document passages and extract findings.

IMPORTANT RULES:
- You are NOT a lawyer. Do NOT judge validity, legality, or enforceability.
- Every finding MUST include a verbatim quote from the passage.
- Keep numbers, dates, amounts, and percentages EXACTLY as they appear in the text.
- Use short, plain-language sentences a non-lawyer can understand.
- If a legal term appears, define it briefly in parentheses.
- Pick the correct label: STATED (quote directly supports it), INTERPRETATION (needs inference), CONCERN (worth asking about).

INPUT FORMAT:
You will receive passages with IDs like [p3.c2]. Always cite the passage ID.

OUTPUT FORMAT:
Return ONLY a JSON array of findings. Each finding must match this schema exactly:
{schema}

PASSAGES:
{passages}

Return ONLY the JSON array. No other text.
```

**Step 2: Define the JSON schema for Finding**

```python
FINDING_SCHEMA = {
    "type": "object",
    "required": ["kind", "plain_text", "quote", "passage_id", "label"],
    "properties": {
        "kind": {"type": "string", "enum": ["obligation", "right", "deadline", "penalty",
                                              "termination", "ambiguity", "risk"]},
        "party": {"type": ["string", "null"]},
        "plain_text": {"type": "string"},
        "quote": {"type": "string"},
        "passage_id": {"type": "string"},
        "label": {"type": "string", "enum": ["STATED", "INTERPRETATION", "CONCERN"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]}
    }
}
```

**Step 3: Build `legallens/analyze.py` — first version**

```python
"""Analysis pipeline — Gemma extracts, code verifies."""

import json
import uuid
from pathlib import Path
from legallens.llm import generate_json, LLMConfig
from legallens.types import Document, Passage, Finding, Analysis

PROMPTS_DIR = Path(__file__).parent / "prompts"

def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text()

def _format_passages(passages: list[Passage], max_chars: int = 6000) -> str:
    """Format passages with IDs for the prompt, respecting context limits.

    Truncation is NEVER silent: a partial context passed off as complete is
    exactly what PLAN §9 (long-document handling) forbids. If passages are
    dropped, the caller must know so it can warn or chunk instead.
    """
    parts = []
    total = 0
    dropped = 0
    for p in passages:
        block = f"[{p.id}] (Page {p.page}){f' — {p.heading}' if p.heading else ''}\n{p.text}\n"
        if total + len(block) > max_chars:
            dropped += 1
            continue
        parts.append(block)
        total += len(block)
    if dropped:
        import logging
        logging.getLogger(__name__).warning(
            "context truncation: %d passage(s) dropped from prompt", dropped
        )
    return "\n".join(parts)

def _extract_findings(passages: list[Passage], config: LLMConfig = LLMConfig()) -> list[Finding]:
    """Extract findings from a group of passages using Gemma."""
    prompt_template = _load_prompt("extract")
    formatted = _format_passages(passages)
    prompt = prompt_template.format(
        schema=json.dumps(FINDING_SCHEMA, indent=2),
        passages=formatted
    )

    raw_findings = generate_json(prompt, FINDING_SCHEMA, config)

    # Ensure it's a list
    if isinstance(raw_findings, dict):
        raw_findings = [raw_findings]

    findings = []
    for rf in raw_findings:
        try:
            f = Finding(
                id=str(uuid.uuid4())[:8],
                kind=rf["kind"],
                party=rf.get("party"),
                plain_text=rf["plain_text"],
                quote=rf["quote"],
                passage_id=rf["passage_id"],
                label=rf["label"],
                confidence=rf.get("confidence", "medium"),
                flags=[],
                escalation_note=None,
            )
            findings.append(f)
        except (KeyError, ValueError) as e:
            # Log but don't crash — skip malformed findings
            print(f"⚠️ Skipped malformed finding: {e}")
            continue

    return findings

def analyze(doc: Document, config: LLMConfig = LLMConfig()) -> Analysis:
    """Full document analysis: extract → (verify handled by C) → summarise."""
    findings = _extract_findings(doc.passages, config)

    return Analysis(
        summary="",  # filled in H4–H6 after summary prompt is built
        summary_citations=[],
        findings=findings,
        coverage={},  # filled in after coverage check
    )
```

**Step 4: Test with a stubbed document**

```python
# test_analyze_stub.py
from legallens.types import Document, Passage
from legallens.analyze import analyze

stub_doc = Document(
    doc_id="test1",
    source_name="rental_clear.txt",
    passages=[
        Passage(id="p1.c1", page=1, heading="Rent",
                text='The monthly rent shall be Rs. 15,000 (Rupees Fifteen Thousand only), payable on or before the 5th of each month.',
                start=0, end=110),
        Passage(id="p1.c2", page=1, heading="Security Deposit",
                text='The Tenant shall pay a security deposit of Rs. 45,000 (Rupees Forty-Five Thousand only) at the time of signing this agreement.',
                start=111, end=230),
    ],
    extraction_warnings=[]
)

result = analyze(stub_doc)
for f in result.findings:
    print(f"[{f.kind}] {f.plain_text}")
    print(f"  Quote: \"{f.quote}\"")
    print(f"  Passage: {f.passage_id}, Label: {f.label}")
    print()
```

### ✅ Checkpoint 1 (H4)
- `analyze()` returns `Finding` objects with valid `kind`, `quote`, `passage_id`, and `label`
- JSON parsing succeeds on at least one sample
- Retry logic handles one malformed response gracefully

### Commit: `a/gemma-extraction`

---

## H4–H6: Explanation, Summary, and Label Prompts

### Goal
Explanations a non-lawyer can read. Summary with passage ID citations. Labels assigned.

### Build steps

**Step 1: Create `legallens/prompts/explain.txt`**
```
You are explaining a legal clause to someone who is NOT a lawyer.

RULES:
- Use short sentences (max 20 words each).
- If a legal term appears, define it in parentheses: e.g. "indemnity (you pay for their losses)".
- Keep ALL numbers, dates, amounts, and percentages EXACTLY as they appear.
- Do NOT say whether the clause is legal, valid, or enforceable.
- Do NOT recommend signing or not signing.

PASSAGE [{passage_id}]:
{passage_text}

Write a plain-language explanation (2–4 sentences). Return ONLY the explanation text, no JSON.
```

**Step 2: Create `legallens/prompts/summarize.txt`**
```
You are writing a brief summary of a legal document analysis.

You will receive a list of VERIFIED findings (each with a passage ID). Write a summary that:
1. Covers the most important obligations, penalties, deadlines, and termination conditions.
2. Cites passage IDs in brackets like [p2.c3] after each claim.
3. Uses short, plain sentences a non-lawyer can understand.
4. Does NOT judge legality, validity, or enforceability.
5. Keeps ALL numbers and dates EXACTLY as they appear in the findings.

VERIFIED FINDINGS:
{findings}

Write a summary of 3–6 sentences. Cite passage IDs after each claim. Return ONLY the summary text.
```

**Step 3: Create `legallens/prompts/qa.txt`**
```
You are answering a question about a legal document.

RULES:
- Answer ONLY from the passages below. Do NOT use general knowledge.
- If the passages do not contain the answer, respond with EXACTLY: "The document does not appear to say anything about this."
- Include a verbatim quote from the relevant passage.
- Cite the passage ID in brackets.
- Do NOT judge legality, validity, or enforceability.
- (Verdict questions are refused in CODE before this prompt ever runs — the next rule is only a backstop for phrasings the classifier misses.)
- If asked "is this legal/enforceable/valid?" or "should I sign?", respond with EXACTLY:
  "I cannot determine that. This depends on your jurisdiction and specific circumstances. Consider asking a qualified legal professional about [specific clause/topic]."

PASSAGES:
{passages}

QUESTION: {question}

Return a JSON object:
{{
  "text": "your answer",
  "citations": [{{"passage_id": "...", "quote": "..."}}],
  "silent": false,
  "refused": false,
  "escalation_note": null
}}
```

**Step 4: Add `ask()` to `analyze.py`**

```python
def ask(doc: Document, question: str, config: LLMConfig | None = None) -> Reply:
    """Answer a question about the document using retrieved passages.

    Safety routing happens in CODE before the model is ever called:
    verdict requests and off-topic questions never reach Gemma
    (PLAN §6.3 — the prompt's refusal wording is only a backstop).
    """
    from legallens.safety import classify_question, refusal_reply
    kind = classify_question(question)
    if kind in ("verdict_request", "off_topic"):
        return refusal_reply(question, kind)   # C's deterministic template

    from legallens.retrieve import retrieve
    results = retrieve(doc, question, k=3)
    passages = [p for p, _ in results]

    prompt_template = _load_prompt("qa")
    formatted = _format_passages(passages)
    prompt = prompt_template.format(passages=formatted, question=question)

    raw = generate_json(prompt, QA_SCHEMA, config)

    reply = Reply(
        text=raw.get("text", ""),
        citations=raw.get("citations", []),
        silent=raw.get("silent", False),
        refused=raw.get("refused", False),
        escalation_note=raw.get("escalation_note"),
    )

    # The model never certifies its own citations: verify before returning.
    # PLAN §6.1.4 — unverified citations means the fixed silent text, never
    # the model's answer with citations stripped (text may still be ungrounded).
    from legallens.verify import verify
    v = verify(reply, doc)
    if not v.ok and not reply.silent:
        return Reply(
            text="The document does not appear to say anything about this. "
                 "You may want to ask the other party directly, or consult a "
                 "qualified legal professional about this topic.",
            citations=[],
            silent=True,
            refused=False,
            escalation_note="retrieved passages did not support a verifiable answer",
        )
    return reply
```

**Step 5: Add summary generation to `analyze()`**

```python
def _generate_summary(findings: list[Finding], config: LLMConfig = LLMConfig()) -> tuple[str, list[str]]:
    """Generate a grounded summary from VERIFIED findings only."""
    prompt_template = _load_prompt("summarize")

    findings_text = "\n".join(
        f"- [{f.passage_id}] ({f.kind}, {f.label}): {f.plain_text} | Quote: \"{f.quote}\""
        for f in findings
        if "unverified" not in f.flags  # only verified findings!
    )

    prompt = prompt_template.format(findings=findings_text)
    raw = generate(prompt, config)

    # Extract passage IDs cited in the summary
    import re
    citations = re.findall(r'\[p\d+\.c\d+\]', raw)
    citations = [c.strip("[]") for c in citations]

    return raw.strip(), citations
```

**Step 6: Add coverage report**

```python
EXPECTED_CLAUSE_TYPES = ["obligation", "right", "deadline", "penalty", "termination"]

def _compute_coverage(findings: list[Finding]) -> dict:
    """Report which clause types were found and which are missing."""
    found_kinds = {f.kind for f in findings}
    return {
        "found": sorted(found_kinds & set(EXPECTED_CLAUSE_TYPES)),
        "not_found": sorted(set(EXPECTED_CLAUSE_TYPES) - found_kinds),
        "additional": sorted(found_kinds - set(EXPECTED_CLAUSE_TYPES)),
    }
```

### ✅ Checkpoint 2 (H6)
- `analyze()` produces findings + summary + coverage on rental AND employment samples
- `ask()` answers questions with citations
- Integration with B's real `ingest()` and C's `verify()` works end-to-end
- Labels (STATED/INTERPRETATION/CONCERN) are assigned

### Commit: `a/gemma-explain-summary-qa`

---

## H6–H8: Q&A, Silent Path, and Long-Document Handling

### Goal
Questions answered with verified citations. Silent case works. Long documents don't break.

### Build steps

**Step 1: Wire the silent path**

In `ask()`, after getting retrieved passages:
```python
# Check if retrieval quality is too low for a reliable answer
best_score = max((score for _, score in results), default=0)
SILENCE_THRESHOLD = 0.3  # tune this at H8

if best_score < SILENCE_THRESHOLD:
    return Reply(
        text="The document does not appear to say anything about this. "
             "You may want to ask the other party directly, or consult a "
             "qualified legal professional about this topic.",
        citations=[],
        silent=True,
        refused=False,
        escalation_note="Low retrieval confidence — the document may not cover this topic.",
    )
```

**Step 2: Long-document chunking strategy**

```python
def _chunk_passages_for_context(passages: list[Passage], max_chars: int = 6000) -> list[list[Passage]]:
    """Split passages into groups that fit within the context window."""
    groups = []
    current_group = []
    current_size = 0

    for p in passages:
        p_size = len(p.text) + 50  # overhead for formatting
        if current_size + p_size > max_chars and current_group:
            groups.append(current_group)
            current_group = []
            current_size = 0
        current_group.append(p)
        current_size += p_size

    if current_group:
        groups.append(current_group)

    return groups


def analyze(doc: Document, config: LLMConfig = LLMConfig()) -> Analysis:
    """Full analysis with long-document support."""
    groups = _chunk_passages_for_context(doc.passages)

    all_findings = []
    for group in groups:
        group_findings = _extract_findings(group, config)
        all_findings.extend(group_findings)

    # De-duplicate: same passage_id + same kind + similar quote → keep first
    seen = set()
    deduped = []
    for f in all_findings:
        key = (f.passage_id, f.kind)
        if key not in seen:
            seen.add(key)
            deduped.append(f)

    # C's verifier runs here (called by the pipeline orchestrator)
    # For now, pass all findings through

    summary, summary_citations = _generate_summary(deduped, config)
    coverage = _compute_coverage(deduped)

    return Analysis(
        summary=summary,
        summary_citations=summary_citations,
        findings=deduped,
        coverage=coverage,
    )
```

**Step 3: Integrate with C's verifier**

After `_extract_findings()`, call C's `verify()` on each finding:
```python
from legallens.verify import verify

verified_findings = []
for f in deduped:
    result = verify(f, doc)
    if result.ok:
        verified_findings.append(f)
    elif result.repaired_quote:
        f.quote = result.repaired_quote
        f.flags.append("quote_corrected")
        verified_findings.append(f)
    else:
        f.flags.append("unverified")
        # Keep but mark — don't show in main list
```

Then verify the SUMMARY itself (PLAN §6.1.6 — the summary is the most
claim-dense artifact on screen; it can never be the one unverified surface):
```python
# After _generate_summary(): run the same number/date consistency check
# over each summary sentence, against the passages in summary_citations.
# Sentences that fail are DROPPED, not repaired. C owns the check —
# you just wire it in before returning Analysis:
v = verify(analysis, doc)          # Analysis → per-sentence summary check
if not v.ok:
    analysis.summary = v.dropped_sentences_handled  # C returns the pruned text
```

### ✅ Done when
- Q&A returns verified citations for answerable questions
- "What is the pet policy?" on a doc without one → silent response
- 30+ page document finishes without truncation or crash
- Findings from different chunk groups are merged and de-duplicated

### Commit: `a/gemma-qa-longdoc`

---

## H8–H9: Prompt Tuning Against Eval Results

### Goal
Verifier rejection rate drops. Eval metrics improve.

### What to do

1. **Get D's eval results** from `bench/run.py` — look at:
   - Quote-verification rejection rate (target: <15%)
   - Number/date drift count (target: 0)
   - Label accuracy (STATED findings should genuinely be stated)
   - Meaning accuracy (human-scored: target ≥ 8/10)

2. **Common failure modes to fix in prompts:**

| Failure | Prompt fix |
|---------|------------|
| Invented quotes | Add: "Copy the quote CHARACTER BY CHARACTER from the passage. Do not paraphrase." |
| Numbers changed (30 days → 1 month) | Add: "NEVER convert units. If it says '30 days', write '30 days', not '1 month'." |
| Over-confident wording | Add: "Use 'the document states' not 'this means'. Never say 'clearly' or 'obviously'." |
| Missing passage_id | Add: "You MUST include the passage_id from the [pX.cY] tag. If unsure, use the closest one." |
| Too many STATED labels | Strengthen: "Only use STATED if the quote DIRECTLY AND FULLY supports your explanation with zero inference." |

3. **Iterate:** change prompt → re-run eval → check metrics → repeat (max 3 iterations)

4. **Record** final prompt versions and their eval scores in `bench/results/`

### Commit: `a/gemma-prompt-tuning`

---

## H9–H10.5: Bug Fixes and Speed Tuning

### Goal
No known demo-breaking bugs. Acceptable speed for the demo.

### Speed tuning checklist

- [ ] Shorten system prompts (remove redundant instructions)
- [ ] Reduce `max_tokens` where possible (extraction: 1500, explain: 300, summary: 500, qa: 500)
- [ ] Use `temperature: 0.0` for maximum determinism (instead of 0.1)
- [ ] Pre-cache the summary at upload time (don't regenerate on every view)
- [ ] For Q&A, retrieve top-3 passages (not 5) to keep prompts shorter
- [ ] Measure: target <30 seconds per Q&A response on demo laptop

### Help C with safety wording
- Review C's `safety.py` escalation templates — make sure they're specific, not generic
- Verify the output filter doesn't block legitimate findings
- Check that the disclaimer sounds professional, not robotic

### Commit: `a/gemma-polish`

---

## H10.5–H12: Code Freeze → Demo → Submit

### What you do
- **No new code.** Only fix demo-breaking bugs.
- Help D with the live demo — be ready to explain:
  - Why you chose this Gemma variant and runtime
  - How JSON extraction works and what happens on failure
  - How long-document handling works
  - Why the model proposes and code verifies (never self-certifying)
- Be ready to answer judge questions about prompt engineering decisions

---

## Quick Reference: Your Integration Points

| You need from | What | When |
|---------------|------|------|
| **B** | `ingest()` returning `Document` with `Passage` objects | H4 (use stubs until then) |
| **B** | `retrieve()` returning ranked passages | H6 (for Q&A) |
| **C** | `verify()` to check your findings | H4 (use pass-through stub until then) |
| **C** | `apply_safety()` to filter your output | H6 |
| **C** | `classify_question()` to route Q&A | H6 |
| **D** | Eval results from `bench/run.py` | H6 for first run, H8 for tuning |

| Others need from you | What | When |
|----------------------|------|------|
| **C** | `Finding` objects to verify | H4 |
| **D** | `analyze()` and `ask()` functions | H6 |
| **D** | Speed/memory numbers for README | H1, H9 |

---

## File Summary

| File | Purpose | Created at |
|------|---------|------------|
| `legallens/llm.py` | Local Gemma client, JSON mode, retries | H1–H2 |
| `legallens/prompts/extract.txt` | Finding extraction prompt | H2–H4 |
| `legallens/prompts/explain.txt` | Plain-language explanation prompt | H4–H6 |
| `legallens/prompts/summarize.txt` | Grounded summary prompt | H4–H6 |
| `legallens/prompts/qa.txt` | Q&A with citations prompt | H4–H6 |
| `legallens/analyze.py` | `analyze()`, `ask()`, long-doc merge | H2–H8 |

---

## Risk Cheat Sheet

| If this happens... | Do this |
|--------------------|---------|
| Model too slow (>60s/query) | Switch to E2B; shorten prompts; reduce passages to top-3 |
| JSON never parses reliably | Add `"Return ONLY JSON, no markdown"` to every prompt; strip ```json fences more aggressively |
| Quotes are always fabricated | Add few-shot examples in the extraction prompt showing exact quote copying |
| RAM exceeds available | Switch to a smaller quantization (Q3_K_S); reduce context to 4096 |
| Findings are too generic | Add document-type-specific hints: "For rental agreements, look for: rent amount, deposit, notice period, maintenance, penalties..." |
| Summary has ungrounded claims | Feed ONLY verified findings to the summary prompt (never raw passages) |
