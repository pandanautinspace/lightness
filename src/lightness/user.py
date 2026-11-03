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

    def ask(
        self,
        question: str,
        options: list[str] | None = None,
        default: str | None = None,
    ) -> Answer: ...

    def review(self, statements: list[str]) -> dict[int, str]:
        """Show draft spec statements; return {statement index: correction} for the wrong ones."""
        ...


@dataclass
class DefaultsUser:
    """Autonomous mode: every question gets its default, recorded as an assumption."""

    log: list[Exchange] = field(default_factory=list)

    def ask(self, question, options=None, default=None):
        answer = Answer(
            default or "No preference; use your judgement.", "default", covered=False
        )
        self.log.append(Exchange(question, options, default, answer))
        return answer

    def review(self, statements):
        return {}


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

    def review(self, statements):
        print("\nPlease check these points of the draft spec:")
        for i, st in enumerate(statements, 1):
            print(f"  {i}. {st}")
        out = {}
        while True:
            raw = input(
                "> number and correction (e.g. '3 use EUR'), or Enter if all fine: "
            ).strip()
            if not raw:
                return out
            num, _, text = raw.partition(" ")
            if num.isdigit() and 1 <= int(num) <= len(statements) and text:
                out[int(num) - 1] = text


SIMUSER_SYSTEM = """You are role-playing a user who asked a coding assistant to build something.
Your private preferences are listed below. Answer the assistant's question the way this user would.

Rules:
- Answer ONLY the specific question asked, in one or two short sentences.
- Use only the preferences below. If they address the topic of the question, set "covered" to
  true and state your preference in full, with its exact details (names, formats, numbers,
  rules). Do not just pick the nearest option if your preference says something more specific.
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


REVIEW_SYSTEM = """You are role-playing a user who asked a coding assistant to build something.
Your private preferences are listed below. The assistant shows you numbered statements from its
draft spec. Classify every statement:
- agrees: your preferences say the same thing, or are consistent with it.
- contradicts: your preferences say something different about exactly what the statement says.
- not_addressed: your preferences don't say anything about it.

Your private preferences:
{intent}"""

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "integer"},
                    "verdict": {"enum": ["agrees", "contradicts", "not_addressed"]},
                },
                "required": ["item", "verdict"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}


@dataclass
class SimulatedUser:
    """Bench only: a model answers from a task's hidden intent, one question at a time."""

    client: Client
    intent: str
    log: list[Exchange] = field(default_factory=list)

    def _answer(self, question, options=None):
        q = question + ("\nOptions: " + " | ".join(options) if options else "")
        reply = self.client.decide(
            [
                {
                    "role": "system",
                    "content": SIMUSER_SYSTEM.format(intent=self.intent),
                },
                {"role": "user", "content": q},
            ],
            SIMUSER_SCHEMA,
            purpose="simuser",
            max_tokens=300,
            temperature=0,
        )
        return bool(reply.parsed["covered"]), reply.parsed["answer"]

    def ask(self, question, options=None, default=None):
        covered, text = self._answer(question, options)
        if not covered:
            text = default or "No preference, use your judgement."
        answer = Answer(text, "simulated", covered=covered)
        self.log.append(Exchange(question, options, default, answer))
        return answer

    def review(self, statements):
        """Classify each statement; ask for a fix only for contradicted ones (single-question path)."""
        listing = "\n".join(f"{i}. {st}" for i, st in enumerate(statements, 1))
        reply = self.client.decide(
            [
                {"role": "system", "content": REVIEW_SYSTEM.format(intent=self.intent)},
                {"role": "user", "content": f"Draft spec statements:\n{listing}"},
            ],
            REVIEW_SCHEMA,
            purpose="simuser.review",
            max_tokens=1500,
            temperature=0,
        )
        out = {}
        for v in reply.parsed["verdicts"]:
            i = v["item"] - 1
            if v["verdict"] == "contradicts" and 0 <= i < len(statements):
                covered, text = self._answer(
                    f'Your draft says: "{statements[i]}" What should it say instead?'
                )
                if covered:
                    out[i] = text
        self.log.append(
            Exchange(
                "(review of draft spec)",
                None,
                None,
                Answer(f"{len(out)} correction(s)", "simulated", covered=bool(out)),
            )
        )
        return out
