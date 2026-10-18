# LegalLens — Model Setup

> How to obtain, licence, configure and benchmark the on-device Gemma model.
> One-time setup needs the network; **after this page, nothing does**.

---

## 1. Which model and why

| Choice | Value |
|---|---|
| **Family / variant** | Gemma 4 **E4B** (edge-class) |
| **Quantisation** | Q4_K_M 4-bit GGUF (4.98 GB) |
| **Runtime** | llama.cpp `llama-server` on `127.0.0.1:8080` (CUDA, all layers on GPU on the demo laptop) |
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

The GGUF we use is `gemma-4-E4B-it-Q4_K_M.gguf` from the public, ungated
repository `unsloth/gemma-4-E4B-it-GGUF` (4,977,171,584 bytes).

```bash
mkdir -p models
python -c "from huggingface_hub import hf_hub_download as d; d('unsloth/gemma-4-E4B-it-GGUF', 'gemma-4-E4B-it-Q4_K_M.gguf', local_dir='models')"
```

Expected SHA-256: `85a896a047553e842f25297ee5b031d64ff30147d9c4af17b1e4b394cd1fab87`
(check with `certutil -hashfile models\gemma-4-E4B-it-Q4_K_M.gguf SHA256` on
Windows or `sha256sum` elsewhere). The Python call is used instead of the
`hf`/`huggingface-cli` command because that CLI fails to start on some
installs (a `typer` version clash); the library itself is fine.

`models/` is gitignored — weights are **never** committed.

## 4. Run

### Demo laptop: RTX 4060 (8 GB VRAM), 24 GB RAM — recommended

E4B Q4_K_M (~5 GB) fits entirely in 8 GB of VRAM with an 8k context, so
offload every layer to the GPU. Use the **CUDA** build of llama.cpp
(`llama-<build>-bin-win-cuda-13.4-x64.zip` plus
`cudart-llama-bin-win-cuda-13.4-x64.zip` from the llama.cpp GitHub releases,
unzipped into one folder; NVIDIA driver 580+).

```bash
llama-server -m models/gemma-4-E4B-it-Q4_K_M.gguf \
    --host 127.0.0.1 --port 8080 -c 8192 -ngl 99 --jinja \
    --chat-template-kwargs '{"enable_thinking":false}'
```

If quality matters more than speed, `Q5_K_M` (~5.5 GB) also fits fully on the
4060. Record the measured numbers in §5.

### Any machine without a suitable GPU (CPU only)

Same command without `-ngl 99`. On the development laptop (no usable GPU) this
gives about 5 tok/s: a full analysis takes ~4.5 minutes, so raise the client
timeout with `GEMMA_TIMEOUT=900`.

Notes:

- `--host 127.0.0.1` is mandatory — never `0.0.0.0`.
- `--jinja` applies Gemma's own chat template. Gemma 4 "thinks" by default
  and llama-server then returns an empty answer; `llm.py` already sends
  `enable_thinking: false` per request, and the server flag makes it the
  default for any other client too.
- The client (`legallens/llm.py`) calls `/v1/chat/completions` so the Gemma
  chat template is applied. The raw `/completion` endpoint does **not** apply
  it and Gemma degrades badly without it — do not switch.
- The Vulkan build that `winget install ggml.llamacpp` installs hung during
  GPU detection on one of our laptops; use the CUDA build on NVIDIA GPUs.
- Verify the server: `python -c "from legallens.llm import health_check; print(health_check())"`
  → `True`, with the network adapter disabled.

## 5. Benchmark record

| Machine | Backend | Prompt tok/s | Gen tok/s | Full analysis (rental_clear.pdf, 17 clauses) | Per question |
|---|---|---|---|---|---|
| Dev laptop, 12-thread CPU, GTX 1650 4 GB (not used) | llama.cpp b11680 CPU | ~38 | ~5.2 | 265 s | 20–26 s |
| Demo laptop, RTX 4060 8 GB, 24 GB RAM | llama.cpp CUDA, `-ngl 99` | *to measure* | *to measure* | *to measure* | *to measure* |

Run `python smoke.py --file data/samples/rental_clear.pdf` on the demo laptop
and copy the timings it prints; read VRAM/RAM use from Task Manager while it
runs. The dev-laptop run is in `docs/examples/real_run_rental_clear.txt`
(11/11 findings verified).

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
