// LegalLens — Solution Proposal (concise .docx)
// Generates docs/LegalLens_Solution_Proposal.docx. Helpers mirror make_docx.js.
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow,
  TableCell, WidthType, ShadingType, AlignmentType, BorderStyle,
  PageOrientation, LevelFormat, Header, Footer, PageNumber,
} = require("docx");
const fs = require("fs");
const path = require("path");

// ---------- helpers ----------

const INK = "1A1A2E";
const ACCENT = "1F3864";   // deep blue for headings
const MUTED = "5B6470";
const HDRBG = "1F3864";
const ALTBG = "F2F5F9";

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 160 },
    children: [new TextRun({ text, bold: true, size: 34, color: ACCENT, font: "Georgia" })],
  });
}
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 280, after: 120 },
    children: [new TextRun({ text, bold: true, size: 26, color: ACCENT, font: "Georgia" })],
  });
}
function h3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 220, after: 100 },
    children: [new TextRun({ text, bold: true, size: 23, color: "2E4B7A", font: "Georgia" })],
  });
}
function p(text, opts = {}) {
  const runs = Array.isArray(text) ? text : [new TextRun({ text, size: 21, color: INK })];
  return new Paragraph({
    spacing: { after: 120, line: 300 },
    alignment: opts.align,
    children: runs,
    ...(opts.style || {}),
  });
}
function r(text, o = {}) {
  return new TextRun({ text, size: 21, color: o.color || INK, bold: o.bold, italics: o.italics, font: o.font });
}
function bullet(text, level = 0) {
  const runs = Array.isArray(text) ? text : [r(text)];
  return new Paragraph({
    numbering: { reference: "bul", level },
    spacing: { after: 80, line: 290 },
    children: runs,
  });
}
function numbered(text) {
  const runs = Array.isArray(text) ? text : [r(text)];
  return new Paragraph({
    numbering: { reference: "num", level: 0 },
    spacing: { after: 80, line: 290 },
    children: runs,
  });
}
function mono(text, size = 18) {
  return new Paragraph({
    spacing: { after: 0, line: 260 },
    shading: { type: ShadingType.CLEAR, fill: "F4F4F6" },
    children: [new TextRun({ text, font: "Consolas", size, color: "24292F" })],
  });
}
function codeBlock(lines) {
  return lines.map((l) => mono(l === "" ? " " : l));
}
function quote(text) {
  return new Paragraph({
    spacing: { before: 100, after: 140 },
    indent: { left: 360, right: 360 },
    border: { left: { style: BorderStyle.SINGLE, size: 18, color: ACCENT, space: 12 } },
    children: [new TextRun({ text, italics: true, size: 21, color: "333F55" })],
  });
}
function spacer(after = 120) {
  return new Paragraph({ spacing: { after }, children: [] });
}

const tableBorders = {
  top: { style: BorderStyle.SINGLE, size: 4, color: "C9D2DE" },
  bottom: { style: BorderStyle.SINGLE, size: 4, color: "C9D2DE" },
  left: { style: BorderStyle.SINGLE, size: 4, color: "C9D2DE" },
  right: { style: BorderStyle.SINGLE, size: 4, color: "C9D2DE" },
  insideHorizontal: { style: BorderStyle.SINGLE, size: 4, color: "C9D2DE" },
  insideVertical: { style: BorderStyle.SINGLE, size: 4, color: "C9D2DE" },
};

function cellPara(content, bold, color) {
  const runs = Array.isArray(content) ? content
    : [new TextRun({ text: content, bold, size: 19, color: color || INK })];
  return new Paragraph({ spacing: { after: 40, line: 260 }, children: runs });
}

// table(rows) — rows[0] is the header; each cell: string or {runs}
function table(rows, widths) {
  const total = widths.reduce((a, b) => a + b, 0);
  return new Table({
    width: { size: total, type: WidthType.DXA },
    columnWidths: widths,
    borders: tableBorders,
    rows: rows.map((row, ri) =>
      new TableRow({
        tableHeader: ri === 0,
        children: row.map((cell, ci) =>
          new TableCell({
            width: { size: widths[ci], type: WidthType.DXA },
            shading: ri === 0
              ? { type: ShadingType.CLEAR, fill: HDRBG }
              : ri % 2 === 0 ? { type: ShadingType.CLEAR, fill: ALTBG } : undefined,
            children: [cellPara(
              cell,
              ri === 0,
              ri === 0 ? "FFFFFF" : INK
            )],
          })
        ),
      })
    ),
  });
}


// ---------- content ----------

const W = 9306; // A4 text width at 1300 margins
const children = [];
const b = (t) => r(t, { bold: true });

