"""OpenAI-compatible chat client with thinking control, schema-constrained decisions, and a call log.

Every model call names a `purpose` (the call type) and is appended to a JSONL log, so runs can be
broken down by where tokens and time went.
"""

import json
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]


class ProviderError(RuntimeError):
    pass


class ContextOverflow(ProviderError):
    pass


class DecisionError(ProviderError):
    """The model's constrained answer still failed validation after the retry."""


@dataclass
class Caps:
    """What the endpoint supports. Defaults describe llama-server (probed 2026-11-02)."""

    json_schema: bool = True
    # chat_template_kwargs.enable_thinking turns thinking on/off per request.
    thinking_toggle: bool = True
    # Per-request request field that caps thinking tokens (None = not supported).
    thinking_budget_field: str | None = "thinking_budget_tokens"


@dataclass
class Reply:
    text: str
    reasoning: str = ""
    parsed: Any = None
    usage: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    latency: float = 0.0
    finish_reason: str = ""


Thinking = bool | int  # False = off, True = on (server cap), int = on with this token budget


class Client:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        caps: Caps | None = None,
        log_path: Path | None = None,
        sampling: dict | None = None,
        timeout: float = 900,
        transport: httpx.BaseTransport | None = None,
    ):
        self.model = model
        self.caps = caps or Caps()
        self.log_path = log_path
        self.sampling = sampling or {}
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)

    @classmethod
    def from_registry(cls, name: str, **kwargs) -> "Client":
        """Build a client from an entry in models.toml."""
        entry = tomllib.loads((REPO_ROOT / "models.toml").read_text())[name]
        caps = Caps(**entry.get("caps", {}))
        return cls(entry["base_url"], entry["model"], caps=caps, sampling=entry.get("sampling"), **kwargs)

    def chat(
        self,
        messages: list[dict],
        *,
        purpose: str,
        schema: dict | None = None,
        thinking: Thinking = False,
        max_tokens: int = 4096,
        stop: list[str] | None = None,
        temperature: float | None = None,
    ) -> Reply:
        body: dict[str, Any] = {"model": self.model, "messages": messages, "max_tokens": max_tokens, **self.sampling}
        if temperature is not None:
            body["temperature"] = temperature
        if stop:
            body["stop"] = stop
        if schema is not None:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": purpose, "schema": schema, "strict": True}}
        if self.caps.thinking_toggle:
            body["chat_template_kwargs"] = {"enable_thinking": bool(thinking)}
        if thinking is not True and thinking and self.caps.thinking_budget_field:
            body[self.caps.thinking_budget_field] = int(thinking)
            # Thinking cut short by the budget spills into the answer; leave room for it.
            body["max_tokens"] = max_tokens + int(thinking)

        start = time.time()
        try:
            resp = self.http.post("/chat/completions", json=body)
        except httpx.TransportError as e:
            raise ProviderError(f"request failed: {e}") from e
        latency = time.time() - start
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code != 200 or "error" in data:
            msg = (data.get("error") or {}).get("message", resp.text[:300]) if data else resp.text[:300]
            self._log(purpose, None, latency, ok=False, error=msg)
            if "context" in msg.lower() and ("exceed" in msg.lower() or "too long" in msg.lower()):
                raise ContextOverflow(msg)
            raise ProviderError(f"HTTP {resp.status_code}: {msg}")

        choice = data["choices"][0]
        msg = choice["message"]
        reply = Reply(
            text=msg.get("content") or "",
            reasoning=msg.get("reasoning_content") or "",
            usage=data.get("usage", {}),
            timings=data.get("timings", {}),
            latency=latency,
            finish_reason=choice.get("finish_reason", ""),
        )
        self._log(purpose, reply, latency, ok=True, thinking=thinking)
        return reply

    def decide(
        self,
        messages: list[dict],
        schema: dict,
        *,
        purpose: str,
        reason_budget: int = 0,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> Reply:
        """Reason (optionally, bounded), then answer in JSON matching `schema`.

        llama-server applies the schema only after the thinking block, so reasoning and the
        constrained answer happen in one request. On a validation failure, retry once with the
        error; then raise DecisionError.
        """
        thinking: Thinking = reason_budget if reason_budget > 0 else False
        reply = self.chat(messages, purpose=purpose, schema=schema, thinking=thinking, max_tokens=max_tokens,
                          temperature=temperature)
        error = _validate(reply, schema)
        if error is None:
            return reply
        retry = messages + [
            {"role": "assistant", "content": reply.text},
            {"role": "user", "content": f"That answer was invalid: {error}. Reply again with only valid JSON."},
        ]
        reply = self.chat(retry, purpose=f"{purpose}:retry", schema=schema, thinking=False, max_tokens=max_tokens,
                          temperature=temperature)
        error = _validate(reply, schema)
        if error is not None:
            raise DecisionError(f"{purpose}: {error}; got {reply.text[:200]!r}")
        return reply

    def _log(self, purpose: str, reply: Reply | None, latency: float, *, ok: bool, thinking: Thinking = False, error: str = ""):
        if not self.log_path:
            return
        row: dict[str, Any] = {"ts": time.time(), "purpose": purpose, "model": self.model, "ok": ok, "latency": round(latency, 3)}
        if reply is not None:
            t = reply.timings
            row |= {
                "thinking": thinking,
                "prompt_tokens": reply.usage.get("prompt_tokens"),
                "completion_tokens": reply.usage.get("completion_tokens"),
                "cached_tokens": t.get("cache_n"),
                "prompt_ms": t.get("prompt_ms"),
                "predicted_ms": t.get("predicted_ms"),
                "reasoning_chars": len(reply.reasoning),
                "finish_reason": reply.finish_reason,
            }
        if error:
            row["error"] = error[:500]
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as f:
            f.write(json.dumps(row) + "\n")


def _validate(reply: Reply, schema: dict) -> str | None:
    try:
        reply.parsed = json.loads(reply.text)
    except json.JSONDecodeError as e:
        return f"not JSON ({e.msg})"
    try:
        jsonschema.validate(reply.parsed, schema)
    except jsonschema.ValidationError as e:
        return e.message
    return None
