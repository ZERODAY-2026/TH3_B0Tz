# LegalLens

**A private, fully on-device legal document triage agent.**

LegalLens reads a rental or employment agreement **on your own machine**,
explains its clauses in plain language, and flags obligations, rights,
penalties, deadlines, termination terms and ambiguities. Every claim is tied to
a quoted passage from the document and checked by code. When the document does
not say something, or the question needs a lawyer, LegalLens says so instead of
guessing. **Nothing you open ever leaves your device.**

> LegalLens is for preliminary document understanding and issue spotting only.
> It is **not a lawyer**, gives **no legal advice**, and never decides whether a
> clause is valid, legal or enforceable.

Built for **ZeroDay OSS Hacktoberfest 2026, IIIT Dharwad — PS2: Agentic AI,
Private Legal Document Triage Agent** by team TH3_B0Tz.

---

## Table of contents

1. [How it works](#how-it-works)
2. [Key features](#key-features)
3. [Install](#install)
4. [Run](#run)
5. [Configuration](#configuration)
6. [Privacy guarantees](#privacy-guarantees)
7. [Results](#results)
8. [Testing](#testing)
9. [Troubleshooting](#troubleshooting)
10. [Project structure](#project-structure)
11. [Implementation status](#implementation-status)
12. [Limitations](#limitations)
13. [Main technical contribution](#main-technical-contribution)
14. [Contributing](#contributing)
15. [Licence and attribution](#licence-and-attribution)

---

## How it works

```
document (PDF / .txt)                     ON THE USER'S DEVICE ONLY
   │
   ▼
1. INGEST        pypdf (+ pdfplumber fallback) → headers/footers stripped →
   │             clause-aware chunks with stable IDs (p3.c2) and headings
   ▼
2. ANALYSE       Gemma 4 E4B via llama-server on 127.0.0.1 — document text is
   │             DATA inside delimiters, never instructions → JSON findings
   ▼
3. VERIFY        deterministic code, no model: quote ∈ cited passage?
   │             numbers/dates in the explanation ⊆ quote?  fail → dropped or
   │             marked "unverified"; the summary is checked sentence by sentence
   ▼
4. SAFETY        labels (stated / our reading / concern), ambiguity and
   │             jurisdiction flags, verdict refusal in code, escalation notes,
   │             forbidden-wording filter, severity ordering
   ▼
5. ASK           hybrid retrieval (BM25 + MiniLM embeddings in a FAISS index,
                 in memory) → top-3 clauses → Gemma → citations verified →
                 cited answer, "the document doesn't say", or a refusal
```

**The design rule: the model proposes, code disposes.** Gemma reads and explains;
plain code checks every quote, every number and every refusal rule. The model
never certifies its own output. Full detail in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Key features

- **Plain-language clause explanations**: short sentences, legal terms defined
  in brackets, numbers kept exactly as written.
- **Evidence on every claim**: each finding carries a verbatim quote and a
  clause ID; the verifier rejects any quote not found in the source and any
  explanation whose numbers or dates differ from it.
- **Stated vs our reading vs concern**: what the text says is kept apart from
  interpretation.
- **Honest silence**: a question the document cannot answer gets "the document
  does not appear to say anything about this", never an invented answer.
- **Verdict refusal**: "is this enforceable?" and "should I sign?" are declined
  **in code, before the model is called**, with specific advice on what to ask a
  lawyer.
- **Most important first**: findings are ordered by a code-computed severity.
- **Prompt-injection defence**: instructions hidden in a document are flagged
  to the user and ignored.
- **Robust input**: empty, damaged, password-protected and scanned files get a
  clear message, never a crash.
- **Verifiable privacy**: a network guard, connection monitoring, a canary leak
  check and a dependency audit, with recorded evidence.

## Install

**Prerequisites:** Python 3.11+; llama.cpp (`llama-server`); about 6 GB of disk
for the models. A GPU is optional: on an RTX 4060 (8 GB) the whole model runs on
the GPU, and on a CPU it still works, only slower.

```bash
git clone https://github.com/ZERODAY-2026/TH3_B0Tz.git
cd TH3_B0Tz

python -m venv .venv
# Windows:  .venv\Scripts\activate
source .venv/bin/activate

pip install -r requirements.txt
```

**Models** (one time, needs the network; full procedure, licences and SHA-256
checks in [docs/MODEL_SETUP.md](docs/MODEL_SETUP.md)):

```bash
# Gemma 4 E4B, 4-bit GGUF (4.98 GB)
python -c "from huggingface_hub import hf_hub_download as d; d('unsloth/gemma-4-E4B-it-GGUF', 'gemma-4-E4B-it-Q4_K_M.gguf', local_dir='models')"
# Embedding model for retrieval (91 MB), pinned to a commit
python -c "from huggingface_hub import hf_hub_download as d; [d('sentence-transformers/all-MiniLM-L6-v2', f, revision='1110a243fdf4706b3f48f1d95db1a4f5529b4d41', local_dir='models/all-MiniLM-L6-v2') for f in ('onnx/model.onnx', 'tokenizer.json')]"
```

After this step, **no network access is needed again**.

## Run

```bash
# Terminal 1 — the local model server (loopback only).
# -ngl 99 puts every layer on the GPU (RTX 4060: fits); drop it on CPU-only machines.
llama-server -m models/gemma-4-E4B-it-Q4_K_M.gguf --host 127.0.0.1 --port 8080 -c 8192 -ngl 99 --jinja --chat-template-kwargs "{\"enable_thinking\":false}"

# Terminal 2 — a real document, end to end (ingest → analyse → three questions)
python smoke.py --file data/samples/rental_clear.pdf

# Inspect how a file is split into clauses
python -m legallens.ingest data/samples/employment_standard.txt

# Offline demo with a scripted model (no server needed)
python smoke.py
```

On a CPU-only machine set `GEMMA_TIMEOUT=900`. The UI (Gradio on `127.0.0.1`,
lane D) is in progress; the design mockup is in `app/mockup/`.

**To reproduce the demonstration:** run the two terminals above on
`data/samples/rental_clear.pdf`, then the privacy checks in
[Privacy guarantees](#privacy-guarantees). The expected output is in
[docs/examples/real_run_rental_clear.txt](docs/examples/real_run_rental_clear.txt).

## Configuration

Settings come from environment variables, optionally from a gitignored `.env`
(copy [.env.example](.env.example)); real environment variables win. Kill-switches
are **set in code** at import (`legallens/config.py`), not just documented.

| Variable | Default | Purpose |
|---|---|---|
| `GEMMA_BASE_URL` | `http://127.0.0.1:8080` | Local llama-server or Ollama. **Refused** unless it is 127.0.0.1 or localhost, since document text is sent there |
| `GEMMA_TIMEOUT` | `120` | Seconds per model reply; use `900` on CPU |
| `LEGALLENS_EMBED_MODEL_DIR` | `models/all-MiniLM-L6-v2` | Embedding model; without it retrieval uses BM25 alone |
| `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, `HF_HUB_DISABLE_TELEMETRY`, `DO_NOT_TRACK` | `1` | Never touch the Hugging Face hub or send telemetry at run time |

## Privacy guarantees

Three independent layers, all scripted in `privacy/` and explained in
[privacy/THREAT_MODEL.md](privacy/THREAT_MODEL.md):

| Layer | Tool | Status |
|---|---|---|
| 1. **Cannot connect**: full run with the machine offline | `privacy/run_offline.ps1` (Windows, Airplane mode) / `run_offline.sh` (Linux network namespace) | To record on the demo laptop |
| 2. **Does not try**: every connection attempt watched during a full run (ingest, analysis, retrieval, three questions) | `privacy/monitor.ps1` / `monitor.sh` + in-process audit-hook guard (`privacy/netguard.py`) | **PASS**: 12 attempts, all to 127.0.0.1:8080; 0 non-loopback; canary text found in no file ([evidence](docs/examples/privacy/run-monitored/)) |
| 3. **Has no code that connects**: audit of our code and every runtime dependency, marking code actually loaded in a real session | `privacy/audit_deps.py` | **Clean**: only `llm.py` talks to the local model; 4 dormant numpy hits ([report](docs/examples/privacy/dependency_audit.md)) |

The only run-time network traffic is LegalLens → `127.0.0.1:8080` (the local
model). Embeddings and the retrieval index stay in memory. Logs carry timings
and counts only, never document text.

```bash
python privacy/audit_deps.py --out docs/examples/privacy/dependency_audit.md
powershell -ExecutionPolicy Bypass -File privacy\monitor.ps1 -ServerLog <llama-server log>
powershell -ExecutionPolicy Bypass -File privacy\run_offline.ps1 -ServerLog <llama-server log>   # Airplane mode on
```

## Results

Measured on our own synthetic documents; full evaluation on unseen documents is
still to come (see [Implementation status](#implementation-status)).

| What | Result | Evidence |
|---|---|---|
| Findings on `rental_clear.pdf` (17 clauses), real Gemma | 11 findings, **11/11 passed quote and number verification**; the vague "amounts the Landlord considers reasonable" clause flagged | [real_run_rental_clear.txt](docs/examples/real_run_rental_clear.txt) |
| Questions on the same file | answerable question cited correctly; "Can I keep a pet?" → *not in the document*; "Is the late fee enforceable?" → refused with escalation | same |
| Retrieval, 15 handwritten questions over both sample contracts | right clause in the **top 3 for 15/15**, at rank 1 for 13/15 | `tests/test_retrieve.py` |
| Malformed input (empty, damaged, password-protected, scanned) | 4/4 give one clear message, no crash | `tests/test_ingest.py` |
| Privacy, monitored run | PASS (see above) | [run-monitored/](docs/examples/privacy/run-monitored/) |
| Speed, dev laptop (CPU only, ~5 tok/s) | full analysis 110–265 s; ~15–30 s per question; retrieval ~4 ms | [MODEL_SETUP.md §5](docs/MODEL_SETUP.md) |
| Speed, demo laptop (RTX 4060, 8 GB) | to measure | — |

## Testing

```bash
pytest tests/ -q        # 137 deterministic tests: no model, GPU or network needed
```

CI runs the tests, the offline smoke demo and the dependency audit on Ubuntu and
Windows with Python 3.11 and 3.13 (`.github/workflows/ci.yml`). Coverage:
LLM client and retries, analysis pipeline and failure handling, grounding
verifier, safety layer, injection defence, severity ordering, ingestion
(clause chunking, header/footer stripping, malformed files), hybrid retrieval
(with and without the embedding model), and the privacy guard and audit.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `LLMError: local model ... failed` | `llama-server` isn't running on the configured port, or the reply took longer than `GEMMA_TIMEOUT` (raise it on CPU) |
| Empty answers from the model | Gemma 4 is "thinking": start `llama-server` with `--jinja --chat-template-kwargs '{"enable_thinking":false}'` (the client also sends this per request) |
| `GEMMA_BASE_URL must point at this machine` | By design: document text may only go to 127.0.0.1/localhost |
| "This PDF looks like a scanned image" | The PDF has no text layer; export the original as text or open a .txt copy (no OCR) |
| "Part of this document could not be analysed" | The model returned invalid output for some clauses; results are marked incomplete rather than guessed. Retry, or use a higher-quality quantisation |
| Paraphrased questions find the wrong clause | The embedding model is missing, so retrieval uses BM25 alone; download it (see Install) |
| Out of memory | Drop to Q3_K_S or E2B, or reduce `-c` to 4096 ([fallback ladder](docs/MODEL_SETUP.md)) |
| `winget` llama.cpp hangs at start-up | That build uses Vulkan; on NVIDIA GPUs use the CUDA release build |

## Project structure

```
.
├── README.md, CONTRIBUTING.md, LICENSE, .env.example, requirements.txt
├── PLAN_PS2.md                 # build plan: lanes, checkpoints, scoring map
├── smoke.py                    # end-to-end demo (scripted or real model, any file)
├── legallens/
│   ├── types.py                # shared dataclasses (the contract between lanes)
│   ├── config.py               # .env loading, kill-switches, loopback-only model URL
│   ├── llm.py                  # local Gemma client: JSON mode, retries, clear errors
│   ├── analyze.py              # analyze(), ask(): extract → verify → safety → summary
│   ├── prompts/                # extract / explain / summarize / qa
│   ├── ingest.py               # PDF/.txt → clause passages with stable IDs
│   ├── retrieve.py             # BM25 + MiniLM (ONNX) + FAISS, in memory
│   ├── verify.py               # quote, number and date verification
│   ├── safety.py               # labels, flags, refusal, escalation, wording filter
│   ├── injection.py            # instruction-text pre-scan
│   └── priority.py             # severity score and ordering
├── privacy/                    # network guard, monitors, offline runs, audit, threat model
├── data/samples/               # synthetic documents we wrote + malformed fixtures
├── tests/                      # 137 deterministic tests
├── app/mockup/                 # UI design mockup (Gradio app: lane D, in progress)
└── docs/
    ├── ARCHITECTURE.md         # design, data flow, privacy architecture
    ├── MODEL_SETUP.md          # models, licences, SHA-256s, GPU/CPU set-up, benchmarks
    ├── DATASETS.md             # sample sources and licences
    ├── API.md                  # module reference
    ├── EVALUATOR_BRIEF.md      # pitch and judge Q&A
    └── examples/               # real-run log, safety examples, privacy evidence
```

## Implementation status

| Lane | Scope | Status |
|---|---|---|
| **A**: Gemma + analysis | `llm.py`, `prompts/`, `analyze.py` | **Done**: real-model runs verified; graceful handling of bad JSON, timeouts and a dead server |
| **B**: ingest, retrieval, privacy | `ingest.py`, `retrieve.py`, `privacy/` | **Done**; offline privacy run still to record on the demo laptop |
| **C**: grounding + safety | `verify.py`, `safety.py`, `injection.py`, `priority.py` | **Done** |
| **D**: UI, evaluation, demo | `app/`, `bench/`, samples, video | **In progress**: UI design agreed (`app/mockup/`); Gradio app, `bench/` evaluation, more sample documents and the demo video to come |

## Limitations

Stated honestly:

1. **English only**; text-based PDF and `.txt`; no OCR (scans are detected and
   reported, never guessed).
2. **Tested scope:** rental and employment agreements, on documents we wrote.
   Evaluation on unseen real-world templates is still to do.
3. **Speed depends on hardware:** a full analysis takes minutes on a laptop CPU;
   on an RTX 4060 it should take well under a minute (to be measured).
4. **Retrieval bounds Q&A:** if the relevant clause is not in the top three, the
   answer is "the document doesn't say", never a guess. That is a deliberate trade.
5. **Severity is a fixed formula:** a mutual notice clause can rank as
   "critical"; the weights are a team decision still under review.
6. **Privacy covers the software**, not a compromised OS or a malicious model
   file (scope in the threat model).
7. **No legal conclusions, ever:** validity, enforceability and "should I sign"
   are refused and escalated to a qualified professional.

## Main technical contribution

A reusable **grounding layer for on-device legal assistants**: clause-aware
passage IDs; a deterministic quote, number and date verifier applied to
findings, answers and summaries alike; refusal enforced in code before the
model runs; and a reproducible three-layer privacy proof with an in-process
network guard and canary leak check. Together they show a small edge model can
be trusted on legal text, because code, not the model, decides what reaches the
user.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for set-up, the lane workflow, the privacy
check for new dependencies and how to add a document type.

## Licence and attribution

- Project code: **MIT** (see [LICENSE](LICENSE)).
- Gemma model: licence per its official model card; the all-MiniLM-L6-v2
  embedding model is Apache-2.0. See [docs/MODEL_SETUP.md](docs/MODEL_SETUP.md).
- Sample documents: written by the team, safe to redistribute
  ([docs/DATASETS.md](docs/DATASETS.md)).
- No user documents, credentials or model weights are committed.
