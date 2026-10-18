# 🏗️ LegalLens Architecture

## System Overview

LegalLens is an offline, privacy-first legal document analyzer for rental and employment agreements. It runs entirely on 127.0.0.1 with no external CDN dependencies, network calls, or analytics.

\┌────────────────────────────────────────────────────────┐
│                      Gradio UI                         │
│   Upload -> Summary (+Citations) -> Risk List          │
│   -> Side-by-Side Clauses -> Q&A -> Escalation Panel   │
│   [Permanent Legal Advice Disclaimer Banner]           │
└───────────────────────────┬────────────────────────────┘
                            │ (Local In-Memory Calls)
┌───────────────────────────▼────────────────────────────┐
│                    app/contracts.py                    │
│           (Pipeline Seam / Ingestion Wrapper)          │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                  legallens.analyze                     │
│  ┌───────────────┐  ┌──────────────┐  ┌─────────────┐  │
│  │ Ingest/Chunk  │->│ Prompt/LLM   │->│ Verifier/   │  │
│  │ (pypdf/txt)   │  │ (Stub/Gemma) │  │ Safety      │  │
│  └───────────────┘  └──────────────┘  └─────────────┘  │
└───────────────────────────┬────────────────────────────┘
                            │ Local HTTP (127.0.0.1:8080)
┌───────────────────────────▼────────────────────────────┐
│         Local Model Server (llama-server / Gemma)      │
└────────────────────────────────────────────────────────┘
\
## Key Design Principles

1. **Zero Data Egress (100% Offline)**: All analysis, parsing, and LLM inference occur strictly on localhost. No document or metadata ever leaves the host machine.
2. **Grounded Extraction & Citations**: Summaries and findings must point directly to exact source passages (passage_id). Quotes are verified against source text.
3. **Defense Against Prompt Injection**: User documents are treated as untrusted data. Instructions embedded within contracts (e.g. [SYSTEM] Ignore prior instructions...) are detected and suppressed.
4. **Honest Ambiguity & Refusal**: When terms are vague, contradictory, or absent, the model flags ambiguity or responds with 'not found in document' rather than hallucinating.
5. **Clear Legal Escalation**: Permanent disclaimer on every screen, with high-risk terms flagged for human legal counsel review.

## Team Component Ownership

| Component | Primary Owner | Description |
|-----------|---------------|-------------|
| Ingestion & Chunking | Person B | Clause-aware paragraph segmentation and PDF text extraction |
| Prompts & LLM Client | Person C | Gemma client, retry loop, and JSON schema extraction |
| Verification & Safety | Person A | Quote grounding, conflict detection, and injection filtering |
| UI, Tests, Docs, Demo | Person D | Gradio interface, eval harness, synthetic docs, CI, demo |
