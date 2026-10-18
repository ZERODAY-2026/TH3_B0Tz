# LegalLens — Model Setup

> How to obtain, licence, configure and benchmark the on-device Gemma model.
> One-time setup needs the network; **after this page, nothing does**.

---

## 1. Which model and why

| Choice | Value |
|---|---|
| **Family / variant** | Gemma 4 **E4B** (edge-class) |
| **Quantisation** | Q4_K_M 4-bit GGUF (~4–5 GB) |
| **Runtime** | llama.cpp `llama-server` on `127.0.0.1:8080` |
| **Context** | 8192 tokens |
| **Fallbacks** | Q3_K_S → E2B (same family), each re-measured |

Why this variant (derived, not guessed):

1. **The rules** mandate an edge-class Gemma running on-device — either
   generation (Gemma 3n *or* Gemma 4 E2B/E4B) is accepted; Gemma 4 is reported
   Apache-2.0 and shows better JSON reliability at equal RAM.
2. **Hardware** — E4B at 4-bit fits a 16 GB laptop alongside the OS, UI and the
   embedding model, with headroom.
3. **The task** punishes paraphrasing: character-exact quotes and schema
   adherence are exactly where the larger edge variant pays for itself (fewer
   verifier rejections → fewer dropped findings).
4. **Latency** — with top-3 retrieval, E4B answers inside the ~30 s demo budget
   on CPU.

The decision is locked at **H1 after measurement**, not before.

## 2. Licence steps (do these first)

1. Open the official Gemma model card on Hugging Face (or Kaggle) **while you
   have network**.
2. Read and accept the licence. Gemma 4 is reported Apache-2.0 — **confirm on
   the official model card**; if the card states different terms, those terms
   apply and this document must be updated.
3. Note the exact repository id, file name and SHA of the GGUF you downloaded —
   record them below in §5.

## 3. Download (setup time only)

```bash
mkdir -p models
# log in once (network):
huggingface-cli login
# pull the Q4_K_M GGUF (~4–5 GB):
huggingface-cli download <org>/<gemma-4-e4b-gguf-repo> \
    --include "*Q4_K_M*" --local-dir models
```

Ollama alternative (same weights, different packaging):

```bash
ollama pull <gemma-4-e4b-tag>          # serves on 127.0.0.1:11434
# then: GEMMA_BASE_URL=http://127.0.0.1:11434
```

`models/` is gitignored from the first commit — weights are **never** committed.

## 4. Run

```bash
llama-server -m models/<gemma-4-e4b-Q4_K_M>.gguf \
    --host 127.0.0.1 --port 8080 -c 8192
```

Notes:

- `--host 127.0.0.1` is mandatory — never `0.0.0.0`.
- The client (`legallens/llm.py`) calls `/v1/chat/completions` so the Gemma
  chat template is applied. The raw `/completion` endpoint does **not** apply
  it and Gemma degrades badly without it — do not switch.
- Verify the server: `python -c "from legallens.llm import health_check; print(health_check())"`
  → `True`, with the network adapter disabled.

## 5. H1 benchmark record (fill at H1, commit to `bench/results/`)

`bench/results/h1_model_benchmarks.json`:

```json
{
  "model": "gemma-4-e4b-q4_k_m",
  "weights_sha256": "<fill>",
  "runtime": "llama-server <version>",
  "context_window": 8192,
  "ram_idle_gb": 0,
  "ram_loaded_gb": 0,
  "load_time_sec": 0,
  "tokens_per_sec": 0,
  "json_first_try_rate": 0.0,
  "hardware": "CPU: ..., RAM: ... GB, GPU: ...",
  "os": "..."
}
```

Decision matrix (measured, then winner locked):

| Option | RAM (GB) | tok/sec | JSON reliable? |
|---|---|---|---|
| llama.cpp E4B Q4_K_M | | | |
| llama.cpp E4B Q3_K_S | | | |
| llama.cpp E2B Q4_K_M | | | |
| Ollama E4B | | | |

**Winner:** ______ **Reason:** ______

## 6. Fallback ladder

If the demo laptop struggles at any checkpoint:

1. Drop context 8192 → 4096 (chunk groups shrink; pipeline unchanged).
2. Q4_K_M → Q3_K_S (~3 GB; quote fidelity usually holds).
3. E4B → E2B (~2 GB; expect more verifier repairs — the verifier, not the
   user, absorbs the difference).

Every switch is re-measured and recorded in §5. Architecture is
model-agnostic; nothing in `analyze.py` assumes a variant.

## 7. Privacy notes for this page

- Downloads happen **once, at setup, with user action** — allowed explicitly by
  the rules ("provided no private user document is sent").
- No document content is ever part of any download, request or log.
- After setup, `HF_HUB_OFFLINE=1` and friends (set in code,
  `legallens/config.py`) make hub access impossible even by accident.
