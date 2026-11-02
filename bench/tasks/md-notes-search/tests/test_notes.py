import json
from pathlib import Path

import pytest

from lightness.bench.testkit import run_cli

NOTES = {
    "recipes/sourdough.md": """---
title: Sourdough Bread
tags: [recipe, baking]
---
# Sourdough Bread

My go-to sourdough loaf. Feed the starter the night before; a lively sourdough starter
doubles in about six hours.

## Ingredients

- 500 g flour
- 350 g water
- 100 g starter

## Steps

Mix, rest, fold, shape. Bake the sourdough at 250 °C in a Dutch oven.
""",
    "recipes/pancakes.md": """---
tags:
  - recipe
  - breakfast
---
# Fluffy Pancakes

Good way to use sourdough discard. Whisk eggs, milk and flour; rest 10 minutes.
""",
    "recipes/ramen.md": """# Tokyo Ramen

Tried to recreate the bowl from 東京で食べたラーメン. Rich tonkotsu broth, chashu, ajitama.

#recipe #japan
""",
    "travel/munich.md": """---
title: Trip to München
tags: travel, germany
---
Three days in München in October. Breakfast at Café Luitpold, beer at the Viktualienmarkt
Biergarten. Take the S-Bahn from the airport.
""",
    "travel/paris.md": """---
title: Paris weekend
tags: [travel, France]
---
# Paris weekend

Café au lait every morning near the Marais. The Musée d'Orsay is worth the queue.
""",
    "work/kubernetes-notes.md": """---
title: Kubernetes cheatsheet
tags: [work, devops]
---
# Kubernetes cheatsheet

Kubernetes basics I keep forgetting. A Kubernetes pod is the smallest unit; deployments
manage replica sets. Kubernetes services give pods a stable address.

```bash
kubectl get pods -A
kubectl describe pod web-1
```
""",
    "work/standup-2024-03-04.md": """# Standup 2024-03-04

- Plan to migrate the billing service to kubernetes next sprint.
- Waiting on review from Priya.

#work #meeting
""",
    "work/standup-2024-03-11.md": """# Standup 2024-03-11

- Project Phoenix kickoff on Thursday.
- On-call handover.

#Work #Meeting
""",
    "work/phoenix.md": """---
title: Project Phoenix
tags: [Work, phoenix]
---
# Project Phoenix

Rewrite of the reporting pipeline. Setup guide: https://example.com/docs#install

Target launch is Q3. #launch
""",
    "personal/journal-jan.md": """# January journal

Wrote in the café downstairs most mornings. A bit naïve to think I'd keep this up.

#journal
""",
    "personal/books.md": """---
tags: reading
---
# Books to read

- Kubernetes in Action
- The Name of the Rose
- Gödel, Escher, Bach
""",
    "personal/gym.md": """# Gym plan

Mon/Wed/Fri: squats, bench, rows. Stretch afterwards.

#health #Fitness
""",
    "ideas/app-ideas.md": """# App ideas

## Notes search tool

Something to search my markdown notes from the terminal.

## Plant watering reminder

Ping me when the basil needs water.
""",
    "ideas/garden.md": """---
title: Garden plans
tags: [garden, outdoors]
---
Tomatoes along the south fence, basil in pots. Compost bin by the shed.
""",
    "inbox.md": """# Inbox

- feed the sourdough starter on Saturday
- call the landlord about the heating
#todo
""",
}


@pytest.fixture
def notes(tmp_path: Path) -> Path:
    root = tmp_path / "notes"
    for rel, text in NOTES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def search(folder: Path, *args: str) -> list[dict]:
    r = run_cli("notes.py", "search", str(folder), *args, "--json")
    assert r.returncode == 0, r.stderr
    results = json.loads(r.stdout)
    assert isinstance(results, list)
    return results


def paths(results: list[dict]) -> set[str]:
    return {r["path"].replace("\\", "/") for r in results}


def tag_counts(folder: Path) -> dict[str, int]:
    r = run_cli("notes.py", "tags", str(folder), "--json")
    assert r.returncode == 0, r.stderr
    counts: dict[str, int] = {}
    for tag, n in json.loads(r.stdout).items():
        key = tag.lstrip("#").lower()
        counts[key] = counts.get(key, 0) + int(n)
    return counts


