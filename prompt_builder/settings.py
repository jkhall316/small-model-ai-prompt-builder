"""Where the model lives. Any OpenAI-compatible chat endpoint works: Ollama, llama.cpp server, LM Studio, vLLM,
LocalAI, text-generation-webui, OpenAI, OpenRouter...

Resolution order for `Settings.from_env()`: environment variables -> a JSON file named by PB_CONFIG -> defaults.
Bad values raise SettingsError naming the variable, so a typo in .env fails at startup with one clear line.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


class SettingsError(ValueError):
    pass


_ENV = {
    "PB_BASE_URL": "base_url", "PB_MODEL": "model", "PB_API_KEY": "api_key", "PB_EXTRA_BODY": "extra_body",
    "PB_JSON_MODE": "json_mode", "PB_TIMEOUT_S": "timeout_s", "PB_CHAT_MAX_TOKENS": "chat_max_tokens",
    "PB_TIDY_MAX_TOKENS": "tidy_max_tokens", "PB_PREFIX": "prefix",
}
_VAR = {v: k for k, v in _ENV.items()}


@dataclass
class Settings:
    base_url: str = "http://127.0.0.1:11434/v1"      # Ollama's OpenAI-compatible endpoint, the most common local default
    model: str = "qwen3:4b"
    api_key: str = ""                                  # sent as "Authorization: Bearer ..." when non-empty
    extra_body: dict[str, Any] = field(default_factory=dict)   # merged into every request, e.g. {"chat_template_kwargs": {"enable_thinking": false}}
    json_mode: bool = True                             # ask the server for grammar-constrained JSON (response_format). Turn off if the backend rejects it.
    timeout_s: float = 180.0
    chat_max_tokens: int = 900
    tidy_max_tokens: int = 1500
    prefix: str = "/api/pb"                            # URL prefix of the router

    @classmethod
    def from_dict(cls, d: dict | None) -> "Settings":
        d = dict(d or {})
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        s = cls(**known)
        s._coerce()
        return s

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        base: dict[str, Any] = {}
        cfg = env.get("PB_CONFIG")
        if cfg:
            p = Path(cfg)
            if not p.is_file():
                raise SettingsError(f"PB_CONFIG points to a file that does not exist: {cfg}")
            try:
                base = json.loads(p.read_text(encoding="utf8"))
            except ValueError as ex:
                raise SettingsError(f"PB_CONFIG file is not valid JSON ({ex})")
            if not isinstance(base, dict):
                raise SettingsError("PB_CONFIG file must contain a JSON object")
        for var, key in _ENV.items():
            if env.get(var) not in (None, ""):
                base[key] = env[var]
        return cls.from_dict(base)

    def _coerce(self) -> None:
        def bad(key, why):
            raise SettingsError(f"{_VAR.get(key, key)}: {why}")
        if isinstance(self.extra_body, str):
            try:
                self.extra_body = json.loads(self.extra_body or "{}")
            except ValueError as ex:
                bad("extra_body", f"not valid JSON ({ex})")
        if self.extra_body is None:
            self.extra_body = {}
        if not isinstance(self.extra_body, dict):
            bad("extra_body", "must be a JSON object, e.g. {\"think\": false}")
        if isinstance(self.json_mode, str):
            self.json_mode = self.json_mode.strip().lower() not in ("0", "false", "no", "off")
        for key in ("timeout_s", "chat_max_tokens", "tidy_max_tokens"):
            v = getattr(self, key)
            try:
                v = float(v) if key == "timeout_s" else int(float(v))
            except (TypeError, ValueError):
                bad(key, f"must be a number, got {getattr(self, key)!r}")
            if v <= 0:
                bad(key, "must be positive")
            setattr(self, key, v)
        if not isinstance(self.base_url, str) or not self.base_url.startswith(("http://", "https://")):
            bad("base_url", f"must start with http:// or https://, got {self.base_url!r}")
        self.prefix = "/" + str(self.prefix).strip("/") if str(self.prefix).strip("/") else ""

    def public(self) -> dict:
        """Safe to show in a status endpoint: no key, no credentials in the URL, no request body extras."""
        d = asdict(self)
        d["api_key"] = "set" if self.api_key else ""
        u = urlsplit(self.base_url)
        if u.username or u.password:
            d["base_url"] = urlunsplit((u.scheme, u.hostname + (f":{u.port}" if u.port else ""), u.path, u.query, u.fragment))
        d["extra_body"] = sorted(self.extra_body) if self.extra_body else []   # keys only
        return d
