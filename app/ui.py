"""LegalLens UI — Person D lane.

Runs on 127.0.0.1 ONLY. No CDN, no remote fonts, no analytics.
Privacy kill-switches are re-asserted here in code, because launch-script
env vars get lost when someone runs `python -m app.ui` directly.

Requires the real pipeline (legallens.analyze) — no stub mode. For a model
server that is not running, ask()/analyze() errors surface as clear UI
messages rather than stack traces.
"""

from __future__ import annotations

import os

# --- privacy kill-switches (PLAN §4) — set BEFORE importing gradio -------
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
os.environ.setdefault("DO_NOT_TRACK", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import gradio as gr

from app import contracts
from legallens.llm import LLMError

HOST = "127.0.0.1"  # hardcoded, not just documented (PLAN §6.5)

LABEL_STYLES = {
    "STATED": ("badge badge-stated", "STATED"),
    "INTERPRETATION": ("badge badge-interpretation", "OUR READING"),
    "CONCERN": ("badge badge-concern", "WORTH ASKING ABOUT"),
}

INJECTION_HINT = "looks like an instruction"

# High-contrast palette; all pairs checked >= 4.5:1 on their backgrounds.
CSS = """
#disclaimer { background:#fff3cd; border:1px solid #b8860b; padding:10px 14px;
  font-size:0.95em; border-radius:8px; }
.badge { display:inline-block; padding:2px 8px; border-radius:10px;
  font-size:0.78em; font-weight:bold; letter-spacing:0.02em; }
.badge-stated { background:#1a5d1a; color:#ffffff; }
.badge-interpretation { background:#8a4b00; color:#ffffff; }
.badge-concern { background:#7a1f1f; color:#ffffff; }
.kind { display:inline-block; padding:2px 8px; border-radius:10px;
  font-size:0.78em; background:#e8e8e8; color:#202020; font-weight:600; }
.quote { background:#f4f7fb; border-left:4px solid #2b5c8a; padding:8px 12px;
  font-style:italic; margin:6px 0; }
.explain { padding:4px 0; }
.passage { color:#444; font-size:0.85em; }
.tier-head { font-size:1.05em; font-weight:700; margin-top:14px;
  border-bottom:2px solid #999; padding-bottom:2px; }
.silent { background:#eef3ee; border-left:4px solid #3a7a3a; padding:10px 12px; }
.refused { background:#f7eefc; border-left:4px solid #6b2fa0; padding:10px 12px; }
.esc { background:#fdf0e7; border-left:4px solid #b05a1e; padding:8px 12px;
  font-size:0.92em; }
.cov-gap { color:#7a1f1f; }
"""


def _label_badge(label: str) -> str:
    cls, text = LABEL_STYLES.get(label, ("badge badge-stated", label))
    return f'<span class="{cls}">{text}</span>'


def _finding_html(f) -> str:
    flags = " · ".join(f.flags) if getattr(f, "flags", None) else ""
    flags_html = f' <span class="passage">[{flags}]</span>' if flags else ""
    esc = ""
    if getattr(f, "escalation_note", None):
        esc = f'<div class="esc">⚖ Ask about this: {f.escalation_note}</div>'
    return f"""
<div class="finding" role="article" aria-label="Finding {f.kind}">
  <div><span class="kind">{f.kind}</span>{flags_html} {_label_badge(f.label)}
    <span class="passage">· passage {f.passage_id} · applies to: {f.party or "unspecified"}</span></div>
  <div class="explain"><p>{f.plain_text}</p></div>
  <div class="quote">“{f.quote}” <span class="passage">— source, {f.passage_id}</span></div>
  {esc}
</div><hr/>"""


def render_analysis(doc, a) -> str:
    parts = [f"<h3>Summary — {doc.source_name}</h3>",
             f"<p>{a.summary}</p>",
             '<p class="passage">Summary rests on passages: '
             + ", ".join(a.summary_citations) + "</p>"]

    if doc.extraction_warnings:
        # injection warnings arrive here too (analyze._scan_for_injection)
        for w in doc.extraction_warnings:
            marker = "🛡" if INJECTION_HINT in w.lower() else "⚠"
            parts.append(f'<div class="refused" role="alert">{marker} {w}</div>')

    t = contracts.tiers(a.findings)
    parts.append("<h3>Findings</h3>")
    for tier in ("Critical", "Important", "Informational"):
        if t[tier]:
            parts.append(f'<div class="tier-head">{tier} ({len(t[tier])})</div>')
            parts.extend(_finding_html(f) for f in t[tier])

    cov = a.coverage or {}
    if cov.get("not_found"):
        parts.append("<h3>What the document does not cover</h3><ul>"
                     + "".join(f'<li class="cov-gap">No {x} clause found</li>'
                               for x in cov["not_found"]) + "</ul>")
    return "\n".join(parts)


def render_reply(r) -> str:
    if r.refused:
        body = (f'<div class="refused" role="alert"><b>This needs a lawyer, not a guess.</b>'
                f'<br/>{r.text}</div>')
    elif r.silent:
        body = (f'<div class="silent" role="status"><b>Not in the document.</b>'
                f'<br/>{r.text}</div>')
    else:
        cites = "".join(
            f'<div class="quote">“{c.quote}” <span class="passage">— {c.passage_id}</span></div>'
            for c in r.citations)
        body = f"<p>{r.text}</p>{cites}"
    esc = (f'<div class="esc">⚖ Suggested next step: {r.escalation_note}</div>'
           if r.escalation_note else "")
    return body + esc


# --- app state ------------------------------------------------------------

_state: dict = {"doc": None}


def on_upload(path):
    if not path:
        return "No file selected.", ""
    try:
        doc, a = contracts.get_analysis(path)
    except LLMError as e:
        return (f'<div class="refused" role="alert">Model server unreachable: {e}. '
                'Start llama-server first (docs/MODEL_SETUP.md).</div>', "")
    except Exception as e:  # noqa: BLE001 — one bad file must not kill the app
        return (f'<div class="refused" role="alert">Could not read this document: {e}</div>', "")
    _state["doc"] = doc
    return render_analysis(doc, a), ""


def on_question(question):
    doc = _state.get("doc")
    if doc is None:
        return "Upload a document first."
    if not question or not question.strip():
        return "Type a question first."
    try:
        r = contracts.get_reply(doc, question.strip())
    except LLMError as e:
        return (f'<div class="refused" role="alert">Model server unreachable: {e}.</div>')
    return render_reply(r)


def on_clear():
    _state["doc"] = None
    return "Session cleared. Upload a document to begin."


def build():
    with gr.Blocks(title="LegalLens", css=CSS) as demo:
        gr.Markdown("## LegalLens — private, on-device document triage")
        gr.Markdown(f'<div id="disclaimer" role="alert">⚠ {contracts.DISCLAIMER}</div>')

        with gr.Row():
            with gr.Column(scale=1):
                file_in = gr.File(label="Upload agreement (.pdf / .txt)",
                                  file_types=[".pdf", ".txt"])
                status = gr.Markdown("")
            with gr.Column(scale=2):
                analysis = gr.HTML(label="Analysis", value="Upload a document to begin.")

        file_in.upload(on_upload, inputs=file_in, outputs=[analysis, status])

        gr.Markdown("### Ask a question about this document")
        q = gr.Text(label="Question",
                    placeholder="e.g. How much notice before I can leave?")
        ask_btn = gr.Button("Ask", variant="primary")
        answer = gr.HTML(label="Answer")

        ask_btn.click(on_question, inputs=q, outputs=answer)
        q.submit(on_question, inputs=q, outputs=answer)

        gr.Markdown(
            "*Everything runs on this machine. The model server and this UI talk only over "
            "loopback (127.0.0.1). Use “Clear session” below to reset this session.*"
        )
        clear_btn = gr.Button("Clear session")
        clear_btn.click(on_clear, outputs=status)
    return demo


if __name__ == "__main__":
    build().launch(server_name=HOST, server_port=7860, show_error=True,
                   show_api=False)