def test_search_finds_notes_mentioning_word(notes):
    assert paths(search(notes, "tonkotsu")) == {"recipes/ramen.md"}
    assert paths(search(notes, "sourdough")) == {"recipes/sourdough.md", "recipes/pancakes.md", "inbox.md"}


def test_search_is_case_insensitive_and_results_have_fields(notes):
    results = search(notes, "BASIL")
    assert paths(results) == {"ideas/app-ideas.md", "ideas/garden.md"}
    for r in results:
        assert isinstance(r["title"], str) and r["title"]
        assert isinstance(r["tags"], list)
        assert isinstance(r["score"], (int, float))


def test_ranking_puts_focused_note_first(notes):
    results = search(notes, "kubernetes")
    assert paths(results) == {"work/kubernetes-notes.md", "work/standup-2024-03-04.md", "personal/books.md"}
    assert results[0]["path"] == "work/kubernetes-notes.md"
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_tag_filter_sees_inline_and_front_matter_tags(notes):
    assert paths(search(notes, "--tag", "recipe")) == {
        "recipes/sourdough.md", "recipes/pancakes.md", "recipes/ramen.md"}
    assert paths(search(notes, "--tag", "germany")) == {"travel/munich.md"}
    assert paths(search(notes, "--tag", "reading")) == {"personal/books.md"}


def test_tag_filter_ignores_case(notes):
    assert paths(search(notes, "--tag", "WORK")) == {
        "work/kubernetes-notes.md", "work/standup-2024-03-04.md", "work/standup-2024-03-11.md", "work/phoenix.md"}
    assert paths(search(notes, "--tag", "fitness")) == {"personal/gym.md"}


def test_words_and_tag_combined(notes):
    assert paths(search(notes, "sourdough", "--tag", "recipe")) == {"recipes/sourdough.md", "recipes/pancakes.md"}


def test_titles_and_note_tags(notes):
    by_path = {r["path"]: r for r in search(notes, "--tag", "travel")}
    assert by_path["travel/munich.md"]["title"].strip().lower() == "trip to münchen"
    ramen = search(notes, "tonkotsu")[0]
    assert ramen["title"].strip().lower() == "tokyo ramen"
    phoenix = search(notes, "--tag", "phoenix")
    assert [r["path"] for r in phoenix] == ["work/phoenix.md"]
    assert {t.lstrip("#").lower() for t in phoenix[0]["tags"]} == {"work", "phoenix", "launch"}


def test_tag_counts_and_headings_are_not_tags(notes):
    counts = tag_counts(notes)
    assert counts.get("recipe") == 3
    assert counts.get("work") == 4
    assert counts.get("travel") == 2
    for not_a_tag in ("ingredients", "steps", "install", "books", "inbox", "notes", ""):
        assert not_a_tag not in counts, f"{not_a_tag!r} should not be a tag"


def test_results_follow_file_changes(notes):
    assert search(notes, "zucchini") == []
    (notes / "ideas" / "garden.md").write_text("# Garden plans\n\nZucchini everywhere this year.\n", encoding="utf-8")
    (notes / "recipes" / "sourdough.md").unlink()
    (notes / "new.md").write_text("# Zucchini bread\n\nUses up the zucchini glut.\n#recipe\n", encoding="utf-8")
    assert paths(search(notes, "zucchini")) == {"ideas/garden.md", "new.md"}
    assert "recipes/sourdough.md" not in paths(search(notes, "sourdough"))


def test_intent_all_words_must_match(notes):
    assert paths(search(notes, "sourdough", "starter")) == {"recipes/sourdough.md", "inbox.md"}


def test_intent_accent_insensitive(notes):
    assert paths(search(notes, "cafe")) == {"travel/munich.md", "travel/paris.md", "personal/journal-jan.md"}
    assert paths(search(notes, "munchen")) == {"travel/munich.md"}


def test_intent_multiple_tags_all_required(notes):
    assert paths(search(notes, "--tag", "work", "--tag", "meeting")) == {
        "work/standup-2024-03-04.md", "work/standup-2024-03-11.md"}
