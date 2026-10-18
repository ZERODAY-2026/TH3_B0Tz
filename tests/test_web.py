"""tests/test_web.py -- the local web UI server (app/web_server.py).

Starts the real HTTP server on an ephemeral 127.0.0.1 port with the pipeline
functions replaced by stubs, so no model server is needed. ingest() is the
real one in the sample-file test.
"""
from __future__ import annotations

import http.client
import json
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from app import web_server
from app.web_server import WebApp, make_server, safe_filename
from legallens.llm import LLMError
from legallens.types import Analysis, Citation, Document, Finding, Passage, Reply

ROOT = Path(__file__).resolve().parent.parent
HDR = {"X-LegalLens": "1"}


def _doc(name="test.txt"):
    return Document(doc_id="d1", source_name=name,
                    passages=[Passage(id="p1.c1", page=1, heading="Rent",
                                      text="Rent is Rs. 10,000 per month.", start=0, end=29)])


def _analysis(doc):
    return Analysis(
        summary="Rent is Rs. 10,000 [p1.c1].", summary_citations=["p1.c1"],
        findings=[Finding(id="f1", kind="obligation", party="Tenant",
                          plain_text="Pay Rs. 10,000.", quote="Rent is Rs. 10,000 per month.",
                          passage_id="p1.c1", label="STATED", confidence="high")],
        coverage={"found": ["obligation"], "not_found": ["right"]})


def _reply(doc, q):
    return Reply(text="Rs. 10,000 [p1.c1].",
                 citations=[Citation("p1.c1", "Rent is Rs. 10,000 per month.")])


@contextmanager
def running(app=None):
    app = app or WebApp(ingest_fn=lambda p: _doc(Path(p).name),
                        analyze_fn=_analysis, ask_fn=_reply)
    server = make_server(0, app)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    port = server.server_address[1]
    try:
        yield app, port
    finally:
        server.shutdown()
        server.server_close()


