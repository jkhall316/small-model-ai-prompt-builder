"""Minimal OpenAI-compatible chat client (httpx) plus a forgiving JSON extractor for small-model replies."""
from __future__ import annotations

import json
import re

import httpx

from .settings import Settings


class ModelError(RuntimeError):
    pass


def _headers(settings: Settings) -> dict:
    return {"Authorization": f"Bearer {settings.api_key}"} if settings.api_key else {}


def complete(settings: Settings, messages: list[dict], max_tokens: int, temperature: float = 0.3, json_mode: bool = True) -> tuple[str, bool]:
    """One chat completion. Returns (text, truncated). Raises ModelError with a user-readable message."""
    req: dict = dict(model=settings.model, temperature=temperature, max_tokens=max_tokens, messages=messages)
    if json_mode and settings.json_mode:
        req["response_format"] = {"type": "json_object"}
    req.update(settings.extra_body or {})
    url = settings.base_url.rstrip("/") + "/chat/completions"
    try:
        r = httpx.post(url, json=req, headers=_headers(settings), timeout=settings.timeout_s)
    except httpx.HTTPError as ex:
        raise ModelError(f"The model did not answer ({ex.__class__.__name__}). Is {settings.base_url} up?")
    if r.status_code != 200:
        raise ModelError(f"Model error {r.status_code}: {r.text[:300]}")
    try:
        ch = r.json()["choices"][0]
        txt = ch["message"].get("content") or ""
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise ModelError(f"Unexpected reply from the model endpoint (not a chat completion): {r.text[:200]}")
    txt = re.sub(r"<think>.*?</think>\s*", "", txt, flags=re.S)   # thinking models that leak their scratchpad
    return txt, ch.get("finish_reason") == "length"


def list_models(settings: Settings) -> list[str]:
    r = httpx.get(settings.base_url.rstrip("/") + "/models", headers=_headers(settings), timeout=6)
    if r.status_code != 200:
        raise ModelError(f"/models returned {r.status_code}")
    data = r.json()
    items = data.get("data") or data.get("models") or []
    out = []
    for m in items:
        if isinstance(m, dict):
            name = m.get("id") or m.get("name") or m.get("model")
            if isinstance(name, str) and name:
                out.append(name)
    return out


def model_listed(model: str, ids: list[str]) -> bool:
    """Exact match, or Ollama-style tag tolerance: 'qwen3' matches 'qwen3:latest'; 'qwen3:4b' matches 'qwen3:4b-instruct'."""
    if model in ids:
        return True
    return any(i == model + ":latest" or i.startswith(model + ":") or model.startswith(i + ":") for i in ids)


def extract_json(txt: str):
    """Parse a reply as JSON: whole text first, then the first ```json fence, then the first {…}/[…] found.
    Whole-text first matters: valid JSON whose strings contain code fences must not be cut up by the fence rule."""
    dec = json.JSONDecoder(strict=False)   # strict=False: tolerate raw newlines/tabs inside strings, which small models emit
    s = txt.strip()
    try:
        return dec.raw_decode(s)[0]
    except ValueError:
        pass
    m = re.search(r"```(?:json)?\s*(.*?)```", txt, flags=re.S)
    if m:
        try:
            return dec.raw_decode(m.group(1).strip())[0]
        except ValueError:
            pass
    tried = 0
    for m in re.finditer(r"[\[{]", txt):
        try:
            return dec.raw_decode(txt, m.start())[0]
        except ValueError:
            tried += 1
            if tried >= 25:
                break
    raise ModelError("The model did not return valid JSON — try again.")
