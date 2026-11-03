import json

import httpx
import pytest

from lightness.provider import Caps, Client, ContextOverflow, DecisionError

SCHEMA = {
    "type": "object",
    "properties": {"action": {"enum": ["read", "done"]}},
    "required": ["action"],
    "additionalProperties": False,
}


def fake_server(*contents, status=200, error=None):
    """Transport that answers successive requests with the given contents; records bodies."""
    seen, replies = [], iter(contents)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        if error:
            return httpx.Response(status, json={"error": {"message": error}})
        return httpx.Response(200, json={
            "choices": [{"message": {"content": next(replies), "reasoning_content": "hmm"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "timings": {"cache_n": 4, "prompt_ms": 1.0, "predicted_ms": 2.0},
        })

    return httpx.MockTransport(handler), seen


def make_client(transport, tmp_path, **kw):
    return Client("http://x/v1", "m", transport=transport, log_path=tmp_path / "calls.jsonl", **kw)


def test_thinking_off_by_default(tmp_path):
    transport, seen = fake_server("hi")
    make_client(transport, tmp_path).chat([{"role": "user", "content": "q"}], purpose="t")
    assert seen[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "thinking_budget_tokens" not in seen[0]


def test_thinking_budget_sets_field_and_headroom(tmp_path):
    transport, seen = fake_server("hi")
    make_client(transport, tmp_path).chat([{"role": "user", "content": "q"}], purpose="t", thinking=256, max_tokens=100)
    assert seen[0]["chat_template_kwargs"] == {"enable_thinking": True}
    assert seen[0]["thinking_budget_tokens"] == 256
    assert seen[0]["max_tokens"] == 356


def test_no_thinking_fields_when_unsupported(tmp_path):
    transport, seen = fake_server("hi")
    caps = Caps(thinking_toggle=False, thinking_budget_field=None)
    make_client(transport, tmp_path, caps=caps).chat([{"role": "user", "content": "q"}], purpose="t", thinking=256)
    assert "chat_template_kwargs" not in seen[0] and "thinking_budget_tokens" not in seen[0]


def test_decide_parses_and_sends_schema(tmp_path):
    transport, seen = fake_server('{"action": "read"}')
    reply = make_client(transport, tmp_path).decide([{"role": "user", "content": "q"}], SCHEMA, purpose="act")
    assert reply.parsed == {"action": "read"}
    sent = seen[0]["response_format"]["json_schema"]["schema"]
    assert sent["properties"]["action"] == {"enum": ["read", "done"], "type": "string"}  # strict mode wants a type


def test_decide_retries_once_then_succeeds(tmp_path):
    transport, seen = fake_server('{"action": "fly"}', '{"action": "done"}')
    reply = make_client(transport, tmp_path).decide([{"role": "user", "content": "q"}], SCHEMA, purpose="act")
    assert reply.parsed == {"action": "done"}
    assert len(seen) == 2 and "invalid" in seen[1]["messages"][-1]["content"]


def test_decide_raises_after_failed_retry(tmp_path):
    transport, _ = fake_server("not json", '{"action": "fly"}')
    with pytest.raises(DecisionError):
        make_client(transport, tmp_path).decide([{"role": "user", "content": "q"}], SCHEMA, purpose="act")


def test_context_overflow_is_typed(tmp_path):
    transport, _ = fake_server(status=400, error="the request exceeds the available context size")
    with pytest.raises(ContextOverflow):
        make_client(transport, tmp_path).chat([{"role": "user", "content": "q"}], purpose="t")


def test_calls_are_logged_with_purpose_and_usage(tmp_path):
    transport, _ = fake_server('{"action": "fly"}', '{"action": "read"}')
    make_client(transport, tmp_path).decide([{"role": "user", "content": "q"}], SCHEMA, purpose="act")
    rows = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert [r["purpose"] for r in rows] == ["act", "act:retry"]
    assert rows[0]["prompt_tokens"] == 10 and rows[0]["cached_tokens"] == 4
