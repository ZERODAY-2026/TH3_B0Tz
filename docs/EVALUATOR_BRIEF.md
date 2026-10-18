# LegalLens — Evaluator Brief & Defense Q&A

> Team reference for the demo and judge questions. Everything here describes the
> system as it is in `main`; anything not finished is marked as such. If a judge
> asks about something marked pending, say so plainly.
>
> **Status:** analysis pipeline, ingestion, hybrid retrieval, grounding verifier,
> safety layer, severity ordering and privacy tooling are done (137 tests, CI on
> Ubuntu + Windows). **Pending:** the Gradio UI (design agreed), the offline
> privacy run and speed numbers on the demo laptop (RTX 4060), the `bench/`
> evaluation, more sample documents, and the demo video.

---

## 1. The pitch

**30 seconds:**

> "LegalLens is a fully on-device legal document triage agent. A local Gemma model
> reads your rental or employment agreement and explains clauses in plain language,
> every claim backed by a verbatim quote and checked by code. Nothing you open ever
> leaves your machine, and when the document doesn't say something, or the question
> needs a lawyer, it says so."

**60 seconds, add:**

> "It works because of one design rule: the model proposes, code disposes. Gemma
> extracts findings as JSON with verbatim quotes; deterministic code then checks
> that every quote really is in the document, that every number and date in an
> explanation appears in its quote, and it checks the summary sentence by
> sentence. Verdict questions like 'is this enforceable?' are refused by code
> before the model is ever called. And privacy is measured, not promised: an
> in-process network guard and an OS connection monitor recorded zero outside
> connections during a full run, and no text from the document turned up in any
> file on disk."

---

## 2. Tech stack

| Layer | Choice | Why |
|---|---|---|
| **Model** | Gemma 4 **E4B** (edge-class), Q4_K_M GGUF, 4.98 GB (`unsloth/gemma-4-E4B-it-GGUF`, SHA-256 recorded) | Strongest edge-class variant that fits the demo laptop's 8 GB GPU entirely; fallback Q3_K_S → E2B. Licence: per the official model card |
| **Runtime** | llama.cpp `llama-server` on `127.0.0.1`, `--jinja`, thinking off | Local inference; the chat endpoint applies Gemma's template; Gemma 4's "thinking" is switched off so answers come back as plain JSON |
| **Ingestion** | pypdf → pdfplumber fallback | Local PDF/.txt; headers/footers stripped; clause-aware chunks with stable IDs (`p3.c2`) |
| **Retrieval** | BM25 (`rank_bm25`) + all-MiniLM-L6-v2 as ONNX (onnxruntime, no PyTorch) in a FAISS index, **in memory** | Exact legal terms + paraphrase; 15/15 handwritten questions find the right clause in the top 3 |
| **Language** | Python 3.11+, versions pinned in `requirements.txt` | CI tests 3.11 and 3.13 on Ubuntu and Windows |
| **UI** | Gradio on `127.0.0.1`, analytics off, system fonts, no CDN (*in progress*) | Source passage beside every explanation |
| **Testing** | 137 pytest tests, no model or network needed | CI runs green without model files |

**Kill-switches set in code at import** (`legallens/config.py`): `HF_HUB_OFFLINE=1`,
`TRANSFORMERS_OFFLINE=1`, `HF_HUB_DISABLE_TELEMETRY=1`, `DO_NOT_TRACK=1`.
`GRADIO_ANALYTICS_ENABLED=False` is in `.env.example` and must be set by the UI
when it lands. `GEMMA_BASE_URL` is refused unless it points at 127.0.0.1/localhost.

---

## 3. Architecture

```
document (PDF/.txt)                        ON THE USER'S DEVICE ONLY
   │
   ▼
1. INGEST          pypdf/pdfplumber → headers/footers stripped → clause chunks
   │               with stable IDs (p3.c2) and headings; bad files → one clear message
   ▼
2. ANALYSE         Gemma on 127.0.0.1; document text = DATA inside delimiters,
   │               never instructions → JSON findings
   ▼               (kind, plain_text, quote, passage_id, label, confidence)
3. VERIFY          deterministic code, no model: quote ∈ passage?
   │               numbers/dates ⊆ quote?  fail → dropped or "unverified"
   ▼
4. SAFETY          labels, ambiguity/jurisdiction flags, verdict refusal in code,
   │               escalation notes, wording filter, severity order
   ▼
5. ASK             BM25 + MiniLM/FAISS (in memory) → top-3 clauses → Gemma →
                   citations verified → cited answer / "doesn't say" / refusal
```

