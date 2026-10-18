"""Environment configuration for DataMind (Person A surface).

Reads settings from the environment, optionally seeded from a ``.env`` file
at the repo root (tiny built-in loader — no python-dotenv dependency).
Only the Gemma endpoint lives here; Snowflake credentials belong to
Person B's ``snowflake_client`` (see ``.env.example`` placeholders).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path = ENV_FILE) -> None:
    """Populate os.environ from KEY=VALUE lines (never overrides real env)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        os.environ.setdefault(key, value)


@dataclass
class Settings:
    # Any OpenAI-compatible endpoint serving Gemma: Ollama, LM Studio, vLLM,
    # or Google AI Studio's OpenAI-compatible URL.
    gemma_base_url: str = "http://localhost:11434/v1"  # Ollama default
    gemma_api_key: str = "ollama"
    gemma_model: str = "gemma3:12b"
    gemma_timeout: float = 120.0

    @classmethod
    def from_env(cls) -> "Settings":
        load_env()
        return cls(
            gemma_base_url=os.environ.get("GEMMA_BASE_URL", cls.gemma_base_url),
            gemma_api_key=os.environ.get("GEMMA_API_KEY", cls.gemma_api_key),
            gemma_model=os.environ.get("GEMMA_MODEL", cls.gemma_model),
            gemma_timeout=float(os.environ.get("GEMMA_TIMEOUT", cls.gemma_timeout)),
        )
