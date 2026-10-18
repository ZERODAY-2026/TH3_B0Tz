"""Layer 3 of the privacy proof: find every piece of code that *could* talk
to the network, in our code and in every installed runtime dependency.

    python privacy/audit_deps.py --out docs/examples/privacy/dependency_audit.md

It resolves the runtime dependency tree from requirements.txt (dev-only
packages excluded), searches each package's Python source for network
clients, DNS, raw sockets and telemetry/update-check code, lists compiled
modules it cannot read as text, and records which network-capable modules
the app actually imports at run time. Every hit is reviewed by a person and
the verdict goes in privacy/THREAT_MODEL.md; this script only finds them.
"""
from __future__ import annotations

import argparse
import importlib.metadata as md
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEV_ONLY = {"pytest", "pymupdf"}

NET_IMPORT = re.compile(r"^\s*(?:import|from)\s+(requests|httpx|aiohttp|urllib3|websockets?|socket|ssl|"
                        r"ftplib|smtplib|poplib|imaplib|telnetlib|http\.client|urllib\.request|"
                        r"xmlrpc\.client|asyncio\.streams)\b")
NET_CALL = re.compile(r"\b(urlopen|create_connection|socket\.socket|getaddrinfo|gethostbyname|"
                      r"requests\.(?:get|post|put|request)|httpx\.(?:get|post|Client)|HTTPSConnection|HTTPConnection)\b")
TELEMETRY = re.compile(r"\b(telemetry|analytics|posthog|sentry_sdk|mixpanel|opentelemetry|"
                       r"check_for_updates?|update_check|phone_home)\b|"
                       r"^\s*(?:import|from)\s+amplitude\b", re.I)   # the SDK, not the word in docs
NETWORK_MODULES = ["socket", "ssl", "http.client", "urllib.request", "urllib3", "requests", "httpx", "aiohttp"]


def _requirement_parser():
    try:
        from packaging.requirements import Requirement
    except ImportError:                                  # pip always vendors it
        from pip._vendor.packaging.requirements import Requirement
    return Requirement


def runtime_roots() -> list[str]:
    names = []
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            name = re.split(r"[<>=!~;\[ ]", line, maxsplit=1)[0]
            if name.lower() not in DEV_ONLY:
                names.append(name)
    return names


def closure(roots: list[str]) -> list[md.Distribution]:
    Requirement = _requirement_parser()
    seen: dict[str, md.Distribution] = {}
    todo = list(roots)
    while todo:
        name = todo.pop()
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            continue
        key = dist.metadata["Name"].lower()
        if key in seen:
            continue
        seen[key] = dist
        for req in dist.requires or []:
            r = Requirement(req)
            if r.marker is None or r.marker.evaluate({"extra": ""}):
                todo.append(r.name)
    return sorted(seen.values(), key=lambda d: d.metadata["Name"].lower())


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    hits = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return hits
    for n, line in enumerate(lines, start=1):
        for kind, rx in (("import", NET_IMPORT), ("call", NET_CALL), ("telemetry", TELEMETRY)):
            if rx.search(line):
                hits.append((n, kind, line.strip()[:110]))
                break
    return hits


def _norm(path) -> str:
    return str(Path(path).resolve()).lower()


def scan_dist(dist: md.Distribution, loaded: set[str]) -> dict:
    py, binaries, hits, used = 0, [], [], False
    for f in dist.files or []:
        p = Path(dist.locate_file(f))
        live = _norm(p) in loaded
        used = used or live
        if p.suffix == ".py":
            py += 1
            hits += [(f"{f}:{n}", kind, text, live) for n, kind, text in scan_file(p)]
        elif p.suffix in (".pyd", ".so", ".dll", ".dylib"):
            binaries.append(str(f))
    return {"name": dist.metadata["Name"], "version": dist.version, "py_files": py,
            "binaries": binaries, "hits": hits, "used": used}


def scan_own_code(loaded: set[str]) -> dict:
    hits, files = [], sorted((ROOT / "legallens").rglob("*.py"))
    for p in files:
        live = _norm(p) in loaded
        hits += [(f"{p.relative_to(ROOT).as_posix()}:{n}", kind, text, live) for n, kind, text in scan_file(p)]
    return {"name": "legallens (our code)", "version": "-", "py_files": len(files), "binaries": [],
            "hits": hits, "used": True}