**Design principle: the model proposes, code disposes.**

---

## 4. The three safety caps (where we over-invest)

The rubric caps the whole PS2 score at **40** if grounding (criterion 2),
uncertainty/refusal (criterion 3) or on-device privacy (criterion 4) lands in
Poor.

### 4.1 Grounding (criterion 2)

1. **Passage IDs everywhere**: the model only sees clauses with IDs and must cite one.
2. **Verbatim quote check**: after normalisation (NFKC, whitespace, curly quotes, case), the quote must be a substring of the cited clause. A near match (≥ 0.95) is replaced with the real source text and flagged `quote_corrected`; anything else is marked `unverified` and hidden.
3. **Number/date consistency**: every amount, day count, percentage and date in an explanation must appear in its clause. Catches "30 days" explained as "one month".
4. **"The document is silent"**: if an answer's citations don't verify against the retrieved clauses, the reply becomes the fixed silent text, never general knowledge.
5. **Coverage report**: clause types found *and not found*.
6. **The summary is verified too**: built from verified findings only; every sentence carries clause IDs; failing sentences are dropped, not repaired.
7. **Incomplete is said out loud**: if the model fails on part of a document, those clauses are listed and the user is warned. A partial analysis is never shown as complete.

**Evidence:** real run on `rental_clear.pdf`: 11 findings, 11/11 verified
([log](examples/real_run_rental_clear.txt)); `tests/test_verify.py`.

### 4.2 Uncertainty, refusal, escalation (criterion 3)

- **Labels:** stated / our reading / worth asking about. Code *downgrades* a "stated" label when the explanation adds content not in the quote.
- **Verdict requests** ("is this enforceable?", "should I sign?") are **refused in code before the model is called**; prompt wording is only a backstop.
- **Specific escalation:** which clause, what to ask, what to bring.
- **Jurisdiction flags** (deposit, notice period, non-compete, probation, rent increase…): "this depends on where you are", no conclusion.
- **Deterministic wording filter** removes "illegal / void / unenforceable / should sign" phrasing; tests check it.

**Evidence:** [SAFETY_EXAMPLES.md](examples/SAFETY_EXAMPLES.md); `tests/test_safety.py`.

### 4.3 Privacy (criterion 4): three layers ([threat model](../privacy/THREAT_MODEL.md))

1. **Does not try** (recorded, **PASS**): Python audit hooks record and block every connect, sendto, DNS lookup and urllib call in the process; an OS monitor watches LegalLens and llama-server; a canary string from the test document is searched for in every file touched. Result over a full run including retrieval: 12 connection attempts, all to `127.0.0.1:8080`; 0 outside; canary in none of 17 files touched. ([evidence](examples/privacy/run-monitored/))
2. **Has no code that connects** (recorded, **clean**): `audit_deps.py` scans our code and 43 runtime dependencies and profiles a real session. Only `legallens/llm.py` talks to the network (to the local model). The 4 live dependency hits are numpy's optional URL loader, which we never call. Hugging Face's client arrives with `tokenizers` but is never imported. ([report](examples/privacy/dependency_audit.md))
3. **Cannot connect** (*to record on the demo laptop*): `privacy/run_offline.ps1` refuses to run while online, then repeats the monitored run in Airplane mode.

Embeddings and the index stay in memory; logs carry counts and timings only.

---

## 5. Retrieval, explained (BM25 + embeddings + FAISS)

**Why retrieve at all?** The 8k context can't hold long contracts, and long
contexts make small models paraphrase instead of quote. Per question we send only
the **top-3** clauses.

| | BM25 | Embeddings |
|---|---|---|
| What it is | Exact-word ranking (rare words weigh more) | all-MiniLM-L6-v2 maps clauses and the question to vectors; nearest win |
| Best at | "security deposit", "sublet", "60 days" | "can I leave the flat early?" → the early-exit clause |
| Fails when | The user's words aren't the document's words | Rare exact legal terms |
| Cost | Instant, no download | 91 MB ONNX model, set-up download, ~4 ms per query on CPU |

**Why both:** they fail in opposite ways; rankings are merged with
reciprocal-rank fusion. A small lay-term glossary expands the BM25 query only
("rent a room to a friend" → *sublet*), so it can steer the search but never
put words in an answer.

**FAISS** is the in-process vector index. For a 3-page contract a plain scan
would do; FAISS keeps the same code path for long documents.

