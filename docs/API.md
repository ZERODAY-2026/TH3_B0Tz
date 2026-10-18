# LegalLens — Module Reference

> Public API of the `legallens` package: the H0 contracts, the two entry
> points, and the client layer. Status markers show what has landed.

---

## Data types — `legallens/types.py` *(landed)*

Single source of truth; changes require all four lanes' agreement.

```python
Passage(id="p3.c2", page=3, heading="Termination" | None,
        text="...", start=1024, end=1280)          # stable, human-readable ID + char offsets

Document(doc_id, source_name, passages, extraction_warnings=[])
  .passage(passage_id) -> Passage | None

Finding(id, kind, party, plain_text, quote, passage_id, label,
        confidence="medium", flags=[], escalation_note=None)
  # kind:        obligation | right | deadline | penalty | termination | ambiguity | risk
  # label:       STATED | INTERPRETATION | CONCERN
  # flags:       ambiguous, jurisdiction_dependent, needs_professional,
  #              quote_corrected, unverified, unverified_stub, injected_text,
  #              label_downgraded, conflicting

Analysis(summary, summary_citations, findings, coverage)
  # summary_citations: passage IDs backing the summary (grounding rule 6.1.6)
  # coverage: {"found": [...], "not_found": [...], "additional": [...]}

Reply(text, citations=[Citation(passage_id, quote)], silent=False,
      refused=False, escalation_note=None)

VerifyResult(ok, reason, repaired_quote=None, pruned_summary=None)

SafeOutput(item, disclaimer, blocked_phrases=[])   # return type of apply_safety()
```

## Entry points — `legallens/analyze.py` *(landed)*

### `analyze(doc: Document, config=None, client=None) -> Analysis`

Full document analysis. Pipeline: chunk passages to context → per-group Gemma
extraction (JSON findings, schema-validated, retry max 2) → de-duplicate →
verify each finding (`verify.py`) → labels and flags (`safety.py`) → summary
from verified findings only, citations parsed → summary sentence check →
coverage report → findings ordered by severity (`priority.py`) → output
wording filter.

| Parameter | |
|---|---|
| `doc` | document from `ingest()` (tests may build one by hand) |
| `config` | `LLMConfig` or None for defaults/env |
| `client` | optional stub with `.generate(prompt, config)` for offline tests |

Malformed findings are skipped and logged. A chunk group with no valid JSON
after retries is skipped; skipped clause IDs go in `coverage["not_analysed"]`
(with `coverage["incomplete"] = True`) and a warning is appended to
`doc.extraction_warnings`. If the model stops responding mid-run the partial
result is returned the same way. Raises `LLMError` only when the model cannot
be reached at all.

### `ask(doc: Document, question: str, config=None, client=None) -> Reply`

Question answering. Order matters:

1. **Code routes first**: `classify_question()` sends verdict requests and
   off-topic questions to a deterministic refusal template. **Gemma is never
   called for these.**
2. Top-3 passages retrieved by `retrieve()` (hybrid BM25 + embeddings).
3. The `qa` prompt returns JSON with `text`, `citations`, `silent`, `refused`.
4. Reply citations go through the verifier; a failed verification collapses
   the reply to the fixed silent text, never the model's answer with citations
   stripped. A malformed reply returns `NO_ANSWER_TEXT`; a dead server raises
   `LLMError`.

Constants: `SILENT_TEXT` (the fixed "document does not appear to say…"
message) and `NO_ANSWER_TEXT`. Use them; don't retype them.

## Gemma client — `legallens/llm.py` *(landed)*

