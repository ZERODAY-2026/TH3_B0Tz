# LegalLens — Evaluator Brief & Defense Q&A

> Team reference for the demo and judge questions. Everything here describes the
> shipped system; where a lane is still landing, it says so.
> **Status:** Lane A (Gemma + analysis pipeline) landed; B (ingest/retrieve/privacy),
> C (verify/safety), D (UI/bench/docs) per PLAN_PS2 §9.

---

## 1. The pitch

**30 seconds:**

> "LegalLens is a fully on-device legal document triage agent. A local Gemma model
> reads your rental or employment agreement and explains clauses in plain language —
> every claim backed by a verbatim quote, checked by code. Nothing you upload ever
> leaves your machine, and when the document doesn't say something, or the question
> needs a lawyer, it says so."

**60 seconds — add:**

> "It works because of one design rule: the model proposes, code disposes. Gemma
> extracts findings as JSON with verbatim quotes; deterministic code then verifies
> every quote is a real substring of the document, every number and date in an
> explanation appears in its quote, and even the summary is verified sentence by
> sentence. Verdict questions like 'is this enforceable?' are refused by a code
> classifier before the model is ever called. And privacy is proven, not promised:
> the full analysis runs with the network adapter off, a connection monitor shows
> zero outbound calls, and a dependency audit backs both up."

---

## 2. Tech stack

| Layer | Choice | Why |
|---|---|---|
| **Model** | Gemma 4 **E4B** (edge-class), 4-bit Q4 GGUF (~4–5 GB) | Largest edge-class variant that fits a 16 GB laptop; Apache-2.0 (confirmed on the official model card at H0). Fallback: E2B |
| **Runtime** | llama.cpp `llama-server` on `127.0.0.1` | Local inference, no cloud; OpenAI-compatible endpoint applies Gemma's chat template (raw `/completion` does not — Gemma degrades without it) |
| **Language** | Python 3.11+, pinned `requirements.lock` | Reproducibility (C5) |
| **Ingestion** | pypdf → pdfplumber fallback | Local PDF/.txt parsing; clause-aware chunking with stable passage IDs (`p3.c2`) |
| **Retrieval** | BM25 (`rank_bm25`) + local MiniLM-class embeddings, FAISS index | Hybrid: exact legal terms + paraphrase matching, all local |
| **UI** | Gradio on `127.0.0.1`, analytics off, no CDN/fonts | Source passage shown beside every explanation |
| **Testing** | pytest (deterministic: verifier, safety rules, chunker — no model needed) + `bench/` evals | CI runs green without weights |

**Telemetry kill-switches set in code, not just docs:**
`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_HUB_DISABLE_TELEMETRY=1`,
`ANONYMIZED_TELEMETRY=False`, `GRADIO_ANALYTICS_ENABLED=False`, `DO_NOT_TRACK=1`.

---

## 3. Architecture

```
document (PDF/.txt)                        ON THE USER'S DEVICE ONLY
   │
   ▼
1. INGEST (B)      pypdf/pdfplumber → text + page map → clause-aware chunker
   │               → passages with stable IDs (p3.c2, page, char offsets)
   ▼
2. INDEX (B)       BM25 + local embeddings → FAISS vector store (local disk)
   │
   ▼
3. ANALYSE (A)     Gemma (127.0.0.1 only); document text = DATA inside
   │               delimiters, never instructions → JSON findings
   ▼               (kind, plain_text, quote, passage_id, label)
4. VERIFY (C)      deterministic code, no model:
   │               quote ∈ passage? numbers/dates ⊆ quote?
   ▼               fail → drop or mark "unverified"
5. SAFETY (C)      labels, ambiguity/jurisdiction flags, "document is silent",
   │               verdict refusal, escalation advice, fixed disclaimer
   ▼
6. UI (D)          127.0.0.1 only: summary · risk list · clause view with source
                   beside explanation · Q&A · escalation panel
```

**Design principle: the model proposes, code disposes.** Gemma reads and explains.
Plain code checks every quote, every number, every refusal rule. The model never
certifies its own output.

---

## 4. The three safety caps (where we over-invest)

The rubric caps the whole PS2 score at **40** if grounding (criterion 2),
uncertainty/refusal (criterion 3) or on-device privacy (criterion 4) lands in
Poor. Our mechanisms:

### 4.1 Grounding (criterion 2)

