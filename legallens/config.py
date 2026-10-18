"""Shared configuration: paths, telemetry kill-switches, model settings.

Kill-switches are set in code at import time (not just documented) so any
accidental hub/telemetry call is suppressed even if a caller forgets.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

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
        return cls(
            base_url=os.environ.get("GEMMA_BASE_URL", cls.base_url),
            timeout=float(os.environ.get("GEMMA_TIMEOUT", str(cls.timeout))),
        )
