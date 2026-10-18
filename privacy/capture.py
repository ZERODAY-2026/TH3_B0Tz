"""Run the full pipeline under the network guard and collect privacy evidence.

    python -m privacy.capture --file data/samples/privacy_canary.txt \
        --out docs/examples/privacy/run-monitored --mode block \
        --canary QZX-CANARY-41907 --server-log path/to/llama-server.log

What it does, in one process:
  1. installs privacy.netguard (audit hooks) in record or block mode;
  2. ingest() -> analyze() -> three ask() calls (answerable, silent, verdict);
  3. records every network event the process attempted;
  4. lists files created or modified anywhere under the temp dir, the home
     cache dirs and the project during the run, and searches them (and the
     llama-server log, if given) for the canary string from the document.

Nothing document-derived is printed to stdout, so console capture cannot
leak it either. The analysis itself is written to OUT/analysis.json: OUT is
the one place document-derived text is allowed to land. Exit code 0 means
no non-loopback network event and no canary outside OUT.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from privacy import netguard

PROJECT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "node_modules", "models", "__pycache__", ".pytest_cache"}
MAX_SCAN_BYTES = 20 * 1024 * 1024


def watched_dirs() -> list[Path]:
    home = Path.home()
    dirs = [Path(tempfile.gettempdir()), home / ".cache", PROJECT]
    for env in ("LOCALAPPDATA", "APPDATA", "XDG_CACHE_HOME"):
        if os.environ.get(env):
            dirs.append(Path(os.environ[env]) / "LegalLens")
    return [d for d in dirs if d.exists()]


def changed_files(since: float, exclude: Path) -> list[Path]:
    out = []
    for root in watched_dirs():
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                p = Path(dirpath) / name
                try:
                    if p.stat().st_mtime >= since and exclude not in p.resolve().parents:
                        out.append(p)
                except OSError:
                    continue
    return sorted(set(out))


def contains(path: Path, needle: bytes) -> bool:
    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            return False
        data = path.read_bytes()
    except OSError:
        return False
    return needle in data or needle.decode().encode("utf-16-le") in data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", choices=["record", "block"], default="block")
    ap.add_argument("--canary", required=True, help="distinctive string that appears in the document")
    ap.add_argument("--server-log", help="llama-server log to search for the canary")
    args = ap.parse_args(argv)

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    started = time.time() - 1          # filesystem mtime resolution slack

    netguard.install(args.mode)        # before importing the app, so imports are watched too
    from legallens.analyze import analyze, ask
    from legallens.ingest import ingest

    timings, result = {}, {}
    t = time.perf_counter()
    doc = ingest(args.file)
    timings["ingest_s"] = round(time.perf_counter() - t, 2)
    t = time.perf_counter()
    analysis = analyze(doc)
    timings["analyze_s"] = round(time.perf_counter() - t, 1)
    replies = {}
    for q in ("What is the notice period?", "Can I keep a pet?", "Is the late fee enforceable?"):
        t = time.perf_counter()
        r = ask(doc, q)
        timings[f"ask: {q}"] = round(time.perf_counter() - t, 1)
        replies[q] = asdict(r)
    result = {"document": {"source_name": doc.source_name, "passages": len(doc.passages),
                           "warnings": doc.extraction_warnings},
              "analysis": asdict(analysis), "replies": replies}
    (out / "analysis.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    net = netguard.summary()
    needle = args.canary.encode()
    touched = changed_files(started, exclude=out)
    leaks = [str(p) for p in touched if contains(p, needle)]
    if args.server_log and contains(Path(args.server_log), needle):
        leaks.append(f"{args.server_log} (llama-server log)")

    report = {
        "when": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "platform": platform.platform(), "python": sys.version.split()[0],
        "document": args.file, "canary": args.canary, "guard_mode": args.mode,
        "timings": timings,
        "findings": len(analysis.findings),
        "network": net,
        "files_changed_during_run": len(touched),
        "files_changed_sample": [str(p) for p in touched[:40]],
        "canary_found_outside_output_dir": leaks,
        "verdict": "PASS" if not net["non_loopback_events"] and not leaks else "FAIL",
    }
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"verdict: {report['verdict']}")
    print(f"network events: {net['events_total']} total, {net['non_loopback_events']} non-loopback")
    print(f"targets: {', '.join(net['distinct_targets']) or 'none'}")
    print(f"files changed during run: {len(touched)}; canary outside {out.name}/: {len(leaks)}")
    print(f"timings: {timings}")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
