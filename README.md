# LegalLens

**A private, fully on-device legal document triage agent.**

LegalLens reads a rental, employment or service agreement **on your own machine**,
explains clauses in plain language, and flags obligations, penalties, deadlines,
termination terms and ambiguities. Every claim is tied to a quoted passage from
the document, checked by code. When the document does not say something — or the
question needs a lawyer — LegalLens says so instead of guessing. **Nothing you
upload ever leaves your device.**

> LegalLens is for preliminary document understanding and issue spotting only.
> It is **not a lawyer**, gives **no legal advice**, and never decides whether a
> clause is valid, legal or enforceable.

Built for **ZeroDay OSS Hacktoberfest 2026, IIIT Dharwad — PS2: Agentic AI,
Private Legal Document Triage Agent**.

---

## Table of contents

1. [How it works](#how-it-works)
2. [Key features](#key-features)
3. [Install](#install)
4. [Run](#run)
5. [Configuration](#configuration)
6. [Privacy guarantees](#privacy-guarantees)
7. [Testing](#testing)
7. [Troubleshooting](#troubleshooting)
8. [Project structure](#project-structure)
9. [Implementation status](#implementation-status)
10. [Limitations](#limitations)
11. [Licence and attribution](#licence-and-attribution)

---

## How it works

```
document (PDF / .txt)                     ON THE USER'S DEVICE ONLY
   │
   ▼
1. INGEST        pypdf / pdfplumber → text + page map → clause-aware chunks
   │             → passages with stable IDs (p3.c2) and char offsets
   ▼
2. INDEX         BM25 + local embeddings → local vector store
   │
   ▼
3. ANALYSE       Gemma (edge-class, 127.0.0.1 only) — document text is DATA
   │             inside delimiters, never instructions → JSON findings
   ▼
4. VERIFY        deterministic code, no model: quote ∈ passage?
   │             numbers/dates ⊆ quote?  fail → drop or mark "unverified"
   ▼
5. SAFETY        labels, ambiguity/jurisdiction flags, "document is silent",
   │             verdict refusal, escalation advice, fixed disclaimer
   ▼
6. UI            127.0.0.1 only: summary · findings · clause view with the
                 source passage beside each explanation · Q&A
```

**The design rule: the model proposes, code disposes.** Gemma reads and explains;
plain code checks every quote, every number and every refusal rule. The model
never certifies its own output. Full detail in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Key features

- **Plain-language clause explanations** — short sentences, legal terms defined
  in parentheses, numbers kept exactly as written.
- **Evidence on every claim** — each finding carries a verbatim quote and a
  passage ID; the verifier rejects any quote not found in the source.
- **STATED vs INTERPRETATION vs CONCERN** — explicit separation of what the text
  says from our reading of it.
- **Honest silence** — questions the document cannot answer get "the document
  does not appear to say anything about this", never an invented one.
- **Verdict refusal** — "is this enforceable?" / "should I sign?" are declined
  **in code, before the model is called**, with specific escalation advice.
- **Prompt-injection defence** — document text is untrusted data; injected
  instructions are flagged and ignored.
- **Verifiable privacy** — runs with the network adapter off; connection
  monitoring and a dependency audit prove nothing leaves the device
  ([docs/ARCHITECTURE.md §Privacy](docs/ARCHITECTURE.md)).

## Install

**Prerequisites:** Python 3.11+, ~6 GB free RAM for the model, ~5 GB disk for
weights.

```bash
git clone <repo-url>
cd legallens

python -m venv .venv
# Windows:  .venv\Scripts\activate
source .venv/bin/activate

pip install -r requirements.txt
```

**Model weights** (one-time, needs network — see
[docs/MODEL_SETUP.md](docs/MODEL_SETUP.md) for the full procedure and licence
steps):

```bash
mkdir models
# Gemma 4 E4B, 4-bit GGUF (~4–5 GB) — accept the licence on the model card first
huggingface-cli download <gemma-4-e4b-gguf-repo> --local-dir models
```

After this step, **no network access is ever needed again**.

## Run

```bash
# Terminal 1 — start the local model server (loopback only)
llama-server -m models/gemma-4-e4b-q4_k_m.gguf --host 127.0.0.1 --port 8080 -c 8192

# Terminal 2 — analysis pipeline smoke test (offline stubs, no server needed)
python smoke.py

# ...or with the real model:
python smoke.py --real

# Tests (deterministic; no model or network required)
pytest tests/ -q
```

The UI (Gradio on `127.0.0.1`) lands with lane D — `python -m app`.

## Configuration

Settings come from environment variables, optionally loaded from a gitignored
`.env` (see `.env.example`). Telemetry/network kill-switches are **set in code**
at import (`legallens/config.py`), not just documented:

| Variable | Default | Purpose |
|---|---|---|
| `GEMMA_BASE_URL` | `http://127.0.0.1:8080` | Local llama-server / Ollama endpoint |
| `GEMMA_TIMEOUT` | `120` | Seconds before a generation call fails |
| `HF_HUB_OFFLINE` | `1` | Never touch the Hugging Face hub at runtime |
| `TRANSFORMERS_OFFLINE` | `1` | Same for transformers |
| `DO_NOT_TRACK` | `1` | Suppress third-party telemetry |

## Privacy guarantees

1. **Cannot connect** — the full pipeline runs with networking disabled
   (adapter off / `--network none` container / WSL2 namespace).
2. **Does not try** — a connection monitor around a normal run records zero
   non-loopback connections.
3. **Has no code that connects** — `privacy/audit_deps.py` plus manual review;
   every remaining call (there are none at runtime) is listed in the threat model.

Session artifacts (chunks, embeddings, summaries) live in **one** directory with
a "clear session" control; logs carry timings and counts only, never document
text. Full policy: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Testing

```bash
pytest tests/ -q        # deterministic unit + contract tests (no model needed)
python bench/run.py     # eval: citation accuracy, verifier rate, silence/refusal (lane D)
```

Current state: **110 tests passing** — LLM client, analysis pipeline, grounding
verifier, safety layer, injection defence and ingestion (clause chunking,
header/footer stripping, malformed files).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `health_check()` false / connection refused | `llama-server` not running or wrong port — check `GEMMA_BASE_URL` |
| Model replies are garbage / ignore the prompt | You are likely on a raw `/completion` endpoint; the client uses `/v1/chat/completions` so the Gemma chat template is applied |
| `no valid JSON after 3 attempts` | Reduce prompt size (top-3 passages), lower temperature to 0.0, or check quantisation quality |
| RAM exhaustion | Drop to E2B or Q3_K_S quantisation; reduce context to 4096 (fallback ladder in [docs/MODEL_SETUP.md](docs/MODEL_SETUP.md)) |
| PDF returns no text | The PDF is a scan — out of scope; LegalLens reports "no extractable text" honestly |
| Slow Q&A (>30 s) | Retrieval keeps prompts short — confirm top-3 is wired; shorten the system prompt |

## Project structure

```
.
├── README.md                   # this file
├── PLAN_PS2.md                 # 12-hour build plan (team lanes, checkpoints)
├── requirements.txt            # pinned dependencies
├── legallens/
│   ├── types.py                # shared dataclasses (H0 contracts)
│   ├── config.py               # kill-switches, LLM settings
│   ├── llm.py                  # local Gemma client, JSON mode, retries
│   ├── analyze.py              # analyze(), ask(), chunking, summary
│   ├── prompts/                # extract / explain / summarize / qa
│   ├── ingest.py               # (B) parsing, chunking, passage IDs      [landed]
│   ├── retrieve.py             # (B) BM25 + embeddings + local store     [pending]
│   ├── verify.py               # (C) quote/number verifier               [landed]
│   ├── safety.py               # (C) labels, refusal, escalation         [landed]
│   └── injection.py            # (C) instruction-text pre-scan           [landed]
├── privacy/                    # (B) offline run, monitor, audit, threat model [pending]
├── app/                        # (D) UI, 127.0.0.1 only                  [pending]
├── bench/                      # (D) eval + speed/memory scripts         [pending]
├── tests/                      # unit + contract tests                   [landed]
├── data/samples/               # synthetic documents we wrote            [started]
└── docs/
    ├── ARCHITECTURE.md         # design, data flow, privacy architecture
    ├── MODEL_SETUP.md          # weights, licence, variant, benchmarks
    ├── DATASETS.md             # sample sources and licences
    ├── API.md                  # module reference + H0 contracts
    └── EVALUATOR_BRIEF.md      # demo/Q&A defense notes
```

## Implementation status

| Lane | Scope | Status |
|---|---|---|
| **A** — Gemma + analysis pipeline | `llm.py`, `prompts/`, `analyze.py` | **Landed** — 20 tests, offline smoke demo |
| **B** — ingest, retrieve, privacy | `ingest.py`, `retrieve.py`, `privacy/` | `ingest.py` **landed** (PDF + .txt, 20 tests); `retrieve.py` and `privacy/` pending |
| **C** — grounding + safety | `verify.py`, `safety.py`, `injection.py` | **Landed** — 58 tests (verify 20, safety 27, injection 7, pipeline integration 4) |
| **D** — UI, bench, docs, demo | `app/`, `bench/`, samples | Pending |

`analyze.py` auto-swaps to B's and C's real modules the moment they are
importable — no pipeline changes needed. With lane C landed, `analyze()` and
`ask()` now run real quote/number verification, label downgrade,
ambiguity/jurisdiction flagging and the injection pre-scan; only lane B's
`retrieve` stub remains active. Full suite: 110 tests passing
(`pytest tests/ -q`).

## Limitations

Stated honestly (criterion C7):

1. **English only**; text-based PDF and `.txt`; no OCR for scans (detected and
   reported, never guessed).
2. **Tested scope:** rental and employment agreements; service agreements if
   time allowed.
3. **Retrieval bounds Q&A:** a relevant clause ranked low yields a silent
   answer, never a wrong one — a deliberate trade.
4. **Privacy covers the software**, not a compromised OS or a malicious model
   file (scope in the threat model).
5. **No legal conclusions, ever** — validity, enforceability and "should I
   sign" are refused and escalated to a qualified professional.

## Licence and attribution

- Project code: **MIT** (see [LICENSE](LICENSE)).
- Model: Gemma — licence per its official model card; see
  [docs/MODEL_SETUP.md](docs/MODEL_SETUP.md).
- Sample documents: written by the team, safe to redistribute.
- No user documents, credentials or model weights are committed.
