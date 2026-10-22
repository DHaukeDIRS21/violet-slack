from unittest.mock import MagicMock

import pytest

from violet import lunch as L
from violet.app import Violet
from violet.store import Store

RESULT = {
    "dishes": [
        {"dish": "Pizza Salami", "orders": [{"person": "Ben", "count": 1, "note": ""}]},
        {"dish": "Pizza Margherita", "orders": [
            {"person": "Anna", "count": 1, "note": "ohne Zwiebeln"},
            {"person": "Carl", "count": 2, "note": ""}]},
    ],
    "unclear": ["Dora: das Übliche"],
}


def test_render_sorted_with_counts_notes_unclear():
    out = L.render(RESULT)
    lines = out.splitlines()
    assert lines[0] == ":fork_and_knife: *Mittagsbestellung* – 4 Gerichte für 3 Personen"
    assert lines[2] == "• *3× Pizza Margherita* – Anna _(ohne Zwiebeln)_, Carl (2×)"
    assert lines[3] == "• *1× Pizza Salami* – Ben"
    assert "• Dora: das Übliche" in out


def test_render_empty():
    assert "Keine Bestellungen erkannt" in L.render({"dishes": [], "unclear": []})


@pytest.mark.parametrize("text,ref", [
    ("https://dirs21.slack.com/archives/C0DEV/p1792565269691899", ("C0DEV", "1792565269.691899")),
    ("<https://dirs21.slack.com/archives/C0DEV/p1792565269691899?thread_ts=1792562948.604219&amp;cid=C0DEV>",
     ("C0DEV", "1792562948.604219")),
    ("Anna 11:02 Uhr\nPizza", None),
])
def test_thread_ref(text, ref):
    assert L.thread_ref(text) == ref


@pytest.fixture
def violet(tmp_path):
    v = Violet.__new__(Violet)
    v.store = Store(tmp_path)
    v.say = MagicMock()
    v.llm = MagicMock()
    v.llm.lunch_orders.return_value = RESULT
    v.user = MagicMock()
    v.slack = MagicMock()
    v.slack.author.side_effect = lambda m: m["user"]
    return v


def test_command_with_pasted_text(violet):
    violet.handle_command("essen\nAnna  11:02 Uhr\nMargherita ohne Zwiebeln\nBen  11:03 Uhr\nSalami")
    assert violet.llm.lunch_orders.call_args.args[0].startswith("Anna  11:02 Uhr")
    assert "*3× Pizza Margherita*" in violet.say.call_args.args[0]


def test_command_with_link_reads_thread(violet):
    violet.user.conversations_replies.return_value = {
        "messages": [{"user": "Lisa", "text": "Wer bestellt mit?"}, {"user": "Anna", "text": "Margherita"}],
        "response_metadata": {"next_cursor": ""}}
    violet.handle_command("essen https://dirs21.slack.com/archives/C0DEV/p1792565269691899")
    violet.user.conversations_replies.assert_called_once_with(channel="C0DEV", ts="1792565269.691899", limit=200)
    assert violet.llm.lunch_orders.call_args.args[0] == "Lisa: Wer bestellt mit?\nAnna: Margherita"


def test_bare_word_is_not_lunch(violet):
    violet.lunch = MagicMock()
    violet.handle_command("mittag")      # ohne Thread → kein Essens-Befehl (z. B. eigener Status)
    violet.lunch.assert_not_called()