// Title block (compact, no separate cover page)
children.push(
  new Paragraph({ spacing: { before: 200, after: 0 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "LegalLens", bold: true, size: 56, color: ACCENT, font: "Georgia" })] }),
  new Paragraph({ spacing: { before: 60, after: 60 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "Solution Proposal: a private, on-device legal document triage agent", size: 26, color: MUTED, font: "Georgia" })] }),
  new Paragraph({ spacing: { after: 200 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "ZeroDay OSS Hacktoberfest 2026, IIIT Dharwad  ·  PS2: Agentic AI  ·  Team TH3_B0Tz  ·  October 2026", size: 19, color: MUTED })] }),
  new Paragraph({
    spacing: { after: 200 },
    border: {
      top: { style: BorderStyle.SINGLE, size: 6, color: "B03A2E", space: 6 },
      bottom: { style: BorderStyle.SINGLE, size: 6, color: "B03A2E", space: 6 },
    },
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "LegalLens is for preliminary document understanding and issue spotting only. It is not a lawyer, gives no legal advice, and never decides whether a clause is valid, legal or enforceable.", italics: true, size: 19, color: "6E2C24" })],
  }),
);

// 1. Summary
children.push(h1("1  Summary"));
children.push(p([r("LegalLens reads a rental or employment agreement "), b("entirely on the user's machine"), r(". It explains clauses in plain language and flags obligations, rights, deadlines, penalties, termination terms and ambiguities. Every claim carries a verbatim quote from the document, checked by code. When the document is silent, or the question needs a lawyer, LegalLens says so instead of guessing.")]));
children.push(p([r("Design rule: "), b("the model proposes, code disposes."), r(" A local Gemma model drafts findings as JSON. Deterministic code verifies every quote, number and date, refuses verdict questions before the model is called, and keeps all data on the device.")]));
children.push(table([
  ["Item", "Choice"],
  ["Model", "Gemma 4 E4B (edge-class), Q4_K_M 4-bit GGUF, 4.98 GB (licence per the official model card); fallback E2B"],
  ["Runtime", "llama.cpp llama-server on 127.0.0.1 (loopback only), 8k context; every layer on the demo laptop's RTX 4060 (8 GB)"],
  ["Retrieval", "BM25 + all-MiniLM-L6-v2 (ONNX, no PyTorch) in a FAISS index, in memory only"],
  ["UI", "Gradio on 127.0.0.1, analytics off, no CDN (design agreed, build in progress)"],
  ["Stack", "Python 3.11+, pinned dependencies, MIT licence, 137 tests in CI (Ubuntu + Windows)"],
  ["Scope", "English; text PDF and .txt; rental and employment agreements"],
], [2400, W - 2400]));

// 2. Problem
children.push(h1("2  Problem and Users"));
children.push(p("People sign rental agreements and job offers without fully understanding them, and a lawyer for every first question is not practical. Generic chatbots invent clauses, answer from general knowledge and sound certain. Uploading a private contract to a cloud service is a privacy risk in itself."));
children.push(bullet([b("Users: "), r("tenants, new employees and small-business owners reviewing an agreement before signing.")]));
children.push(bullet([b("Need: "), r("what the document actually says, what it costs them, what is missing or vague, and what to ask a professional.")]));
children.push(bullet([b("Non-goals: "), r("judging validity or enforceability, naming laws as conclusions, recommending “sign” or “don’t sign”, and any cloud call during processing.")]));

// 3. Solution
children.push(h1("3  Proposed Solution"));
children.push(p("The user opens a document in the local UI and gets:"));
children.push(bullet([b("Grounded summary: "), r("every sentence cites the passages it rests on.")]));
children.push(bullet([b("Prioritised findings: "), r("Critical, Important and Informational tiers, ranked by a severity score computed in code. Each finding shows its source passage beside the explanation.")]));
children.push(bullet([b("Labels: "), r("STATED (the text says it), INTERPRETATION (our reading) and CONCERN (worth asking about).")]));
children.push(bullet([b("Coverage report: "), r("which clause types were not found, for example “no termination clause”.")]));
children.push(bullet([b("Document Q&A: "), r("cited answers, or “the document does not appear to say anything about this” when it is silent.")]));
children.push(bullet([b("Escalation panel: "), r("verdict questions are declined with specific advice on which clause to bring, what to ask and which facts matter.")]));

// 4. Architecture
children.push(h1("4  Architecture"));
children.push(p("Six stages, all on the user's device. There is no network access at run time; downloads happen only at setup."));
children.push(table([
  ["#", "Stage", "What happens"],
  ["1", "Ingest", "pypdf / pdfplumber produce text and a page map, then clause-aware chunks with stable IDs (p3.c2) and offsets. Empty, encrypted or scanned files get a clear warning"],
  ["2", "Index", "BM25 and local embeddings feed a FAISS index in one session directory"],
  ["3", "Analyse", "Gemma extracts findings as JSON. Document text is passed as delimited data, never as instructions. Malformed JSON is retried twice, then skipped"],
  ["4", "Verify", "Code only: the quote must be a substring of the cited passage after normalisation, and numbers and dates in the explanation must appear in the quote. Failures are dropped or marked unverified"],
  ["5", "Safety", "Labels, ambiguity and jurisdiction flags, silence logic, verdict refusal, a forbidden-phrase filter and a fixed disclaimer"],
  ["6", "UI", "127.0.0.1 only: summary, findings, clause view with the source beside each explanation, and Q&A"],
], [500, 1300, W - 1800]));

