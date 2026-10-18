# Contributing to LegalLens

Thanks for helping. LegalLens reads private legal documents, so two rules
come before everything else:

1. **Nothing leaves the device.** No remote API, no telemetry, no update
   checks, no CDN assets, no document text in logs. If your change adds a
   dependency or a network call, it needs the privacy check below.
2. **The model proposes, code disposes.** Anything the model says reaches the
   user only after code has checked it against the document (`verify.py`) and
   the safety rules (`safety.py`). Never bypass them, and never let output read
   as legal advice.

## Set up

```bash
git clone https://github.com/ZERODAY-2026/TH3_B0Tz.git && cd TH3_B0Tz
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                               # optional; defaults work
pytest tests/ -q                                   # no model or network needed
```

To run against the real model, follow [docs/MODEL_SETUP.md](docs/MODEL_SETUP.md)
(download the GGUF once, start `llama-server` on 127.0.0.1), then:

```bash
python smoke.py --file data/samples/rental_clear.pdf
```

## Where things live

| Area | Files | Owner lane |
|---|---|---|
| Model client, prompts, pipeline | `legallens/llm.py`, `prompts/`, `analyze.py` | A |
| Ingestion, retrieval, privacy proof | `legallens/ingest.py`, `retrieve.py`, `privacy/` | B |
| Grounding, safety, injection, priority | `legallens/verify.py`, `safety.py`, `injection.py`, `priority.py` | C |
| UI, eval, samples, docs | `app/`, `bench/`, `data/`, `docs/` | D |

`legallens/types.py` is the shared contract between lanes. Changing a field
needs agreement from every lane; adding an optional field is usually fine.

## Workflow

- Branch from `main` with your lane prefix: `a/…`, `b/…`, `c/…`, `d/…`.
- Keep pull requests small and focused; one reviewer approves; CI must be green.
- Write tests for your change. Tests must run **without** the model, network or
  GPU: use `StubGemma` (`legallens/llm.py`) for model replies.
- Bad input must never crash: return a clear, plain-language message instead
  (see how `ingest()` reports empty, damaged or scanned files).
- Never commit model weights, `.env`, credentials, or documents you did not
  write yourselves (see [docs/DATASETS.md](docs/DATASETS.md)).

## Code style

- Python 3.11+, standard library first; every new dependency needs a reason in
  the PR and a pinned version in `requirements.txt`.
- Match the surrounding code: type hints, short docstrings that say *why*,
  plain names.
- User-facing text is plain English: short sentences, no legal conclusions
  ("valid", "enforceable", "you should sign"). `safety.py` filters these, but
  don't rely on it.
- Logs carry counts, timings and error codes, never document text or questions.

## Privacy check for new dependencies or network code

```bash
python privacy/audit_deps.py --out docs/examples/privacy/dependency_audit.md
powershell -ExecutionPolicy Bypass -File privacy\monitor.ps1 -ServerLog <llama-server log>   # or ./privacy/monitor.sh
```

Review every new hit and record the verdict in
[privacy/THREAT_MODEL.md](privacy/THREAT_MODEL.md). A change that adds a
non-loopback connection at run time will not be merged.

## Adding a document type

1. Write a synthetic sample in `data/samples/` (never a real person's contract).
2. Add a hint for the type in `DOC_HINTS` (`legallens/analyze.py`) listing the
   clauses to look for.
3. If its clause numbering is unusual, extend `_MARKER_RE` in
   `legallens/ingest.py` and add a test in `tests/test_ingest.py`.
4. Add jurisdiction-dependent topics for it to `safety.py` if it has any.
5. Run the sample end to end with the real model and add the result to the
   README's results table, including any failures.