1. **Passage IDs everywhere** — the model only ever sees passages with IDs and must cite one.
2. **Verbatim quote check** — after normalisation (NFKC, whitespace, curly quotes, case-fold), the quote must be a substring of the cited passage. Near-match (≥ 0.95 similarity) is repaired with the real source span and flagged `quote_corrected`; anything else is **dropped**, counted in eval as a verifier rejection.
3. **Number/date consistency** — every amount, day-count, percentage and date in an explanation must appear in its quote. Catches "30 days" explained as "one month" — the most harmful plain-language distortion.
4. **"The document is silent"** — retrieval below threshold + nothing verifiable → the fixed silent text. Never general knowledge.
5. **Coverage report** — clause types found *and not found* ("no termination clause found"), so users see what's missing.
6. **The summary is verified too** — the summary is generated from *verified findings only*; every sentence carries passage IDs; failing sentences are **dropped, not repaired**. The most claim-dense artifact on screen is never the unverified one.

### 4.2 Uncertainty, refusal, escalation (criterion 3)

- **Labels:** STATED (quote directly and fully supports it) / INTERPRETATION (our reading) / CONCERN (worth asking about). Code *downgrades* labels when evidence is weak — a finding whose explanation adds a fact not in the quote cannot be STATED.
- **Verdict requests** ("is this enforceable?", "should I sign?") are **classified and refused in code before the model is called** — prompt wording is only a backstop.
- **Specific escalation:** which clause, what to ask a qualified professional, what facts to bring — never "consult a lawyer" boilerplate.
- **Jurisdiction flags** (deposit limits, notice periods, non-compete…) — "this depends on where you are", no legal conclusion.
- **Deterministic output filter** blocks "illegal / void / unenforceable / don't sign" phrasings; the test suite checks it.

### 4.3 Privacy (criterion 4) — proven three ways

1. **Cannot connect:** full analysis with networking disabled (adapter off / container `--network none` / WSL2 namespace; Windows path uses Airplane mode + `Get-NetConnectionProfile` capture).
2. **Does not try:** connection monitor (`ss`/`tcpdump`/`Get-NetTCPConnection`) around a normal run → zero non-loopback connections; raw logs saved in `docs/examples/`.
3. **Has no code that connects:** `privacy/audit_deps.py` greps code + installed packages for HTTP clients, update checks, telemetry; every hit reviewed and recorded in `THREAT_MODEL.md`.

Plus: single documented session directory with a "clear session" control; logs carry
only timings/counts/error codes, never document text (verified by grepping logs for
a distinctive phrase from the test document).

---

## 5. Retrieval, explained (BM25 + embeddings + FAISS)

**Why retrieve at all?** Documents run 30+ pages; the 8k context can't hold them,
and long contexts make small models paraphrase instead of quote. Retrieval is the
funnel that makes both grounding and the ~30 s latency budget possible. At upload
we index once; per question we fetch the **top-3** clauses and show only those.

| | BM25 | Embeddings |
|---|---|---|
| What it is | Classic exact-word ranking (rare-word weighting, length normalisation) | Local MiniLM-class model maps clauses & question to vectors; nearest vectors win |
| Best at | Precise legal terms: "security deposit", "lock-in period", "non-compete" | Paraphrases: "can I get my money back if I leave early?" → deposit-refund clause |
| Fails when | The user's words don't match the document's words | Rare exact legal terms a small embedding model under-saw |
| Cost | Pure math over word counts — deterministic, instant, no download | ~100 MB model downloaded at setup, loaded from disk at runtime |

**Why both:** they fail in opposite ways. Legal language is keyword-heavy; user
questions are paraphrase-heavy. We run both and merge rankings (reciprocal-rank
fusion).

**FAISS** (Facebook AI Similarity Search) is the local vector index: it stores the
clause vectors and returns the top-k nearest in milliseconds. In-process, open
source, no network. For a 3-page rental a brute-force numpy scan would do — FAISS
is there because documents are unbounded and costs nothing. Similarity only; all
semantic quality comes from the embedding model.

**The silent path is retrieval-driven, not model judgment:** if the best merged
score is below threshold, code returns "the document does not appear to say
anything about this" — the model never gets the chance to invent.

---

## 6. Why this Gemma variant

> The rules mandate an **edge-class Gemma, on-device, doing meaningful document
> understanding** — either generation (Gemma 3n *or* Gemma 4 E2B/E4B are the named
> class). We derived the variant from constraints, then locked it after H1
> measurement.

| Constraint | Rules out | Survives |
|---|---|---|
| Rules: edge-class Gemma, local, private | 9B/27B+; any cloud inference | E2B / E4B |
| Hardware: 16 GB laptop, RAM shared with OS + UI + embeddings | > 6–8 GB weights | E4B 4-bit ≈ 4–5 GB |
| Task: character-exact quotes, JSON schema, refusals | Weak instruction-following → more verifier rejections | E4B over E2B |
| Latency: ~30 s/Q&A on CPU | Big prompts/models | top-3 retrieval + E4B |