// 5. Safety
children.push(h1("5  Grounding and Safety"));
children.push(bullet([b("Verified quotes: "), r("an exact normalised match passes. A near match (≥ 0.95) is replaced with the real source span, and anything else is dropped. The summary is checked sentence by sentence the same way.")]));
children.push(bullet([b("No number drift: "), r("“30 days” explained as “3 months” is caught and hidden.")]));
children.push(bullet([b("Honest silence: "), r("a low retrieval score with no verified citation gives a fixed silent reply, never an answer from general knowledge.")]));
children.push(bullet([b("Refusal in code: "), r("“is this enforceable?” and “should I sign?” are classified and declined before Gemma is called.")]));
children.push(bullet([b("Uncertainty: "), r("vague terms (“reasonable”, “sole discretion”), blanks and conflicting clauses are flagged as ambiguous. Deposits, notice periods and non-competes are flagged as jurisdiction-dependent, with no conclusion.")]));
children.push(bullet([b("Prompt injection: "), r("document text is untrusted data in delimited blocks, and the output is a fixed JSON schema. Instruction-like text is ignored and flagged to the user.")]));

// 6. Privacy
children.push(h1("6  Privacy and Proof"));
children.push(p("Nothing private leaves the device: not the file, text, chunks, embeddings, summaries, answers or questions. We prove this in three independent ways, with recorded evidence:"));
children.push(table([
  ["Layer", "Test"],
  ["1. Cannot connect", "run_offline.ps1 refuses to run while online, then repeats the monitored run in Airplane mode (Linux: network namespace). To record on the demo laptop."],
  ["2. Does not try", "PASS. An in-process audit-hook guard plus an OS connection monitor during a full run with retrieval: 12 attempts, all to 127.0.0.1:8080, none outside; a canary string from the document was found in none of the 17 files touched."],
  ["3. No code that connects", "Clean. The audit of our code and 43 runtime dependencies, profiled on a real session, finds network code only in our loopback model client; 4 dormant numpy hits are never called."],
], [2600, W - 2600]));
children.push(p("In addition, telemetry kill-switches are set in code (HF_HUB_OFFLINE, TRANSFORMERS_OFFLINE, HF_HUB_DISABLE_TELEMETRY, DO_NOT_TRACK), and the model URL is refused unless it points at this machine. Embeddings and the retrieval index stay in memory. Logs hold timings and counts only, never document text."));

// 7. Gemma
children.push(h1("7  Gemma Integration"));
children.push(p("Gemma does the central task: clause extraction, plain-language explanation, labelling, summary and Q&A, all locally. It is called through the chat endpoint so the Gemma chat template is applied. On the demo laptop (RTX 4060, 8 GB VRAM, 24 GB RAM) the 4.98 GB E4B model runs entirely on the GPU. Gemma 4's reasoning mode is switched off so answers come back as plain JSON. Retrieval limits Q&A prompts to the top 3 passages. Measured on a CPU-only laptop (about 5 tokens per second): 11 of 11 findings on the sample rental passed verification, a full analysis took 110–265 s and each question 15–30 s. GPU numbers will be recorded on the demo laptop. The fallback ladder is Q3_K_S, then E2B."));

// 8. Compliance
children.push(h1("8  Mandatory Requirements"));
children.push(table([
  ["ID", "Requirement", "Delivered by", "Status"],
  ["L1", "Local ingestion (PDF / .txt)", "ingest.py", "Done"],
  ["L2", "On-device extraction and interpretation", "ingest.py + analyze.py", "Done"],
  ["L3", "Plain-language summaries and explanations", "analyze.py prompts", "Done"],
  ["L4", "Obligations, rights, deadlines, penalties, termination", "Finding kinds + coverage", "Done"],
  ["L5", "Answers backed by identifiable passages", "Clause IDs + verify.py + retrieve.py", "Done"],
  ["L6", "Stated vs interpretation", "Labels + downgrade rules", "Done"],
  ["L7", "Ambiguity, missing evidence, jurisdiction", "Flags + silence logic", "Done"],
  ["L8", "Refuse verdicts, recommend a lawyer", "Classifier + escalation", "Done"],
  ["L9", "Demonstrable privacy", "privacy/ three-layer proof", "Layers 2–3 recorded; offline run on demo laptop"],
  ["L10", "Meaningful Gemma use, reproducible OSS", "llm.py, MIT licence, pinned deps, CI", "Done"],
], [600, 3500, 2900, W - 7000]));
children.push(p("Gates G1–G5 (public repo and licence, no paid services or secrets, a real system, datasets disclosed) and L1–L4 (local Gemma, nothing leaves the device, no fabrication, not legal advice) are all met in the repository today. The user interface is still being built."));

