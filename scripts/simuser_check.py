"""Check the simulated user answers targeted questions and doesn't leak intent on broad ones.

    uv run python scripts/simuser_check.py qwen35a3
"""

import sys

from lightness.bench.tasks import all_task_ids, load_task
from lightness.provider import Client
from lightness.user import SimulatedUser

BROAD = [
    "Anything else I should know before I start?",
    "Do you have any other requirements?",
    "Can you list all your preferences for this project?",
]
OFF_TOPIC = [
    "Should the output use colours in the terminal?",
    "Which Python version are you on?",
]
TARGETED = {  # task -> [(question, substrings that must appear, case-insensitive)]
    "file-organizer": [
        ("What should the category folders be called?", ["images", "documents"]),
        ("Should screenshots be treated any differently from other images?", ["screenshot"]),
        ("If a file with the same name already exists in the destination, what should happen?", ["(1)"]),
    ],
}


def main(model: str) -> int:
    client = Client.from_registry(model)
    failures = 0
    for tid in all_task_ids():
        task = load_task(tid)
        user = SimulatedUser(client, task.intent)
        for q in BROAD + OFF_TOPIC:
            a = user.ask(q)
            leaked = a.covered
            failures += leaked
            print(f"{'LEAK' if leaked else 'ok  '} {tid:16} {q[:45]:45} -> {a.text[:70]!r}")
        for q, must in TARGETED.get(tid, []):
            a = user.ask(q)
            ok = a.covered and all(m.lower() in a.text.lower() for m in must)
            failures += not ok
            print(f"{'ok  ' if ok else 'MISS'} {tid:16} {q[:45]:45} -> {a.text[:70]!r}")
    print(f"\n{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
