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


def test_split_extras():
    text = ("https://dirs21.slack.com/archives/C0DEV/p1792565269691899\n"
            "+ Daniel Pizza Salami\n+Lisa Bowl of the Month\n+ 2x Cola für Tom\n+2x Wasser für Jana\n+")
    rest, extras = L.split_extras(text)
    assert rest == "https://dirs21.slack.com/archives/C0DEV/p1792565269691899"
    assert extras == ["Daniel Pizza Salami", "Lisa Bowl of the Month", "2x Cola für Tom", "2x Wasser für Jana"]


def test_plus_one_in_pasted_thread_stays_in_thread():
    rest, extras = L.split_extras("Kevin Roth  10:50 Uhr\n+1 zu Tom\n+1\n+ Daniel Salami")
    assert "+1 zu Tom" in rest and rest.endswith("+1") and extras == ["Daniel Salami"]


def test_with_extras():
    assert L.with_extras("thread", []) == "thread"
    out = L.with_extras("thread", ["Daniel Salami"])
    assert out.startswith("thread\n\nZUSÄTZLICHE BESTELLUNGEN") and out.endswith("- Daniel Salami")


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


def test_link_with_extras(violet):
    violet.user.conversations_replies.return_value = {
        "messages": [{"user": "Anna", "text": "Margherita"}], "response_metadata": {"next_cursor": ""}}
    violet.handle_command("essen https://dirs21.slack.com/archives/C0DEV/p1792565269691899\n+ Daniel Salami")
    sent = violet.llm.lunch_orders.call_args.args[0]
    assert sent.startswith("Anna: Margherita\n\nZUSÄTZLICHE") and sent.endswith("- Daniel Salami")
    assert "plus 1 Zusatzbestellung" in violet.say.call_args_list[0].args[0]


def test_only_extras(violet):
    violet.handle_command("essen\n+ Daniel Salami\n+ Lisa Bowl of the Month")
    assert "ZUSÄTZLICHE" in violet.llm.lunch_orders.call_args.args[0]
    violet.user.conversations_replies.assert_not_called()


def test_bare_word_is_not_lunch(violet):
    violet.lunch = MagicMock()
    violet.handle_command("mittag")      # ohne Thread → kein Essens-Befehl (z. B. eigener Status)
    violet.lunch.assert_not_called()