// 9. Evaluation
children.push(h1("9  Evaluation Plan"));
children.push(bullet([b("Samples we write: "), r("clear and vague rentals, standard and conflicting employment contracts, an injected document, a complex layout and malformed files. One held-out document and 1–2 public templates are never used for tuning.")]));
children.push(bullet([b("Metrics: "), r("quote-verification pass rate, citation accuracy, human-scored meaning accuracy (X/10 clauses), silence and refusal correctness, injection results, latency and peak RAM.")]));
children.push(bullet([b("Today: "), r("137 deterministic tests pass in CI. A real Gemma run on the sample rental produced 11 findings, all 11 verified, with correct silent and refusal answers. Retrieval finds the right clause in the top 3 for 15 of 15 handwritten questions. Malformed files (empty, damaged, password-protected, scanned) give one clear message each.")]));

// 10. Team and plan
children.push(h1("10  Team and Timeline"));
children.push(table([
  ["Lane", "Owns"],
  ["A: Gemma + analysis", "llm.py, prompts, analyze.py: extraction, explanation, summary, Q&A, long documents"],
  ["B: Ingest + privacy", "ingest.py, retrieve.py, privacy/: parsing, chunking, index, offline run, monitor, audit, threat model"],
  ["C: Grounding + safety", "verify.py, safety.py, injection.py: verifier, labels, flags, refusal, escalation, filter"],
  ["D: UI, eval, docs", "app/, bench/, samples, README, CI, demo recording, submission"],
], [2600, W - 2600]));
children.push(p([b("12-hour checkpoints: "), r("H1 model locked · H4 local Gemma, ingest and verifier working · H6 end-to-end on two document types, scope cuts decided · H9 safety cases pass and the offline run is recorded · H10.5 code freeze. Scope cuts, in order: service agreements, structured extraction, optional extras, CUAD, free-form Q&A.")]));

// 11. Risks
children.push(h1("11  Key Risks"));
children.push(table([
  ["Risk", "Mitigation"],
  ["Model invents quotes (score capped at 40)", "The code verifier drops anything not in the source, summary included"],
  ["Output reads as legal advice (cap)", "Refusal in code, labels, a forbidden-phrase filter and a fixed disclaimer"],
  ["A dependency phones home (cap)", "Kill-switches, dependency audit, offline run and monitor log"],
  ["Gemma too slow on laptops", "Top-3 retrieval, E2B or lower-quant fallback, a recorded backup demo"],
  ["Poor PDF extraction or long documents", "Two parsers, clause-aware chunking, a coverage report and honest warnings"],
], [3800, W - 3800]));

// 12. Limitations
children.push(h1("12  Limitations"));
children.push(bullet("English only; text PDF and .txt. Scanned PDFs are detected and reported, not OCR'd."));
children.push(bullet("Tested on rental and employment agreements only."));
children.push(bullet("A relevant clause that retrieval ranks low yields a silent answer, never a wrong one. This is deliberate."));
children.push(bullet("Privacy covers the software, not a compromised OS or a malicious model file."));

// 13. Contribution
children.push(h1("13  Main Technical Contribution"));
children.push(p("A reusable grounding layer for on-device legal assistants. It combines clause-aware passage IDs, a deterministic quote-and-number verifier applied to findings and summaries alike, refusal enforced in code rather than in the prompt, and a reproducible three-layer privacy proof. Together these show that a small edge model can be used on legal text, because code, not the model, decides what reaches the user."));

// ---------- document ----------

const doc = new Document({
  numbering: {
    config: [
      { reference: "bul", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 460, hanging: 260 } } } }] },
      { reference: "num", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 460, hanging: 260 } } } }] },
    ],
  },
  styles: { default: { document: { run: { font: "Calibri", size: 21, color: INK } } } },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1300, bottom: 1300, left: 1300, right: 1300 } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
      children: [new TextRun({ text: "LegalLens: Solution Proposal", size: 16, color: MUTED })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [
      new TextRun({ text: "Page ", size: 16, color: MUTED }),
      new TextRun({ children: [PageNumber.CURRENT], size: 16, color: MUTED }),
      new TextRun({ text: " of ", size: 16, color: MUTED }),
      new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 16, color: MUTED }),
    ] })] }) },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  const out = path.join(__dirname, "docs", "LegalLens_Solution_Proposal.docx");
  fs.writeFileSync(out, buf);
  console.log("WROTE", out, buf.length, "bytes");
});
