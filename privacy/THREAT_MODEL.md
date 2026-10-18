# LegalLens — Privacy Threat Model

The rule (participant guide, PS2): private document contents — the file,
extracted text, chunks, embeddings, summaries, answers, names, metadata and the
user's questions — must not leave the device during normal processing, and we
must show it with a credible, reproducible test.

This page says what we protect, from whom, how, what we have measured, and
what we do **not** claim.

---

## 1. What we protect

| Asset | Where it lives during a run |
|---|---|
| The uploaded file | Read once from the path the user chose; never copied |
| Extracted text, passages | Python process memory (`ingest()` → `Document`) |
| Prompts and model answers | Loopback HTTP between our process and `llama-server`, then memory |
| Findings, summary, Q&A replies | Python process memory; shown in the UI |
| The user's questions | Python process memory |
| Embeddings / index (when `retrieve.py` lands) | Memory, or the single session folder below |

## 2. Who we defend against

- **Remote services**: any cloud LLM, OCR, translation, embedding or storage API.
- **Telemetry**: analytics, crash reporting, usage pings or update checks in our
  code or any dependency.
- **Leaky side channels on the same machine**: logs, temp files and caches
  that would keep document text after the user is done.

## 3. Controls

1. **Local model only.** Gemma runs in `llama-server`, bound to `127.0.0.1:8080`
   (`--host 127.0.0.1`, never `0.0.0.0`). It is started without `-hf`,
   `--model-url` or any other flag that downloads at run time.
2. **One network client, loopback only.** `legallens/llm.py` is the only code
   that opens a connection. It uses the standard library (`urllib`), so it adds
   no HTTP dependency. It sends to `GEMMA_BASE_URL`, which defaults to `127.0.0.1`.
3. **Kill-switches in code.** `legallens/config.py` sets `HF_HUB_OFFLINE`,
   `TRANSFORMERS_OFFLINE`, `HF_HUB_DISABLE_TELEMETRY` and `DO_NOT_TRACK` at
   import time.
4. **No document text in logs.** LegalLens logs counts, timings and error codes
   only. At its default verbosity, `llama-server` logs timings, not prompts.
   The canary check (§5) confirmed both.
5. **Untrusted document text.** Instructions written inside a document are
   flagged and ignored (`injection.py`). Model output has a fixed JSON schema,
   so a document cannot make the app call out.

## 4. Every network call

**At run time (normal processing):**

| From | To | What | Carries document content? |
|---|---|---|---|
| LegalLens (`llm.py`) | `127.0.0.1:8080` `POST /v1/chat/completions` | prompt with passages, model reply | Yes, but it never leaves the machine (loopback) |
| LegalLens (`llm.py`) | `127.0.0.1:8080` `GET /health` | server liveness | No |

There are no other run-time calls. The only name lookup observed is Python
resolving the literal address `127.0.0.1`. That happens inside the process and
sends no DNS packet.

**At setup time only (user-initiated, before any document is opened, no document content):**

| What | Where |
|---|---|
| Python packages (`pip install -r requirements.txt`) | pypi.org |
| Model weights (`hf_hub_download`, see `docs/MODEL_SETUP.md`) | huggingface.co |
| llama.cpp binaries | github.com (llama.cpp releases) |

## 5. Evidence

The proof has three independent layers. Each layer catches a failure the
others could miss.

### Layer 3: has no code that connects (`privacy/audit_deps.py`)

Report: [`docs/examples/privacy/dependency_audit.md`](../docs/examples/privacy/dependency_audit.md).

- **Our code:** the only network code is in `legallens/llm.py`: `import urllib.request` and
  two `urlopen` calls, to the chat endpoint and `/health`. Both go to the
  configured local server. The three other hits are the word "telemetry" in
  `config.py` comments, next to the kill-switches. **Verdict: expected.**
- **Runtime dependencies:** pypdf, pdfplumber, pdfminer.six, pypdfium2,
  Pillow, charset-normalizer, cryptography, cffi and pycparser. Their Python
  source contains **0** network-client, DNS, socket or telemetry hits.
  **Verdict: clean.**
- **Compiled modules** in Pillow, pypdfium2 (PDFium), cryptography, cffi and
  charset-normalizer can't be read as text. They are image, PDF, crypto and
  charset libraries with no network role. Layers 1 and 2 cover them at run
  time, and Layer 2 saw no outside connection. **Verdict: covered by runtime monitoring.**
