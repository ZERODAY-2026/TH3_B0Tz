# DataMind: 12-Hour Hackathon Plan (team of 4)

> **One-liner:** DataMind turns a plain-language question into a **data-grounded answer**.
> Gemma interprets the question and maps it to the data; Snowflake runs the real query;
> Gemma explains the result in plain language, with the query, rows and assumptions shown
> as evidence. No answer is accepted unless it traces back to something that actually ran.

**Challenge:** ZeroDay OSS Hacktoberfest 2026, IIIT Dharwad — **PS1: DataMind, Talk to Your Data**

## How we meet the challenge rules

| Rule | Our answer |
|---|---|
| Snowflake REQUIRED | Every answer is computed by a query that actually executes against Snowflake at question time — no cached/mocked results, no answering from local files after loading data |
| Google Gemma REQUIRED | Gemma does the AI task central to the product: interpreting the question, generating/checking the query plan, and explaining the result. Gemma inference stays separate from Snowflake/SQL execution |
| Open-source deliverable | Public GitHub repo, MIT licence, README with setup/run/config/troubleshooting, architecture diagram, pinned deps |
| Grounded, evidenced answers (M2–M5) | Every answer carries the executed query, the result rows (or a reference to them) and a plain-language explanation of how it was obtained |
| Honest about limits (M6) | Ambiguous questions, missing data, empty results and unsupported requests get a clear response, never a fabricated answer |
| Gates G1–G5, P1–P3 | Public repo + licence; reproducible demo without undisclosed credentials; real system, not mock-ups; dataset sources/licences disclosed; no secrets in repo; Snowflake and Gemma both used meaningfully; answers derived from retrieval/queries run at question time |

## How it works

```
question (plain language)
      │
      ▼
 Gemma ──interpret──► schema-aware query plan (SQL) ──► pySigma-style validation (read-only, safe)
      │                                                        │
      │                                                        ▼
      │                                               Snowflake executes query
      │                                                        │
      │                                                        ▼
      └──────────────explain + evidence◄── result rows, row/col counts, query_id
                        │
                        ▼
         answer + executed query + rows + assumptions + confidence/ambiguity flag
```

- **Model:** Google Gemma (any suitable variant) for question interpretation and result explanation; keep Gemma calls separate from SQL execution so each is independently testable
- **Data platform:** Snowflake — `SNOWFLAKE_SAMPLE_DATA` (TPC-DS/TPC-H) for joins/aggregates/rankings, plus one real-world dataset (Our World in Data or UCI ML Repository) loaded in for free-text/ambiguity testing
- **Query safety:** generated SQL is validated read-only (no DML/DDL) and schema-checked before it ever reaches Snowflake
- **Scope:** business-intelligence style questions over 2 loaded datasets — single-table lookups, multi-table joins, aggregates, rankings, simple trend/time-series questions, and at least one deliberately unanswerable question per category (ambiguous phrasing, missing column, empty result)

## Team lanes

| Person | Lane | Owns | Load |
|---|---|---|---|
| **A** | NL → query orchestration | `datamind/llm.py`, `datamind/orchestrate.py`: Gemma client, question-interpretation prompt, SQL draft → validate → retry loop, explanation prompt | Heaviest |
| **B** | Snowflake data layer | `datamind/snowflake_client.py`: connection/warehouse setup, read-only query execution, schema introspection, credit-use guardrails | Heavy |
| **C** | Evidence + robustness | `datamind/evidence.py`: evidence packaging (query, rows, query_id), ambiguity/missing-data/empty-result handling, ground-truth eval question set | Medium |
| **D** | Data + benchmark + demo | `data/`: load TPC-DS/TPC-H + one OWD/UCI dataset into Snowflake; `bench/`: correctness vs ground truth; README, architecture diagram, 5-min demo recording, submission | Medium |

**Interfaces (agree these at H0, then everyone can stub the others):**

```python
# B provides
run_query(sql: str) -> QueryResult
# QueryResult: columns, rows, query_id, row_count, error: str | None, warehouse_credits_used: float

# A provides
answer(question: str) -> Answer
# Answer: text, sql, query_result: QueryResult | None, explanation, assumptions: list[str],
#         ambiguous: bool, unsupported: bool, model: str

# C provides
evidence_report(answer: Answer) -> EvidenceReport
# EvidenceReport: query, rows_shown, source_tables, assumptions, confidence_note

# D provides
load_dataset(name: str) -> None       # loads into Snowflake, idempotent
eval_questions(name: str) -> list[dict]  # {question, expected_answer, expected_tables}
```

## Hour-by-hour

### H0–H1: Kickoff (everyone)
- Read this plan, agree on the interfaces above, create branches
- Everyone sets up: Snowflake trial account (no payment details, confirm `signup.snowflake.com` terms), Gemma access (Hugging Face licence accepted or local runtime), `.env` gitignored
- D confirms which two datasets we load first; schema sketch shared with A and C

### Person A: NL → query orchestration
| Hour | Task |
|---|---|
| H1–H2 | Gemma client (local or hosted, OpenAI-compatible or native SDK); first prompt that turns a question + schema into a draft SQL query |
| H2–H3 | Read-only SQL validation (reject DML/DDL/unknown tables); on invalid SQL, feed the error back and retry (max 2) |
| H3–H4 | Wire `answer()` against a **stub** `run_query()` until B's lands |
| H4–H6 | Explanation prompt: turn `QueryResult` into a plain-language answer with assumptions stated; ambiguity/unsupported-request detection |
| H6 | ✅ Checkpoint 2: `answer()` runs end-to-end on 2 question categories with B's real Snowflake execution |
| H6–H8 | Multi-table joins, follow-up questions with context, guard against over-confident answers on empty results |
| H8–H9 | Tune prompts with D's eval results; fix wrong-table / wrong-column failure modes |
| H9–H10.5 | Bug fixes, help C with evidence formatting |
| H10.5–H12 | Code freeze → demo dry-run → submit |

