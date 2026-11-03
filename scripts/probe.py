"""Probe a live endpoint for the capabilities lightness relies on.

    uv run python scripts/probe.py qwen35a3
"""

import sys
import time

from lightness.provider import Client

PRIME = [{"role": "user", "content": "Is 9973 prime? Answer yes or no."}]
MENU = {
    "type": "object",
    "properties": {"choice": {"anyOf": [
        {"type": "object", "properties": {"action": {"const": "read"}, "target": {"enum": ["a.py", "b.py"]}},
         "required": ["action", "target"], "additionalProperties": False},
        {"type": "object", "properties": {"action": {"const": "done"}},
         "required": ["action"], "additionalProperties": False},
    ]}},
    "required": ["choice"],
    "additionalProperties": False,
}


def check(name, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {name:38} {detail}")
    return ok


def main(model: str) -> int:
    c = Client.from_registry(model)
    results = []

    r = c.chat(PRIME, purpose="probe", thinking=False, max_tokens=20)
    results.append(check("thinking off", not r.reasoning, f"reasoning={len(r.reasoning)}ch answer={r.text.strip()!r}"))

    r = c.chat(PRIME, purpose="probe", thinking=64, max_tokens=200)
    approx = len(r.reasoning) // 4
    results.append(check("thinking budget 64", 0 < approx <= 150, f"~{approx} reasoning tokens"))

    r = c.decide([{"role": "user", "content": "You must look at b.py next. Choose."}], MENU, purpose="probe")
    results.append(check("schema anyOf/const/enum", r.parsed == {"choice": {"action": "read", "target": "b.py"}}, str(r.parsed)))

    r = c.decide([{"role": "user", "content": "You must look at b.py next. Choose."}], MENU, purpose="probe", reason_budget=256)
    results.append(check("reason then constrain", bool(r.reasoning) and r.parsed is not None,
                         f"reasoning={len(r.reasoning)}ch parsed={r.parsed}"))

    long = [{"role": "user", "content": "word " * 6000 + "\nHow many times does 'word' appear, roughly?"}]
    c.chat(long, purpose="probe", max_tokens=10)
    start = time.time()
    r = c.chat(long, purpose="probe", max_tokens=10)
    cached = r.timings.get("cache_n", 0)
    results.append(check("prefix cache reuse", cached > 5000, f"cache_n={cached} in {time.time() - start:.1f}s"))

    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
