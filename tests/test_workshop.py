from pathlib import Path

from lightness.provider import Reply
from lightness.spec.workshop import Spec, render, repo_summary, run_workshop
from lightness.user import Answer, DefaultsUser, Exchange

QUESTIONS = [
    {"question": f"q{i}", "options": ["a", "b"], "default": f"d{i}", "impact": imp, "ambiguity": amb, "dimension": "x"}
    for i, (imp, amb) in enumerate([(1, 1), (3, 3), (2, 2), (3, 1), (2, 3), (1, 2), (3, 2)])
]
SPEC = {"goal": "g", "non_goals": [], "features": [{"name": "f", "criteria": ["c"]}], "contract": ["k"], "data_model": "m"}


class FakeClient:
    def __init__(self):
        self.spec_prompt = ""

    def decide(self, messages, schema, *, purpose, **kw):
        if purpose == "workshop.classify":
            return Reply("", parsed={"project_type": "cli"})
        if purpose == "workshop.questions":
            return Reply("", parsed={"questions": QUESTIONS})
        if purpose == "workshop.spec":
            self.spec_prompt = messages[-1]["content"]
            return Reply("", parsed=SPEC)
        raise AssertionError(purpose)


class ScriptedUser:
    """Answers questions whose name is in `knows`; no preference otherwise."""

    def __init__(self, knows, corrections=None):
        self.knows, self.log, self.corrections, self.shown = knows, [], corrections or {}, []

    def review(self, statements):
        self.shown = statements
        return {i: fix for i, st in enumerate(statements) for key, fix in self.corrections.items() if key in st}

    def ask(self, question, options=None, default=None):
        a = Answer(f"user says {question}", "simulated") if question in self.knows else Answer(default, "simulated", covered=False)
        self.log.append(Exchange(question, options, default, a))
        return a


def test_asks_top_k_by_impact_times_ambiguity():
    user = ScriptedUser(knows={"q1"})
    spec = run_workshop(FakeClient(), user, "do it", max_asked=3, review=False)
    assert [e.question for e in user.log] == ["q1", "q4", "q6"]  # scores 9, 6, 6 (stable order)
    status = {d.question: d.status for d in spec.decisions}
    assert status["q1"] == "confirmed" and status["q4"] == "defaulted" and status["q0"] == "assumed"
    answers = {d.question: d.answer for d in spec.decisions}
    assert answers["q1"] == "user says q1" and answers["q4"] == "d4" and answers["q0"] == "d0"


def test_every_decision_reaches_the_spec_prompt():
    client = FakeClient()
    run_workshop(client, DefaultsUser(), "do it", max_asked=5)
    for q in QUESTIONS:
        assert f"{q['question']} → {q['default']}" in client.spec_prompt


def test_repo_detection_and_summary(tmp_path: Path):
    (tmp_path / "app.py").write_text("x = 1\n")
    (tmp_path / "test_app.py").write_text("def test_one():\n    pass\n")
    (tmp_path / "README.md").write_text("# Notes app\n")
    s = repo_summary(tmp_path)
    assert "app.py" in s and "Notes app" in s and "test_one" in s
    spec = run_workshop(FakeClient(), DefaultsUser(), "fix it", ws=tmp_path)
    assert spec.project_type == "repo-change"


def test_spec_roundtrip_and_render():
    spec = run_workshop(FakeClient(), ScriptedUser({"q1"}), "do it", max_asked=2)
    again = Spec.from_json(spec.to_json())
    assert again == spec
    md = render(spec)
    assert "- [ ] c" in md and "| q1 | user says q1 | confirmed |" in md


def test_review_takes_one_question_slot_and_folds_in_corrections():
    client = FakeClient()
    user = ScriptedUser(knows={"q1"}, corrections={"q4 → d4": "use 4 exactly", "c": "c must be strict"})
    spec = run_workshop(client, user, "do it", max_asked=3)
    assert [e.question for e in user.log] == ["q1", "q4"]  # 2 questions + the review
    assert "q4 → d4" in user.shown and "c" in user.shown and not any(s.startswith("q1 →") for s in user.shown)
    by_q = {d.question: d for d in spec.decisions}
    assert by_q["q4"].answer == "use 4 exactly" and by_q["q4"].status == "confirmed"
    assert by_q["Spec said: c"].answer == "c must be strict"
    assert "q4 → use 4 exactly" in client.spec_prompt  # the rewrite saw the corrections


def test_no_corrections_means_no_rewrite():
    client = FakeClient()
    spec = run_workshop(client, ScriptedUser(knows=set()), "do it", max_asked=2)
    assert all(not d.question.startswith("Spec said") for d in spec.decisions)