### Person B: Snowflake data layer
| Hour | Task |
|---|---|
| H1–H2 | Snowflake connection (key-pair or password from `.env`), warehouse sizing, confirm `SNOWFLAKE_SAMPLE_DATA` is shared into the account |
| H2–H4 | `run_query()`: execute, capture `query_id`, row/col metadata, credit use; read-only enforcement at the execution layer too (defence in depth) |
| H4 | ✅ Checkpoint 1: `run_query()` returns correct results for 3 hand-written SQL queries across TPC-DS/TPC-H |
| H4–H6 | Load D's second dataset (OWD/UCI) into Snowflake tables; schema introspection helper for A's prompt |
| H6–H8 | Query timeout/credit guardrails (trial accounts get ~10 credits/day of Cortex AI Functions — track usage so the demo doesn't run dry) |
| H8–H9 | Clear error messages for bad SQL / exhausted credits / region-unavailable features |
| H9–H10.5 | Bug fixes from D's benchmark runs |
| H10.5–H12 | Code freeze → demo dry-run → submit |

### Person C: Evidence + robustness
| Hour | Task |
|---|---|
| H1–H3 | Design `EvidenceReport`: query, trimmed result rows, source tables, assumptions, confidence note |
| H3–H4 | Ambiguous-question handling: detect vague questions, ask for clarification instead of guessing |
| H4 | ✅ Checkpoint 1: evidence report renders correctly for 3 hand-built `Answer` objects |
| H4–H6 | Missing-data and empty-result handling: say so explicitly, never fabricate a number |
| H6–H8 | Ground-truth eval question set (varied phrasing, same intent) for D's benchmark; unsupported-request refusal (e.g. questions needing data we don't have) |
| H8–H9 | CLI/UI surfacing of evidence (query + rows + explanation in one view) |
| H9–H10.5 | Test the full flow end-to-end with unseen questions; fix wording/formatting |
| H10.5–H12 | Code freeze → demo dry-run → submit |

### Person D: Data + benchmark + demo
| Hour | Task |
|---|---|
| H1–H3 | Repo hygiene: README skeleton, LICENSE, CI (lint, tests); issue board; load TPC-DS/TPC-H sample data |
| H3–H6 | Load second dataset (Our World in Data or UCI ML Repository) into Snowflake; write loader as idempotent script |
| H6 | ✅ Checkpoint 2: first benchmark run — correctness vs independently computed ground truth, even if numbers are bad |
| H6–H8 | `bench/run.py`: precision of answers vs ground truth, evidence completeness, latency; save example Q&A to `docs/examples/` |
| H8–H9 | Architecture diagram; slides (problem → how it works → live demo → results → what's next) |
| H9 | ✅ Checkpoint 3: feature freeze candidate, final benchmark run, README results section |
| H9–H10.5 | Record ~5-min demo video (live Q&A, evidence shown, one ambiguous/empty-result case); pre-record a backup run in case Snowflake credits run out |
| H10.5–H12 | Code freeze → demo dry-run → **submit** (repo link, video, description) |

## Checkpoints

| When | What must be true |
|---|---|
| **H4** | B's `run_query()` works on hand-written SQL; C's evidence report renders; A drafts valid read-only SQL |
| **H6** | End-to-end: question → executed query → evidenced answer, on 2 question categories. First benchmark run. **Cut scope here if behind.** |
| **H9** | All question categories work; README has results; feature freeze candidate |
| **H10.5** | 🧊 Code freeze. Only fixes for demo-breaking bugs. |

## Scope cuts (in this order, decided at H6)

1. Follow-up questions with context (keep single-turn Q&A)
2. Second dataset (keep TPC-DS/TPC-H only, drop OWD/UCI)
3. Multi-step analysis / visualizations (optional ideas — never required)
4. Reduce to 2 question categories (single-table lookups + simple aggregates)

## Demo script (~5 min)

1. **Problem (30s):** Getting a useful answer from data takes SQL skills or hours of manual digging; the people who know the question best often can't reach the data.
2. **Live (3 min):** Ask 3–4 unseen questions spanning categories — a simple lookup, a multi-table join, an ambiguous question (model asks for clarification instead of guessing), and one with no matching data (model says so honestly). Show the executed query and rows for each.
3. **Results (1 min):** Benchmark table — correctness vs ground truth, evidence completeness, across question categories.
4. **Close (30s):** Architecture recap — Gemma interprets and explains, Snowflake executes, nothing is answered without a real query behind it.

## Risks

| Risk | Mitigation |
|---|---|
| Snowflake trial credits run out mid-demo | Track credit use from H2; pre-record a backup demo run; keep warehouse small |
| Gemma gives plausible-sounding wrong SQL | Read-only validation + schema check before execution; benchmark catches it early at H6 |
| Cortex features unavailable in our cloud region | Confirm in-account at H1, don't depend on anything unconfirmed |
| Trust cap: correctness scored Poor caps whole PS1 at 50 | Treat correctness (criterion 1, 20 pts) as the top priority from H4 onward, ahead of polish |
| Merge conflicts late | One owner per folder; PRs only; no pushes to `main` after H10.5 |

## Git workflow

- Branches: `a/orchestrate-*`, `b/snowflake-*`, `c/evidence-*`, `d/data-bench-*`
- Small PRs → 1 review → squash merge; CI must be green
- Never commit API keys or Snowflake credentials; `.env` is gitignored