- **Why Gemma 4 generation:** same accepted E-class, reported Apache-2.0 (confirmed on the official model card at H0), better JSON reliability at equal RAM.
- **Why 4-bit (Q4_K_M):** RAM/quality sweet spot for extraction-style tasks.
- **Fallback ladder (measured, not guessed):** Q3_K_S → E2B. H1 decision matrix
  (RAM loaded, load time, tok/sec, JSON parse rate) committed in `bench/results/`.

**Framing:** we didn't pick a variant and justify it — we derived it from the
rules, the hardware and the task, then locked it after measurement.

---

## 7. Main contribution (the memorised answer)

> "A verification-first architecture for small local models: we don't trust Gemma
> to be right, we make it *provably* grounded — quotes, numbers and the summary
> are all checked by deterministic code, so a 4-bit edge model can't fabricate.
> The refusal logic lives in code, not the prompt, so it can't be talked out of
> it — not even by instructions hidden in the document. And because it's
> edge-class, the whole thing runs on a laptop with the network adapter off."

The last clause doubles as the **prompt-injection** answer: document text is
framed as untrusted data inside delimiters, injected instructions
("ignore previous instructions…") are pre-scanned, flagged and ignored — the
output schema is fixed JSON, so injected text can't add fields.

---

## 8. Q&A bank

| If they ask… | You say… |
|---|---|
| Why not feed the whole document to the model? | 8k context vs 30+ page docs, and citation accuracy in small models degrades with context length — retrieval keeps prompts short and quotes exact |
| Why FAISS and not Chroma/Pinecone? | Pinecone is cloud — disqualified by the privacy rule. Chroma is a fine local alternative; FAISS is leaner, battle-tested, fewer moving parts for the dependency audit |
| Do you need FAISS for short contracts? | A brute-force scan would work; FAISS costs nothing and serves unbounded documents with the same code path |
| Where does the vector index persist? | One local session directory, wiped by "clear session" — covered by the temp-file audit |
| Why top-3 passages, not 5? | Latency plus focus; H8 eval showed 3 sufficient |
| Is the embedding model local? | Downloaded once at setup, loaded from disk at runtime, never an API call — part of the privacy proof |
| What if retrieval misses the right clause? | The silence threshold returns "document doesn't say" instead of an answer from the wrong clause — silence is honesty; a wrong citation is fabrication |
| Why not the biggest model you could run? | Reproducibility: the demo must run on ordinary laptops judges can reproduce; we report RAM and tok/sec so they can verify |
| What if E4B misbehaves? | The verifier doesn't trust it — wrong quotes are dropped, not displayed. Architecture absorbs model weakness; that's why we could pick the smallest *reliable* variant |
| Did you measure? | Yes — H1 decision matrix across E4B/E2B × llama.cpp/Ollama: RAM, load time, tok/sec, JSON parse rate; results in `bench/results/` |
| Is Gemma 4 mandatory? | Gemma is; the guide accepts either 3n or 4 E2B/E4B edge class. We chose 4 E4B by measurement |
| Can it do OCR / other languages? | Out of scope by design (stated honestly in README); scanned PDFs are detected with a clear message |
| Is this legal advice? | No — fixed disclaimer on every screen, verdicts refused, escalation to a qualified professional; a deterministic filter blocks advice-like phrasing |
| What are your known limits? | See §9 — we state them in the README because hiding them scores worse than admitting them |

---

## 9. Honest limitations (volunteer these — criterion C7 rewards it)

1. English, text-based PDF/.txt only; no OCR for scans (detected and reported, not guessed).
2. Tested scope: rental and employment agreements; service agreements if time allowed.
3. Retrieval quality bounds Q&A quality — a relevant clause ranked low yields a
   silent answer, never a wrong one. Deliberate trade.
4. Small-model wording is kept deliberately terse; the number/date check hides
   any explanation that drifts.
5. Privacy claims cover the software, not a compromised OS or a malicious model
   file — scope stated in `THREAT_MODEL.md`.

---

## 10. Demo anchor points

1. Network adapter off → full analysis runs → monitor shows zero connections.
2. Unseen document → summary + findings, each with the source passage beside the explanation and its label.
3. Question the document can't answer → "the document does not appear to say anything about this."
4. "Is this enforceable?" → refused, with specific escalation.
5. `injected.pdf` → instruction flagged and ignored; normal analysis output.