**Silence:** decided by citation verification today. Retrieval also scores
relevance, and unanswerable questions score low (≈0.2 vs ≈0.5), so a threshold
that skips the model call is possible but **not enabled yet**.

---

## 6. Why this Gemma variant

| Constraint | Rules out | Survives |
|---|---|---|
| Rules: edge-class Gemma, local, private | 9B/27B+; any cloud inference | E2B / E4B |
| Demo laptop: RTX 4060, 8 GB VRAM, 24 GB RAM | Weights over ~6.5 GB on GPU | E4B Q4_K_M (4.98 GB), every layer on the GPU |
| Task: character-exact quotes, JSON schema, refusals | Weak instruction-following | E4B over E2B |

- **Q4_K_M:** quality/size sweet spot for extraction; Q5_K_M (5.5 GB) also fits the 4060.
- **Measured so far:** on a CPU-only laptop, ~5 tok/s; 11/11 findings verified
  on the sample rental. **GPU numbers on the 4060 are still to be recorded**
  (MODEL_SETUP.md §5). Don't quote GPU speeds until they are.

---

## 7. Main contribution (the memorised answer)

> "A verification-first architecture for small local models: we don't trust Gemma
> to be right, we make it checkably grounded. Quotes, numbers and the summary are
> all checked by deterministic code, so a 4-bit edge model can't slip a
> fabrication past the user. The refusal logic lives in code, not the prompt, so
> it can't be talked out of it, not even by instructions hidden in the document.
> And the privacy claim comes with recorded evidence: a network guard, a
> connection monitor and a canary leak check."

---

## 8. Q&A bank

| If they ask… | You say… |
|---|---|
| Why not feed the whole document to the model? | Context limits, and small models quote less exactly as context grows; top-3 retrieval keeps prompts short and quotes exact |
| Why FAISS and not Chroma/Pinecone? | Pinecone is cloud, so it's out. Chroma would work locally; FAISS is leaner and in-process, so there's less to audit |
| Where does the index live? | In memory only, cached per open document; `clear_cache()` drops it. Nothing is written to disk, and the canary check confirms that |
| Why top-3 clauses? | Latency and focus. It's a design choice we haven't benchmarked against 5 yet; the eval (`bench/`) is pending |
| Is the embedding model local? | Yes: downloaded once at set-up (pinned commit, SHA-256 recorded), run by onnxruntime on the CPU, no API |
| What if retrieval misses the right clause? | Citations won't verify, so the reply is "the document doesn't say", not an answer from the wrong clause |
| What if E4B misbehaves? | Wrong quotes are dropped, numbers are checked, bad JSON is skipped and reported as incomplete; the architecture absorbs model weakness |
| Did you measure? | Yes on CPU (timings, 11/11 verified findings, retrieval 15/15 top-3). GPU numbers on the demo laptop and a full eval on unseen documents are still to come; say so |
| Is Gemma 4 allowed? | The guide accepts Gemma 3n or Gemma 4 E2B/E4B edge-class models; we use Gemma 4 E4B |
| What about the licence? | Gemma's terms are on its official model card; the embedding model is Apache-2.0; our code is MIT |
| OCR / other languages? | Out of scope; scanned PDFs get a clear message, never a guess |
| Is this legal advice? | No: disclaimer on every screen, verdicts refused, wording filter, specific escalation |
| What happens on a bad file? | Empty, damaged, password-protected or scanned files return one plain message; the model is never called |

---

## 9. Honest limitations (volunteer these)

1. English, text-based PDF/.txt only; no OCR.
2. Tested on rental and employment agreements we wrote; unseen real-world templates not yet evaluated.
3. Retrieval bounds Q&A: a clause outside the top three yields "doesn't say", never a guess.
4. Severity is a fixed formula; a mutual notice clause can rank "critical".
5. Privacy covers the software, not a compromised OS or a malicious model file.
6. The offline run and GPU speed numbers are still to be recorded on the demo laptop.

---

## 10. Demo anchor points

1. Network adapter off → `run_offline.ps1` → full analysis → zero outside connections.
2. A document we didn't tune on → findings, each with the source clause beside the explanation and its label.
3. A question the document can't answer → "the document does not appear to say anything about this."
4. "Is this enforceable?" → refused, with specific escalation.
5. A document with an injected instruction → flagged and ignored; normal analysis.
6. A scanned PDF → one clear message, no crash.