# Exercise the code paths a real session uses (ingest a PDF, build the hybrid
# index, retrieve, load the model client) and report what got imported.
_PROFILE = """
import json, sys
from pathlib import Path
from legallens.ingest import ingest
from legallens.retrieve import retrieve, dense_available
import legallens.analyze, legallens.verify, legallens.safety, legallens.injection, legallens.priority, legallens.llm
doc = ingest("data/samples/rental_clear.pdf")
retrieve(doc, "What is the notice period?")
files = [str(Path(m.__file__).resolve()).lower() for m in list(sys.modules.values())
         if getattr(m, "__file__", None)]
print(json.dumps({"files": files, "dense": dense_available(),
                  "net": [m for m in %r if m in sys.modules]}))
""" % (NETWORK_MODULES,)


def runtime_profile() -> dict:
    res = subprocess.run([sys.executable, "-c", _PROFILE], cwd=ROOT, capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(f"runtime profile failed:\n{res.stderr}")
    data = json.loads(res.stdout.strip().splitlines()[-1])
    data["files"] = set(data["files"])
    return data


def render(own: dict, deps: list[dict], profile: dict) -> str:
    live_total = sum(1 for d in deps for h in d["hits"] if h[3])
    out = ["# Dependency network audit", "",
           f"Generated by `privacy/audit_deps.py` with Python {sys.version.split()[0]} on {sys.platform}.",
           "A hit means the code *could* use the network, not that it does. **Live** means the file",
           "was actually imported during a real session (ingest a PDF, build the retrieval index,",
           f"retrieve; dense embeddings {'on' if profile['dense'] else 'OFF: model not downloaded'}).",
           "Hits in files that are never imported cannot run. Every live hit is reviewed in",
           "`privacy/THREAT_MODEL.md`; the monitored and offline runs show what actually happens.", "",
           f"**Live hits in dependencies: {live_total}.**", "",
           "## Summary", "",
           "| Package | Version | Imported at run time | .py files | Hits | Live hits | Compiled modules |",
           "|---|---|---|---|---|---|---|"]
    for d in [own] + deps:
        live = sum(1 for h in d["hits"] if h[3])
        out.append(f"| {d['name']} | {d['version']} | {'yes' if d['used'] else 'no'} | {d['py_files']} | "
                   f"{len(d['hits'])} | {live} | {len(d['binaries'])} |")
    out += ["", "## Standard-library network modules loaded at run time", "",
            ", ".join(f"`{m}`" for m in profile["net"]) if profile["net"] else "None.",
            "(`urllib.request` for the loopback model client; it imports the others.)", ""]
    for d in [own] + deps:
        live = [h for h in d["hits"] if h[3]]
        if not live and not (d["used"] and d["binaries"]):
            continue
        out += [f"## {d['name']} {d['version']}", ""]
        if live:
            out += ["| Where | Kind | Line |", "|---|---|---|"]
            for where, kind, text, _ in live[:25]:
                cell = text.replace("|", "\\|")
                out.append(f"| `{where}` | {kind} | `{cell}` |")
            out.append("")
        if d["used"] and d["binaries"]:
            out += [f"Compiled modules (not text-scanned): {', '.join(f'`{b}`' for b in d['binaries'][:8])}"
                    + (" …" if len(d["binaries"]) > 8 else ""), ""]
    dormant = [(d["name"], len(d["hits"])) for d in deps if d["hits"] and not any(h[3] for h in d["hits"])]
    if dormant:
        out += ["## Hits only in files never imported", "",
                ", ".join(f"{n} ({c})" for n, c in dormant) + ".", "",
                "Examples: FAISS's optional RPC helper, onnxruntime's model-conversion scripts, and the",
                "Hugging Face download client that `tokenizers` depends on but that LegalLens never calls",
                "(it loads the tokenizer from a local file).", ""]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Audit LegalLens and its runtime dependencies for network code.")
    ap.add_argument("--out", help="write the markdown report here")
    args = ap.parse_args(argv)
    profile = runtime_profile()
    deps = [scan_dist(d, profile["files"]) for d in closure(runtime_roots())]
    report = render(scan_own_code(profile["files"]), deps, profile)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(report + "\n", encoding="utf-8")
    total = sum(len(d["hits"]) for d in deps)
    live = sum(1 for d in deps for h in d["hits"] if h[3])
    print(f"audited {len(deps)} runtime dependencies + our code: {total} hit(s), {live} in code imported at run time")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
