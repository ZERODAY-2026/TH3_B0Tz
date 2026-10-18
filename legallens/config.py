"""Shared configuration: paths, telemetry kill-switches, model settings.

Kill-switches are set in code at import time (not just documented) so any
accidental hub/telemetry call is suppressed even if a caller forgets.
"""
from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: str | Path | None = None) -> None:
    """Read KEY=VALUE lines from the gitignored .env (see .env.example).
    Variables already set in the real environment always win."""
    path = Path(path) if path else PROJECT_ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        if key:
            os.environ.setdefault(key, value.strip().strip("\"'"))


load_dotenv()

# Telemetry / remote-access kill-switches (PLAN_PS2 section 4). setdefault so
# a developer can still override explicitly for a setup-time download.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("DO_NOT_TRACK", "1")


@dataclass
class LLMConfig:
    # llama-server default; Ollama exposes the same shape on port 11434.
    base_url: str = "http://127.0.0.1:8080"
    max_tokens: int = 2048
    temperature: float = 0.1     # low for deterministic JSON (0.0 from H9)
    context_window: int = 8192
    max_retries: int = 2         # plan 5.3: retry max 2, then skip + log
    timeout: float = 120.0

    @classmethod
    def from_env(cls) -> "LLMConfig":
        base_url = os.environ.get("GEMMA_BASE_URL", cls.base_url)
        if not _is_loopback_url(base_url):
            # Document text goes to this URL. Anything but this machine would
            # break the on-device rule, so refuse rather than send.
            raise ValueError(f"GEMMA_BASE_URL must point at this machine (127.0.0.1 or "
                             f"localhost), got {base_url!r}")
        return cls(
            base_url=base_url,
            timeout=float(os.environ.get("GEMMA_TIMEOUT", str(cls.timeout))),
        )


def _is_loopback_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
