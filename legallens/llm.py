"""Local Gemma client for LegalLens (Person A, H1-H2).

All inference stays on 127.0.0.1. Uses llama-server's OpenAI-compatible
chat endpoint so the model's built-in Gemma chat template is applied —
the raw /completion endpoint does NOT apply it, and Gemma without its
template degrades badly.
"""
from __future__ import annotations

import json
import logging
import urllib.request

from .config import LLMConfig

log = logging.getLogger(__name__)

# stdlib-only HTTP so the client adds no network-capable dependency for
# the dependency audit to clear (PLAN 12, layer 3).


def generate(prompt: str, config: LLMConfig | None = None) -> str:
    """Send prompt to local Gemma, return raw text response."""
    config = config or LLMConfig()
    payload = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
    }).encode()
    req = urllib.request.Request(
        f"{config.base_url}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=config.timeout) as resp:
        body = json.loads(resp.read().decode())
    return body["choices"][0]["message"]["content"] or ""


def extract_json(raw: str) -> dict | list:
    """Pull the first JSON object/array out of a model reply.

    Gemma sometimes wraps output in markdown fences or adds a stray
    sentence; brace-scan instead of trusting the whole string. The
    earliest opener ({ or [) wins so a top-level array is not mistaken
    for its first inner object.
    """
    raw = raw.strip()
    pairs = [("{", "}"), ("[", "]")]
    candidates = sorted(
        (raw.find(opener), opener, closer)
        for opener, closer in pairs
        if raw.find(opener) != -1
    )
    for start, opener, closer in candidates:
        depth = 0
        in_str = False
        esc = False
        for i, ch in enumerate(raw[start:], start=start):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start:i + 1])
                    except json.JSONDecodeError:
                        break  # try the next candidate
    raise ValueError(f"no valid JSON found in model reply: {raw[:200]!r}")


def generate_json(prompt: str, config: LLMConfig | None = None,
                  schema_check=None, client=None) -> dict | list:
    """Generate, parse JSON, retry on malformed output (max 2, PLAN 5.3).

    schema_check: optional callable(parsed) -> str | None returning an
    error message for structurally invalid payloads (missing keys etc.);
    feeding that back is what makes retries actually help.
    client: optional stub with .generate(prompt, config) for offline tests.
    """
    config = config or LLMConfig()
    last_error: str | None = None
    for attempt in range(config.max_retries + 1):
        full_prompt = prompt if attempt == 0 else (
            f"{prompt}\n\n[RETRY: your previous output was invalid. "
            f"Error: {last_error}. Return ONLY valid JSON matching the "
            f"schema exactly, no markdown fences, no extra text.]"
        )
        if client is not None:
            raw = client.generate(full_prompt, config)
        else:
            raw = generate(full_prompt, config)
        try:
            parsed = extract_json(raw)
            if schema_check is not None:
                problem = schema_check(parsed)
                if problem:
                    raise ValueError(problem)
            return parsed
        except (ValueError, json.JSONDecodeError) as e:
            last_error = str(e)
            log.debug("JSON attempt %d failed: %s", attempt + 1, e)
    raise ValueError(
        f"no valid JSON after {config.max_retries + 1} attempts; "
        f"last error: {last_error}"
    )


def health_check(config: LLMConfig | None = None) -> bool:
    """True if the local model server is responding."""
    config = config or LLMConfig()
    try:
        req = urllib.request.Request(f"{config.base_url}/health", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


class StubGemma:
    """Deterministic offline stand-in for CI and stub wiring (H2-H4).

    script: one payload per generate() call, in order. responses maps a
    lowercase substring of the prompt to a canned payload. Unmatched
    prompts decline rather than invent — the same rule the real system
    follows.
    """

    def __init__(self, script: list | None = None,
                 responses: dict[str, object] | None = None) -> None:
        self.script = list(script) if script else []
        self.responses = responses or {}
        self.calls: list[str] = []  # prompts seen, for assertions

    def generate(self, prompt: str, config: LLMConfig | None = None) -> str:
        self.calls.append(prompt)
        if self.script:
            item = self.script.pop(0)
            return item if isinstance(item, str) else json.dumps(item)
        lowered = prompt.lower()
        for needle, payload in self.responses.items():
            if needle in lowered:
                return payload if isinstance(payload, str) else json.dumps(payload)
        return json.dumps([])   # decline: empty findings, never invented


def _validate_findings_payload(parsed) -> str | None:
    """schema_check for the extraction prompt: validate Finding arrays."""
    items = parsed if isinstance(parsed, list) else [parsed]
    if not isinstance(parsed, (list, dict)):
        return "output must be a JSON array of findings"
    from .types import KINDS, LABELS
    for i, f in enumerate(items):
        if not isinstance(f, dict):
            return f"finding {i} is not an object"
        for key in ("kind", "plain_text", "quote", "passage_id", "label"):
            if not f.get(key):
                return f"finding {i} missing or empty '{key}'"
        if f["kind"] not in KINDS:
            return f"finding {i}: kind must be one of {KINDS}"
        if f["label"] not in LABELS:
            return f"finding {i}: label must be one of {LABELS}"
    return None
