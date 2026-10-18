"""LegalLens web UI server: serves app/web/index.html and a small JSON API.

Standard library only (no new dependency, nothing that can reach a network).
Binds to 127.0.0.1 and nothing else. The document, its text and the user's
questions live in this process's memory and are never logged or written to
disk (an upload is parked in a temp folder only while ingest() reads it).

    python -m app.web_server            # http://127.0.0.1:7861
    python -m app.web_server --port 8000

API (all JSON; every POST must carry the header ``X-LegalLens: 1``):

    GET  /api/state    -> status, document, analysis, thread, model info
    POST /api/analyze  -> raw file bytes, header X-Filename; starts a job (202)
    POST /api/ask      -> {"question": "..."}; answers synchronously
    POST /api/clear    -> forget the document and the thread
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import threading
import time
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

# Same kill-switches as app/ui.py: re-asserted in code so running this module
# directly cannot lose them. They are set before any pipeline import.
os.environ.setdefault("DO_NOT_TRACK", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from app import contracts  # noqa: E402
from legallens import ingest as ingest_mod  # noqa: E402
from legallens.llm import LLMError  # noqa: E402

HOST = "127.0.0.1"  # hardcoded, not configurable (PLAN section 6.5)
DEFAULT_PORT = 7861  # Gradio UI keeps 7860
WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_QUESTION_CHARS = 2000
MAX_UPLOAD_BYTES = ingest_mod.MAX_BYTES + 1  # one over, so ingest can say "too big"
CSRF_HEADER = "X-LegalLens"

CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
       "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
       "form-action 'none'; frame-ancestors 'none'")


# ------------------------------------------------------------------ view models

def _max_page(doc) -> int:
    return max((p.page for p in doc.passages), default=0)


def doc_view(doc) -> dict:
    return {
        "doc_id": doc.doc_id,
        "source_name": doc.source_name,
        "pages": _max_page(doc),
        "passages": [{"id": p.id, "page": p.page, "heading": p.heading, "text": p.text}
                     for p in doc.passages],
        "warnings": list(doc.extraction_warnings),
    }


def analysis_view(a) -> dict:
    return {
        "summary": a.summary,
        "summary_citations": list(a.summary_citations),
        "findings": [asdict(f) for f in a.findings],
        "coverage": dict(a.coverage or {}),
    }


def reply_view(r, question: str) -> dict:
    return {
        "q": question,
        "text": r.text,
        "citations": [asdict(c) for c in r.citations],
        "silent": bool(r.silent),
        "refused": bool(r.refused),
        "escalation_note": r.escalation_note,
    }


def safe_filename(name: str | None) -> str:
    """Basename only, tame characters, keeps the extension ingest() relies on."""
    base = os.path.basename((name or "").replace("\\", "/")).strip()
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base)[:120].strip(" .")
    return base or "document.txt"


# ------------------------------------------------------------------ app state

class WebApp:
    """Holds the one open document. The pipeline functions are injectable so
    tests can run without a model server."""

    def __init__(self, ingest_fn=None, analyze_fn=None, ask_fn=None):
        self._ingest = ingest_fn or ingest_mod.ingest
        self._analyze = analyze_fn or contracts.analyze
        self._ask = ask_fn or contracts.get_reply
        self._lock = threading.Lock()
        self._gen = 0  # bumped by clear() so a stale job cannot repopulate state
        self._reset()

    def _reset(self) -> None:
        self.status = "idle"      # idle | busy | ready | error
        self.filename = None
        self.doc = None
        self.analysis = None
        self.thread: list[dict] = []
        self.error: dict | None = None
        self.started = None

    # -- reads --------------------------------------------------------------
    def state(self) -> dict:
        with self._lock:
            out = {"status": self.status, "file": self.filename, "error": self.error,
                   "doc": None, "analysis": None, "thread": list(self.thread)}
            if self.status == "busy" and self.started:
                out["elapsed"] = int(time.time() - self.started)
            if self.status == "ready":
                out["doc"] = doc_view(self.doc)
                out["analysis"] = analysis_view(self.analysis)
            return out

    # -- writes -------------------------------------------------------------
    def start_analysis(self, data: bytes, filename: str) -> bool:
        """Park the upload, run ingest+analyze in a worker. False if busy."""
        with self._lock:
            if self.status == "busy":
                return False
            self._reset()
            self.status = "busy"
            self.filename = filename
            self.started = time.time()
            gen = self._gen
        threading.Thread(target=self._run, args=(data, filename, gen), daemon=True).start()
        return True

    def _run(self, data: bytes, filename: str, gen: int) -> None:
        doc = analysis = error = None
        try:
            with tempfile.TemporaryDirectory(prefix="legallens-") as tmp:
                path = Path(tmp) / filename
                path.write_bytes(data)
                doc = self._ingest(path)
            del data
            if not doc.passages:
                error = {"kind": "unreadable",
                         "message": (doc.extraction_warnings[0] if doc.extraction_warnings
                                     else ingest_mod.WARN_NO_TEXT)}
            else:
                analysis = self._analyze(doc)
        except LLMError as e:
            error = {"kind": "model", "message": str(e)}
        except Exception as e:  # noqa: BLE001 - one bad file must not kill the server
            error = {"kind": "failed", "message": f"Could not analyse this document: {e}"}
        with self._lock:
            if gen != self._gen:
                return  # cleared while running
            if error:
                self.status, self.error = "error", error
            else:
                self.status, self.doc, self.analysis = "ready", doc, analysis

    def ask(self, question: str):
        """Returns (reply_view | None, error_dict | None)."""
        with self._lock:
            doc, ready, gen = self.doc, self.status == "ready", self._gen
        if not ready:
            return None, {"kind": "no_document", "message": "Open a document first."}
        try:
            reply = self._ask(doc, question)
        except LLMError as e:
            return None, {"kind": "model", "message": str(e)}
        view = reply_view(reply, question)
        with self._lock:
            if gen == self._gen:
                self.thread.append(view)
        return view, None

    def clear(self) -> None:
        with self._lock:
            self._gen += 1
            self._reset()


# ------------------------------------------------------------------ HTTP layer

class Handler(BaseHTTPRequestHandler):
    server_version = "LegalLens"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    app: WebApp  # set on the server class

    # No access log: request lines are harmless but logs must never grow
    # anything derived from a document, so we log nothing at all.
    def log_message(self, format, *args):  # noqa: A002
        return

    # -- helpers --------------------------------------------------------------
    def _allowed_hosts(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if self.close_connection:
            self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def _reject(self, code: int, message: str) -> None:
        # A refused POST may leave its body unread; on a keep-alive connection
        # those bytes would be parsed as the next request. Close instead.
        self.close_connection = True
        self._json(code, {"error": {"kind": "request", "message": message}})

    def _guard(self, post: bool) -> bool:
        """DNS-rebinding and cross-site protection. True if the request may proceed."""
        if (self.headers.get("Host") or "").lower() not in self._allowed_hosts():
            self._reject(HTTPStatus.FORBIDDEN, "This UI only answers on 127.0.0.1.")
            return False
        if post:
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc.lower() not in self._allowed_hosts():
                self._reject(HTTPStatus.FORBIDDEN, "Cross-site request refused.")
                return False
            if self.headers.get(CSRF_HEADER) != "1":
                self._reject(HTTPStatus.FORBIDDEN, "Missing request header.")
                return False
        return True

    def _body(self, limit: int) -> bytes | None:
        try:
            n = int(self.headers.get("Content-Length") or "")
        except ValueError:
            self._reject(HTTPStatus.LENGTH_REQUIRED, "Content-Length is required.")
            return None
        if n < 0 or n > limit:
            self._reject(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "That request is too large.")
            return None
        return self.rfile.read(n)

    # -- routes ---------------------------------------------------------------
    def do_GET(self):  # noqa: N802
        if not self._guard(post=False):
            return
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            self._send(HTTPStatus.OK, (WEB_DIR / "index.html").read_bytes(),
                       "text/html; charset=utf-8")
        elif path == "/api/state":
            self._json(HTTPStatus.OK, self.app.state())
        else:
            self._reject(HTTPStatus.NOT_FOUND, "Not found.")

    def do_POST(self):  # noqa: N802
        if not self._guard(post=True):
            return
        path = urlsplit(self.path).path
        if path == "/api/analyze":
            data = self._body(MAX_UPLOAD_BYTES)
            if data is None:
                return
            name = safe_filename(unquote(self.headers.get("X-Filename") or ""))
            if not self.app.start_analysis(data, name):
                self._reject(HTTPStatus.CONFLICT, "An analysis is already running.")
                return
            self._json(HTTPStatus.ACCEPTED, {"status": "busy", "file": name})
        elif path == "/api/ask":
            raw = self._body(64 * 1024)
            if raw is None:
                return
            try:
                question = str(json.loads(raw or b"{}").get("question", "")).strip()
            except (ValueError, AttributeError):
                self._reject(HTTPStatus.BAD_REQUEST, "Send JSON like {\"question\": \"...\"}.")
                return
            if not question:
                self._reject(HTTPStatus.BAD_REQUEST, "Type a question first.")
                return
            if len(question) > MAX_QUESTION_CHARS:
                self._reject(HTTPStatus.BAD_REQUEST, "That question is too long.")
                return
            reply, err = self.app.ask(question)
            if err:
                code = HTTPStatus.CONFLICT if err["kind"] == "no_document" else HTTPStatus.BAD_GATEWAY
                self._json(code, {"error": err})
            else:
                self._json(HTTPStatus.OK, reply)
        elif path == "/api/clear":
            self._body(64 * 1024)
            self.app.clear()
            self._json(HTTPStatus.OK, {"status": "idle"})
        else:
            self._reject(HTTPStatus.NOT_FOUND, "Not found.")


def make_server(port: int = DEFAULT_PORT, app: WebApp | None = None) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": app or WebApp()})
    return ThreadingHTTPServer((HOST, port), handler)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="LegalLens local web UI (127.0.0.1 only)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args(argv)
    server = make_server(args.port)
    print(f"LegalLens UI: http://{HOST}:{server.server_address[1]}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
