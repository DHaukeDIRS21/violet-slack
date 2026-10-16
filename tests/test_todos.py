import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from violet.app import Violet
from violet.store import Store
from violet.todos import TodoList

SCHEMA = [
    {"key": "name", "name": "Name", "type": "text", "is_primary_column": True, "id": "ColTitle"},
    {"key": "todo_completed", "name": "Erledigt", "type": "todo_completed", "id": "ColDone"},
    {"key": "todo_assignee", "name": "Zuständig", "type": "todo_assignee", "id": "ColWho"},
]


def _item(row, title, done=False, created=1, **extra):
    fields = [{"column_id": "ColTitle", "key": "name", "text": title, "value": "[{\"type\":\"rich_text\"}]"},
              {"column_id": "ColDone", "key": "todo_completed", "checkbox": [done], "value": done}]
    return {"id": row, "date_created": created, "fields": fields, **extra}


class FakeUser:
    def __init__(self, items):
        self.items = items
        self.calls = []

    def api_call(self, method, json=None):
        self.calls.append((method, json))
        if method == "slackLists.create":
            data = {"ok": True, "list_id": "FLIST", "list_metadata": {"schema": SCHEMA}}
        elif method == "slackLists.items.list":
            data = {"ok": True, "items": self.items, "response_metadata": {"next_cursor": ""},
                    "list": {"list_metadata": {"schema": SCHEMA}}}
        else:
            data = {"ok": True}
        return MagicMock(data=data)

    def files_info(self, file):
        return {"file": {"permalink": f"https://slack/lists/{file}"}}


@pytest.fixture
def todos(tmp_path):
    user = FakeUser([
        _item("Rec3", "Drucker 2. OG", created=3),
        _item("Rec1", "VPN für Praktikant", created=1),
        _item("Rec2", "erledigt schon", done=True, created=2),
        _item("Rec4", "Unteraufgabe", created=4, parent_record_id="Rec3"),
        {"id": "Rec5", "date_created": 5, "fields": [
            {"column_id": "ColTitle", "text": ""},
            {"column_id": "ColMsg", "message": [{"value": "https://slack/archives/D1/p123"}]}]},
    ])
    return TodoList(user, Store(tmp_path)), user


def test_creates_list_once_in_todo_mode(todos):
    t, user = todos
    assert t.meta()["created"] is True
    assert t.meta().get("created") is None          # zweites Mal aus dem Speicher
    creates = [c for c in user.calls if c[0] == "slackLists.create"]
    assert creates == [("slackLists.create", {"name": "To-dos", "todo_mode": True})]


def test_open_items_skip_done_and_subtasks(todos):
    t, _ = todos
    assert t.open_items() == [
        {"id": "Rec1", "title": "VPN für Praktikant", "link": None},
        {"id": "Rec3", "title": "Drucker 2. OG", "link": None},
        {"id": "Rec5", "title": "(Nachricht)", "link": "https://slack/archives/D1/p123"},
    ]


def test_complete_sets_checkbox(todos):
    t, user = todos
    t.complete("Rec1")
    assert user.calls[-1] == ("slackLists.items.update", {
        "list_id": "FLIST", "cells": [{"row_id": "Rec1", "column_id": "ColDone", "checkbox": True}]})


def test_done_as_plain_bool(tmp_path):
    item = _item("Rec9", "x")
    item["fields"][1] = {"column_id": "ColDone", "checkbox": True}
    t = TodoList(FakeUser([item]), Store(tmp_path))
    assert t.open_items() == []


def test_configured_list_reads_schema(tmp_path):
    user = FakeUser([])
    t = TodoList(user, Store(tmp_path), "FMINE")
    assert t.meta() == {"id": "FMINE", "title_col": "ColTitle", "done_col": "ColDone", "created": False}
    assert not any(c[0] == "slackLists.create" for c in user.calls)


# --- Buttons im Violet-Chat ---------------------------------------------------
@pytest.fixture
def violet(tmp_path, todos):
    v = Violet.__new__(Violet)
    v.store = Store(tmp_path / "v")
    v.todos = todos[0]
    v.say = MagicMock(return_value="1.0")
    v.bot = MagicMock()
    v.dm = "DVIOLET"
    v.slack = MagicMock()
    v.slack.now.return_value = datetime(2026, 10, 16, 8, 0)
    v.update_focus = MagicMock()
    return v


def _click(violet, action_id, row, title):
    blocks = violet.say.call_args.args[1]
    block = next(b for b in blocks if b.get("block_id") == f"todo_{row}")
    btn = next(e for e in block["elements"] if e["action_id"] == action_id)
    assert json.loads(btn["value"]) == {"id": row, "t": title}
    body = {"actions": [{"value": btn["value"], "block_id": block["block_id"]}],
            "message": {"ts": "9.9", "text": "x", "blocks": blocks}}
    violet._on_todo(MagicMock(), body, take=action_id == "violet_todo_take")
    return violet.bot.chat_update.call_args.kwargs["blocks"]


def test_suggest_and_take_while_answering(violet):
    violet.store.set("state", {"mode": "awaiting_focus", "previous": None})
    violet.suggest_todos()
    blocks = _click(violet, "violet_todo_take", "Rec1", "VPN für Praktikant")
    assert violet.store.get("state")["todo_picks"] == ["VPN für Praktikant"]
    assert ("slackLists.items.update", {"list_id": "FLIST", "cells": [
        {"row_id": "Rec1", "column_id": "ColDone", "checkbox": True}]}) in violet.todos.user.calls
    # nur dieser Eintrag ist ersetzt, die anderen Buttons bleiben
    assert not any(b.get("block_id") == "todo_Rec1" for b in blocks)
    assert any(b.get("block_id") == "todo_Rec3" for b in blocks)


def test_take_after_posting_updates_todays_post(violet):
    violet.slack.today_post.return_value = {"ts": "1", "root_ts": "1", "text": "Info: HO"}
    violet.suggest_todos()
    _click(violet, "violet_todo_take", "Rec3", "Drucker 2. OG")
    violet.update_focus.assert_called_once_with("Neues Focus-Ziel (Status open): Drucker 2. OG")


def test_defer_hides_until_tomorrow(violet):
    violet.suggest_todos()
    _click(violet, "violet_todo_defer", "Rec1", "VPN für Praktikant")
    assert not any(c[0] == "slackLists.items.update" for c in violet.todos.user.calls)
    violet.suggest_todos()
    assert not any(b.get("block_id") == "todo_Rec1" for b in violet.say.call_args.args[1])
    violet.slack.now.return_value = datetime(2026, 10, 17, 8, 0)
    violet.suggest_todos()
    assert any(b.get("block_id") == "todo_Rec1" for b in violet.say.call_args.args[1])


def test_answer_focus_adds_picks(violet):
    violet.llm = MagicMock()
    violet.slack.today_post.return_value = None
    violet.preview = MagicMock()
    violet.answer_focus("Focus: Drucker", None, ["VPN für Praktikant"])
    answer = violet.llm.new_focus_post.call_args.args[1]
    assert "Focus: Drucker" in answer and "- VPN für Praktikant" in answer