def call(port, method, path, body=None, headers=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = dict(headers or {})
    if host:
        h["Host"] = host
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    raw = r.read()
    conn.close()
    try:
        return r.status, json.loads(raw), r
    except ValueError:
        return r.status, raw, r


def wait_for(port, want, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        st = call(port, "GET", "/api/state")[1]
        if st["status"] == want:
            return st
        time.sleep(0.02)
    raise AssertionError(f"never reached {want}: {st['status']}")


def upload(port, data=b"Rent is Rs. 10,000 per month.", name="test.txt"):
    return call(port, "POST", "/api/analyze", data, {**HDR, "X-Filename": name})


# -- static page ---------------------------------------------------------------

def test_server_binds_loopback_only():
    with running() as (_, port):
        pass
    srv = make_server(0)
    try:
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.server_close()


def test_index_served_with_locked_down_headers():
    with running() as (_, port):
        status, body, r = call(port, "GET", "/")
        assert status == 200 and b"LegalLens" in body
        csp = r.getheader("Content-Security-Policy")
        assert "default-src 'none'" in csp and "connect-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert r.getheader("Cache-Control") == "no-store"


def test_page_has_no_external_resources():
    html = (ROOT / "app" / "web" / "index.html").read_text(encoding="utf-8")
    assert not re.findall(r'(?:src|href)\s*=\s*["\']\s*(?:https?:)?//', html)
    assert not re.findall(r"url\(\s*[\"']?(?:https?:)?//", html)
    assert "@import" not in html
    for banned in ("googleapis", "cdn.", "unpkg", "jsdelivr", "analytics"):
        assert banned not in html.lower()


def test_page_keeps_the_permanent_disclaimer():
    html = (ROOT / "app" / "web" / "index.html").read_text(encoding="utf-8")
    assert "Not legal advice." in html and 'class="disclaimer"' in html


# -- request guards ------------------------------------------------------------

def test_foreign_host_header_refused():
    with running() as (_, port):
        status, _, _ = call(port, "GET", "/api/state", host="evil.example")
        assert status == 403
        status, _, _ = call(port, "GET", "/", host=f"evil.example:{port}")
        assert status == 403


def test_localhost_name_is_accepted():
    with running() as (_, port):
        status, _, _ = call(port, "GET", "/api/state", host=f"localhost:{port}")
        assert status == 200


def test_post_needs_custom_header():
    with running() as (_, port):
        status, _, _ = call(port, "POST", "/api/clear", b"")
        assert status == 403
        status, _, _ = call(port, "POST", "/api/analyze", b"x", {"X-Filename": "a.txt"})
        assert status == 403


def test_post_from_other_origin_refused():
    with running() as (_, port):
        status, _, _ = call(port, "POST", "/api/clear", b"",
                            {**HDR, "Origin": "https://evil.example"})
        assert status == 403
        status, _, _ = call(port, "POST", "/api/clear", b"",
                            {**HDR, "Origin": f"http://127.0.0.1:{port}"})
        assert status == 200


def test_unknown_paths_404_and_no_file_serving():
    with running() as (_, port):
        for p in ("/nope", "/app/web_server.py", "/../README.md", "/api/ask"):
            status, _, _ = call(port, "GET", p)
            assert status == 404


# -- analysis flow -------------------------------------------------------------

def test_idle_state():
    with running() as (_, port):
        st = call(port, "GET", "/api/state")[1]
        assert st["status"] == "idle" and st["doc"] is None and st["thread"] == []


def test_upload_analyse_and_read_back():
    with running() as (_, port):
        status, body, _ = upload(port)
        assert status == 202 and body["status"] == "busy"
        st = wait_for(port, "ready")
        assert st["doc"]["source_name"] == "test.txt"
        assert st["doc"]["passages"][0]["id"] == "p1.c1"
        assert st["analysis"]["findings"][0]["kind"] == "obligation"
        assert st["analysis"]["coverage"]["not_found"] == ["right"]


def test_real_ingest_on_sample_file():
    app = WebApp(analyze_fn=_analysis, ask_fn=_reply)  # real ingest()
    with running(app) as (_, port):
        data = (ROOT / "data" / "samples" / "rental_clear.txt").read_bytes()
        assert upload(port, data, "rental_clear.txt")[0] == 202
        st = wait_for(port, "ready")
        assert st["doc"]["source_name"] == "rental_clear.txt"
        assert len(st["doc"]["passages"]) >= 3 and st["doc"]["pages"] >= 1


def test_unreadable_file_reports_ingest_warning():
    def ingest(path):
        return Document(doc_id="x", source_name="scan.pdf", passages=[],
                        extraction_warnings=["This PDF looks like a scanned image."])
    app = WebApp(ingest_fn=ingest, analyze_fn=_analysis, ask_fn=_reply)
    with running(app) as (_, port):
        upload(port, b"%PDF-", "scan.pdf")
        st = wait_for(port, "error")
        assert st["error"]["kind"] == "unreadable"
        assert "scanned" in st["error"]["message"]
        assert st["doc"] is None and st["analysis"] is None


def test_model_down_is_a_clear_error_not_a_crash():
    def analyze(doc):
        raise LLMError("local model unreachable")
    app = WebApp(ingest_fn=lambda p: _doc(), analyze_fn=analyze, ask_fn=_reply)
    with running(app) as (_, port):
        upload(port)
        st = wait_for(port, "error")
        assert st["error"]["kind"] == "model" and "unreachable" in st["error"]["message"]
        assert call(port, "GET", "/api/state")[0] == 200  # server still alive


def test_unexpected_exception_is_contained():
    def analyze(doc):
        raise ValueError("boom")
    app = WebApp(ingest_fn=lambda p: _doc(), analyze_fn=analyze, ask_fn=_reply)
    with running(app) as (_, port):
        upload(port)
        assert wait_for(port, "error")["error"]["kind"] == "failed"


def test_second_upload_while_busy_is_refused():
    gate = threading.Event()

    def analyze(doc):
        gate.wait(5)
        return _analysis(doc)
    app = WebApp(ingest_fn=lambda p: _doc(), analyze_fn=analyze, ask_fn=_reply)
    with running(app) as (_, port):
        assert upload(port)[0] == 202
        wait_for(port, "busy")
        assert upload(port)[0] == 409
        gate.set()
        wait_for(port, "ready")


def test_clear_while_busy_discards_the_late_result():
    gate = threading.Event()

    def analyze(doc):
        gate.wait(5)
        return _analysis(doc)
    app = WebApp(ingest_fn=lambda p: _doc(), analyze_fn=analyze, ask_fn=_reply)
    with running(app) as (_, port):
        upload(port)
        wait_for(port, "busy")
        assert call(port, "POST", "/api/clear", b"", HDR)[0] == 200
        gate.set()
        time.sleep(0.2)
        st = call(port, "GET", "/api/state")[1]
        assert st["status"] == "idle" and st["doc"] is None


def test_oversize_upload_refused_before_reading():
    old = web_server.MAX_UPLOAD_BYTES
    web_server.MAX_UPLOAD_BYTES = 10
    try:
        with running() as (_, port):
            status, _, _ = upload(port, b"x" * 50)
            assert status == 413
    finally:
        web_server.MAX_UPLOAD_BYTES = old


def test_upload_filename_is_sanitised_and_decoded():
    seen = []

    def ingest(path):
        seen.append(Path(path).name)
        return _doc(Path(path).name)
    app = WebApp(ingest_fn=ingest, analyze_fn=_analysis, ask_fn=_reply)
    with running(app) as (_, port):
        upload(port, name="..%2F..%2Fetc%2Fpass%20wd%3F.txt")
        wait_for(port, "ready")
        assert seen == ["pass wd_.txt"]


def test_safe_filename():
    assert safe_filename("../../x/y.pdf") == "y.pdf"
    assert safe_filename("C:\\Users\\me\\lease.PDF") == "lease.PDF"
    assert safe_filename("") == "document.txt"
    assert safe_filename(None) == "document.txt"
    assert safe_filename("a<b>|c.txt") == "a_b__c.txt"
    assert len(safe_filename("a" * 500 + ".txt")) <= 120


def test_upload_is_not_left_on_disk():
    seen = []

    def ingest(path):
        seen.append(Path(path))
        return _doc()
    app = WebApp(ingest_fn=ingest, analyze_fn=_analysis, ask_fn=_reply)
    with running(app) as (_, port):
        upload(port)
        wait_for(port, "ready")
        assert seen and not seen[0].exists() and not seen[0].parent.exists()


# -- questions -----------------------------------------------------------------

def test_ask_needs_a_document():
    with running() as (_, port):
        status, body, _ = call(port, "POST", "/api/ask", json.dumps({"question": "hi"}).encode(), HDR)
        assert status == 409 and body["error"]["kind"] == "no_document"


def test_ask_roundtrip_and_thread():
    with running() as (_, port):
        upload(port)
        wait_for(port, "ready")
        status, body, _ = call(port, "POST", "/api/ask",
                               json.dumps({"question": "How much is rent?"}).encode(), HDR)
        assert status == 200
        assert body["q"] == "How much is rent?" and body["citations"][0]["passage_id"] == "p1.c1"
        assert body["silent"] is False and body["refused"] is False
        st = call(port, "GET", "/api/state")[1]
        assert [t["q"] for t in st["thread"]] == ["How much is rent?"]


def test_ask_validation():
    with running() as (_, port):
        upload(port)
        wait_for(port, "ready")
        for raw in (b"", b"not json", json.dumps({"question": "  "}).encode(),
                    json.dumps({"question": "x" * 5000}).encode()):
            assert call(port, "POST", "/api/ask", raw, HDR)[0] == 400


def test_ask_model_down_is_502_and_server_survives():
    def ask(doc, q):
        raise LLMError("down")
    app = WebApp(ingest_fn=lambda p: _doc(), analyze_fn=_analysis, ask_fn=ask)
    with running(app) as (_, port):
        upload(port)
        wait_for(port, "ready")
        status, body, _ = call(port, "POST", "/api/ask",
                               json.dumps({"question": "q"}).encode(), HDR)
        assert status == 502 and body["error"]["kind"] == "model"
        assert call(port, "GET", "/api/state")[1]["thread"] == []


def test_clear_forgets_everything():
    with running() as (_, port):
        upload(port)
        wait_for(port, "ready")
        call(port, "POST", "/api/ask", json.dumps({"question": "q"}).encode(), HDR)
        assert call(port, "POST", "/api/clear", b"", HDR)[0] == 200
        st = call(port, "GET", "/api/state")[1]
        assert st["status"] == "idle" and st["doc"] is None and st["thread"] == []
        assert call(port, "POST", "/api/ask", json.dumps({"question": "q"}).encode(), HDR)[0] == 409


def test_server_writes_no_access_log():
    # log_message is a deliberate no-op: nothing derived from a request is printed.
    assert web_server.Handler.log_message(object(), "%s", "x") is None
