"""Ollama helper: cached, structured-output LLM calls.

Used by S06 (topic labels) and S09 (rhetorical-mode classification on a sample).
Responses are cached on disk keyed by (model, prompt, schema) so reruns are free
and deterministic.  Supports both local models and Ollama Cloud (set
``OLLAMA_HOST`` / pass ``host``); cloud models send text to an external service,
which is acceptable for these public sermons but is a conscious choice.

Prompts live in ``analysis/sermons/prompts/`` so they are versioned in-repo.
"""

from __future__ import annotations

import json
from pathlib import Path

from sermons import common

CACHE = common.CACHE_DIR / "llm_cache"
CACHE.mkdir(parents=True, exist_ok=True)


def _key(model: str, prompt: str, fmt: str) -> Path:
    h = common.content_hash(f"{model}\x00{prompt}\x00{fmt}")
    return CACHE / f"{h}.json"


def load_prompt(name: str) -> str:
    return (common.PROMPTS_DIR / name).read_text(encoding="utf-8")


def generate_json(prompt: str, model: str = "llama3.1:8b", schema: dict | None = None,
                  host: str | None = None, options: dict | None = None) -> dict:
    """Call Ollama for a JSON response, cached. ``schema`` (a pydantic
    model.model_json_schema() or raw JSON schema) constrains the output."""
    fmt = json.dumps(schema) if schema else "json"
    cache_path = _key(model, prompt, fmt)
    if cache_path.exists():
        return json.loads(cache_path.read_text())

    import ollama  # lazy

    client = ollama.Client(host=host) if host else ollama
    resp = client.generate(
        model=model,
        prompt=prompt,
        format=schema if schema else "json",
        options=options or {"temperature": 0.0},
    )
    raw = resp["response"] if isinstance(resp, dict) else resp.response
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {"_raw": raw, "_parse_error": True}
    cache_path.write_text(json.dumps(data))
    return data


def is_available(host: str | None = None) -> bool:
    try:
        import ollama

        client = ollama.Client(host=host) if host else ollama
        client.list()
        return True
    except Exception:  # noqa: BLE001
        return False
