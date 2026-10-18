#!/usr/bin/env python3
"""bench/speed_memory.py -- Latency and peak memory for ingestion + analysis."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psutil

from legallens.ingest import ingest

SAMPLES_DIR = Path(__file__).parent.parent / "data" / "samples"
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)


def measure(filepath: Path) -> dict:
    proc = psutil.Process(os.getpid())
    mem_before = proc.memory_info().rss / (1024 * 1024)

    t0 = time.perf_counter()
    doc = ingest(str(filepath))
    elapsed = time.perf_counter() - t0

    mem_after = proc.memory_info().rss / (1024 * 1024)

    return {
        "file": filepath.name,
        "passages": len(doc.passages),
        "warnings": len(doc.extraction_warnings),
        "latency_s": round(elapsed, 3),
        "mem_before_mb": round(mem_before, 1),
        "mem_after_mb": round(mem_after, 1),
        "mem_delta_mb": round(mem_after - mem_before, 1),
    }


def main():
    print("  Speed & Memory Evaluation\n")
    results = []
    for fp in sorted(SAMPLES_DIR.rglob("*")):
        if fp.suffix.lower() in (".txt", ".pdf") and fp.is_file():
            r = measure(fp)
            results.append(r)
            print(f"  {r['file']}: {r['latency_s']}s | {r['passages']} passages | +{r['mem_delta_mb']}MB")

    out = RESULTS_DIR / "speed_memory.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\n  Saved to {out}")


if __name__ == "__main__":
    main()