```python
generate(prompt, config=None) -> str
    # POST {base_url}/v1/chat/completions  (chat template applied — do not
    # use raw /completion; Gemma degrades without its template)

generate_json(prompt, config=None, schema_check=None, client=None) -> dict | list
    # generate + extract_json + optional schema validation; malformed output
    # retried up to config.max_retries (default 2) with the error fed back;
    # raises ValueError after exhaustion

extract_json(raw: str) -> dict | list
    # brace-scanning parser: tolerates markdown fences, stray prose and
    # top-level arrays; earliest opener ({ or [) wins

health_check(config=None) -> bool
    # GET {base_url}/health — for smoke tests with the network off

StubGemma(script=[...], responses={needle: payload})
    # deterministic offline stand-in; script = one payload per call in order,
    # responses = substring match; unmatched prompts decline (empty findings),
    # never invent

_validate_findings_payload(parsed) -> str | None
    # schema_check for the extraction prompt (kinds, labels, required keys)
```

## Configuration — `legallens/config.py` *(landed)*

```python
LLMConfig(base_url="http://127.0.0.1:8080", max_tokens=2048,
          temperature=0.1, context_window=8192, max_retries=2, timeout=120.0)
    .from_env()   # honours GEMMA_BASE_URL (must be 127.0.0.1/localhost, else
                  # ValueError) and GEMMA_TIMEOUT
load_dotenv(path=None)   # reads the gitignored .env at import; real env wins
```

Telemetry kill-switches are applied at import: `HF_HUB_OFFLINE`,
`TRANSFORMERS_OFFLINE`, `HF_HUB_DISABLE_TELEMETRY`, `DO_NOT_TRACK`.

## Prompts — `legallens/prompts/` *(landed)*

| File | Called by | Returns | Format holes |
|---|---|---|---|
| `extract.txt` | `_extract_findings` | JSON array of findings | `{doc_hint}`, `{schema}`, `{passages}` |
| `explain.txt` | explanation pass (H4–H6 work) | plain text | `{passage_id}`, `{passage_text}` |
| `summarize.txt` | `_generate_summary` | plain text with `[pX.cY]` citations | `{findings}` |
| `qa.txt` | `ask` | JSON reply object | `{passages}`, `{question}` |

All four carry the shared safety rules: untrusted-data framing, exact quotes,
no unit conversion, no legality judgments, verdict backstop.

## Interfaces provided by other lanes (import boundaries)

```python
# Lane B (legallens/ingest.py, retrieve.py)
ingest(path: str | Path) -> Document      # never raises on bad files: empty passages + extraction_warnings
document_text(doc: Document) -> str       # text that Passage.start/end index into
retrieve(doc: Document, query: str, k: int = 3) -> list[tuple[Passage, float]]
    # best first; score = relevance in [0, 1] (cosine, or BM25 relative to the best match)
clear_cache() -> None                     # drop in-memory indexes ("clear session")

# Lane C (legallens/priority.py)
severity(f: Finding) -> float             # PLAN 5.4: kind x confidence x label
tier(f: Finding) -> "critical" | "important" | "informational"
prioritise(findings) -> list[Finding]     # most severe first, unverified last

# Lane C (legallens/verify.py, safety.py, injection.py)
verify(item: Finding | Reply | Analysis, doc: Document) -> VerifyResult
classify_question(question: str) -> "explain" | "document_question" | "verdict_request" | "off_topic"
refusal_reply(question: str, kind: str) -> Reply
apply_safety(item: Analysis | Reply, doc: Document) -> SafeOutput
scan_document(doc: Document) -> list[str]   # injection pre-scan, wired into analyze()

# Lane D (planned: bench/)
load_sample(name: str) -> str
eval_set() -> list[EvalCase]
```

`analyze.py` imports each lazily. Every module has landed, so the pipeline runs
real retrieval, grounding verification, labels and flags, the injection
pre-scan and severity ordering; the fallbacks remain only so each lane stays
testable on its own. See `docs/examples/SAFETY_EXAMPLES.md` for safety test
evidence.

## CLI

```bash
python smoke.py          # offline demo: analyze + ask against StubGemma
python smoke.py --real   # same flow against a live llama-server
python smoke.py --file data/samples/rental_clear.pdf   # real file: ingest -> analyze -> 3 questions
python -m legallens.ingest FILE                       # show how a file splits into clauses
pytest tests/ -q         # deterministic suite, no model/network needed
```
