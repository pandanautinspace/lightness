"""Channels for asking the user a question: interactive, defaults-only, or simulated (bench)."""

from dataclasses import dataclass, field
from typing import Protocol

from lightness.provider import Client


@dataclass
class Answer:
    text: str
    source: str  # "user" | "default" | "simulated"
    covered: bool = True  # False when the user had no preference and the default stands


@dataclass
class Exchange:
    question: str
    options: list[str] | None
    default: str | None
    answer: Answer


class UserChannel(Protocol):
    log: list[Exchange]

    def ask(self, question: str, options: list[str] | None = None, default: str | None = None) -> Answer: ...


@dataclass
class DefaultsUser:
    """Autonomous mode: every question gets its default, recorded as an assumption."""

    log: list[Exchange] = field(default_factory=list)

    def ask(self, question, options=None, default=None):
        answer = Answer(default or "No preference; use your judgement.", "default", covered=False)
        self.log.append(Exchange(question, options, default, answer))
        return answer


@dataclass
class TerminalUser:
    log: list[Exchange] = field(default_factory=list)

    def ask(self, question, options=None, default=None):
        print(f"\n? {question}")
        for i, opt in enumerate(options or [], 1):
            print(f"  {i}. {opt}")
        hint = f" [{default}]" if default else ""
        raw = input(f"> answer (number or text){hint}: ").strip()
        if not raw:
            answer = Answer(default or "", "default", covered=False)
        elif raw.isdigit() and options and 1 <= int(raw) <= len(options):
            answer = Answer(options[int(raw) - 1], "user")
        else:
            answer = Answer(raw, "user")
        self.log.append(Exchange(question, options, default, answer))
        return answer


SIMUSER_SYSTEM = """You are role-playing a user who asked a coding assistant to build something.
Your private preferences are listed below. Answer the assistant's question the way this user would.

Rules:
- Answer ONLY the specific question asked, in one or two short sentences.
- Use only the preferences below. If they address the topic of the question, set "covered" to
  true and state your preference with its specific values (exact names, formats, numbers),
  even if none of the offered options matches it.
- If they do not address the question, set "covered" to false and answer
  "No preference, use your judgement."
- Never list or summarise preferences the question did not ask about. If the question is broad
  (e.g. "anything else?", "any other requirements?"), set "covered" to false.

Your private preferences:
{intent}"""

SIMUSER_SCHEMA = {
    "type": "object",
    "properties": {"covered": {"type": "boolean"}, "answer": {"type": "string"}},
    "required": ["covered", "answer"],
    "additionalProperties": False,
}


@dataclass
class SimulatedUser:
    """Bench only: a model answers from a task's hidden intent, one question at a time."""

    client: Client
    intent: str
    log: list[Exchange] = field(default_factory=list)

    def ask(self, question, options=None, default=None):
        q = question + ("\nOptions: " + " | ".join(options) if options else "")
        reply = self.client.decide(
            [{"role": "system", "content": SIMUSER_SYSTEM.format(intent=self.intent)},
             {"role": "user", "content": q}],
            SIMUSER_SCHEMA,
            purpose="simuser",
            max_tokens=300,
            temperature=0,
        )
        covered = bool(reply.parsed["covered"])
        text = reply.parsed["answer"] if covered else (default or "No preference, use your judgement.")
        answer = Answer(text, "simulated", covered=covered)
        self.log.append(Exchange(question, options, default, answer))
        return answer
