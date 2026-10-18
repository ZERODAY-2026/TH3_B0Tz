"""Privacy tooling (PLAN_PS2 section 12). The guard is tested in a child
process because audit hooks cannot be removed once installed."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

GUARD_PROBE = r"""
import json, socket
from privacy import netguard
netguard.install("block")
out = {}
try:
    socket.create_connection(("203.0.113.5", 80), timeout=1)   # TEST-NET-3, never routable
    out["outside"] = "connected"
except PermissionError:
    out["outside"] = "blocked"
try:
    socket.getaddrinfo("example.com", 443)
    out["dns"] = "resolved"
except PermissionError:
    out["dns"] = "blocked"
try:
    socket.create_connection(("127.0.0.1", 9), timeout=1)
    out["loopback"] = "connected"
except PermissionError:
    out["loopback"] = "blocked"
except OSError:
    out["loopback"] = "allowed (nothing listening)"
out["summary"] = netguard.summary()
print(json.dumps(out))
"""


def run_probe():
    res = subprocess.run([sys.executable, "-c", GUARD_PROBE], cwd=ROOT, capture_output=True,
                         text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_guard_blocks_outside_connections_and_dns_but_not_loopback():
    out = run_probe()
    assert out["outside"] == "blocked"
    assert out["dns"] == "blocked"
    assert out["loopback"].startswith("allowed")
    s = out["summary"]
    assert s["non_loopback_events"] >= 2
    assert all(e["blocked"] for e in s["non_loopback"])


def test_loopback_classification():
    from privacy.netguard import is_loopback
    assert is_loopback("127.0.0.1") and is_loopback("::1") and is_loopback("localhost")
    assert is_loopback("[::1]")
    assert not is_loopback("10.0.0.5") and not is_loopback("huggingface.co") and not is_loopback(None)


def test_audit_finds_our_only_network_code_in_llm_client():
    sys.path.insert(0, str(ROOT / "privacy"))
    import audit_deps
    own = audit_deps.scan_own_code()
    code_hits = [h for h in own["hits"] if h[1] in ("import", "call")]
    assert code_hits and all(h[0].startswith("legallens/llm.py") for h in code_hits)
    names = {d.metadata["Name"].lower() for d in audit_deps.closure(audit_deps.runtime_roots())}
    assert {"pypdf", "pdfplumber"} <= names and "pytest" not in names


def test_canary_search_sees_utf16_files(tmp_path):
    from privacy.capture import contains
    f = tmp_path / "log.txt"
    marker = "TEST-" + "MARKER-" + "0451"     # built at run time: never the real canary
    f.write_text(f"note {marker} here", encoding="utf-16-le")
    assert contains(f, marker.encode())
    g = tmp_path / "clean.txt"
    g.write_text("nothing to see", encoding="utf-8")
    assert not contains(g, marker.encode())