- **llama-server** is a native binary from the llama.cpp project. It is covered
  by Layer 2 (its sockets are watched) and Layer 1 (offline run).
- The app loads `socket`, `ssl`, `http.client` and `urllib.request` because
  `urllib` imports them. Loading a module is not using it: Layer 2 shows that
  only loopback connections were made.

### Layer 2: does not try to connect (`privacy/monitor.ps1` / `monitor.sh` + `privacy/netguard.py`)

Recorded run: [`docs/examples/privacy/run-monitored/`](../docs/examples/privacy/run-monitored/).
The full pipeline ran on `data/samples/privacy_canary.txt`: `ingest()`, then
`analyze()`, then three questions (answerable, not in the document, verdict).

| Check | Result |
|---|---|
| Python audit hooks, block mode (every `connect`/`sendto`/DNS/`urllib` call in-process) | 12 events, **0 non-loopback**, all to `127.0.0.1:8080` |
| OS connection table, LegalLens + llama-server, polled every 200 ms for 160 s | 13 endpoints, **0 non-loopback** |
| Files created or modified anywhere under %TEMP%, ~/.cache, %LOCALAPPDATA%\LegalLens and the project during the run | 7 files, **0 contain the canary string** |
| llama-server log searched for the canary | **not found** |
| Pipeline output | 4 verified findings; cited answer; "not in the document" for the pet question; verdict question refused |

The canary is a unique string that appears only in the test document. If it
shows up in any file the run touched outside the evidence folder, document text
has leaked to disk. The evidence folder itself holds `analysis.json` on purpose:
it is the run's output.

Recorded on the development laptop (Windows 11, CPU-only llama.cpp b11680,
gemma-4-E4B-it Q4_K_M), 2026-10-18. Overall verdict: **PASS**.

### Layer 1: cannot connect (`privacy/run_offline.ps1` / `run_offline.sh`)

`run_offline.ps1` refuses to start while the machine has an internet route.
It saves the adapter, profile and route state before and after, then runs the
same monitored capture as Layer 2. `run_offline.sh` runs llama-server and the
pipeline inside a Linux network namespace that has only a loopback interface.

**Status: to be recorded on the demo laptop** (RTX 4060). Turn on Airplane
mode, keep llama-server running, then:

```powershell
powershell -ExecutionPolicy Bypass -File privacy\run_offline.ps1 -ServerLog <path-to-llama-server-log>
```

Evidence goes to `docs/examples/privacy/run-offline/`. Commit it, then update
this section.

## 6. Session data and cleanup

All document-derived data lives in process memory today. `retrieve.py`
(embeddings) and the UI (lane D) must keep anything they store in **one**
folder, `%LOCALAPPDATA%\LegalLens\session` (or `$XDG_CACHE_HOME/LegalLens`),
and must offer a "Clear session data" control that empties it. The canary run
already watches that folder. Rerun the capture and `audit_deps.py` when either
lands; Gradio in particular must run with `GRADIO_ANALYTICS_ENABLED=False`,
system fonts and no CDN assets.

## 7. What we do not claim

- **A compromised machine.** Malware, a keylogger or a hostile administrator
  can read anything on the device; no app can prevent that.
- **A malicious model file.** We load weights from a named repository and
  check their SHA-256 (see `docs/MODEL_SETUP.md`), but a booby-trapped GGUF
  exploiting a parser bug is out of scope.
- **Operating-system copies we don't control.** The pagefile or swap may hold
  memory pages, and a crash dump (Windows Error Reporting) of llama-server
  could contain prompt text. Turn off WER uploads on a machine used for
  sensitive documents. The original file stays wherever the user keeps it, and
  OS search indexing of that file is outside the app.
- **People looking at the screen**, and screenshots.
- **The network state of the machine.** We prove LegalLens and llama-server
  make no outside connections. We do not police other programs.

## 8. Reproduce

```bash
python privacy/audit_deps.py --out docs/examples/privacy/dependency_audit.md      # layer 3
powershell -ExecutionPolicy Bypass -File privacy\monitor.ps1 -ServerLog <log>     # layer 2 (Windows)
./privacy/monitor.sh                                                              # layer 2 (Linux, strace)
powershell -ExecutionPolicy Bypass -File privacy\run_offline.ps1 -ServerLog <log> # layer 1 (Windows, Airplane mode)
./privacy/run_offline.sh                                                          # layer 1 (Linux namespace)
pytest tests/test_privacy.py -q                                                   # guard + audit unit tests
```
