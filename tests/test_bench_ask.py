from dataclasses import dataclass, field

from lightness.bench.agents import answer_ask_user
from lightness.user import Answer, Exchange


@dataclass
class EchoUser:
    log: list = field(default_factory=list)

    def ask(self, question, options=None, default=None):
        a = Answer(f"you asked: {question}", "simulated")
        self.log.append(Exchange(question, options, default, a))
        return a


def test_parses_quoted_question():
    assert answer_ask_user('ask_user "What currency?"', EchoUser(), 5) == "you asked: What currency?"


def test_parses_unquoted_and_bad_quotes():
    assert answer_ask_user("ask_user what currency", EchoUser(), 5) == "you asked: what currency"
    assert answer_ask_user("ask_user \"what's the currency", EchoUser(), 5) == "you asked: what's the currency"


def test_empty_question_gets_usage():
    assert "Usage" in answer_ask_user("ask_user", EchoUser(), 5)


def test_budget_enforced():
    user = EchoUser()
    for i in range(2):
        answer_ask_user(f'ask_user "q{i}"', user, 2)
    assert "used all your questions" in answer_ask_user('ask_user "q3"', user, 2)
    assert len(user.log) == 2
