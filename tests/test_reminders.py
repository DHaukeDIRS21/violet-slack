import json
from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from violet import reminders as R
from violet.app import Violet
from violet.store import Store

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 10, 22, 10, 0, tzinfo=TZ)   # Donnerstag


@pytest.mark.parametrize("text,kind", [
    ("erinnere mich in 20 Minuten an den Rückruf", "add"),
    ("Erinner mich morgen um 9 an SPLA", "add"),
    ("erinnerung: Freitag Teamday", "add"),
    ("erinnerungen", "list"),
    ("erinnerung löschen 2", "delete"),
    ("erinnerung 2 löschen", "delete"),
    ("Mailtastic erledigt", None),
])
def test_commands(text, kind):
    found = ("add" if R.ADD.match(text) and not R.DELETE.match(text) else
             "list" if R.LIST.match(text) else "delete" if R.DELETE.match(text) else None)
    assert found == kind


def test_store_add_pop_remove(tmp_path):
    r = R.Reminders(Store(tmp_path))
    b = r.add(200, "B")
    a = r.add(100, "A")
    assert [x["text"] for x in r.all()] == ["A", "B"]
    assert [x["text"] for x in r.pop_due(150)] == ["A"]
    assert [x["text"] for x in r.all()] == ["B"]
    assert r.remove(b["id"])["text"] == "B" and r.all() == []
    assert r.remove(a["id"]) is None


@pytest.fixture
def violet(tmp_path):
    v = Violet.__new__(Violet)
    v.store = Store(tmp_path)
    v.reminders = R.Reminders(v.store)
    v.say = MagicMock()
    v.bot = MagicMock()
    v.dm = "DVIOLET"
    v.avatar = MagicMock()
    v.llm = MagicMock()
    v.slack = MagicMock()
    v.slack.now.return_value = NOW
    return v


def test_add_confirms_and_stores(violet):
    violet.llm.parse_reminder.return_value = {"ok": True, "due": "2026-10-23 09:00", "text": "SPLA", "question": ""}
    violet.handle_command("erinnere mich morgen um 9 an SPLA")
    assert violet.llm.parse_reminder.call_args.args[1] == "Donnerstag, 22.10.2026 10:00"
    assert "Fr 23.10. um 09:00" in violet.say.call_args.args[0] and "*SPLA*" in violet.say.call_args.args[0]
    assert violet.reminders.all()[0]["due"] == datetime(2026, 10, 23, 9, 0, tzinfo=TZ).timestamp()


def test_unclear_asks_back(violet):
    violet.llm.parse_reminder.return_value = {"ok": False, "due": "", "text": "", "question": "Woran denn?"}
    violet.handle_command("erinnere mich morgen")
    assert "Woran denn?" in violet.say.call_args.args[0] and violet.reminders.all() == []


def test_past_time_rejected(violet):
    violet.llm.parse_reminder.return_value = {"ok": True, "due": "2026-10-22 08:00", "text": "x", "question": ""}
    violet.handle_command("erinnere mich um 8 an x")
    assert "Vergangenheit" in violet.say.call_args.args[0] and violet.reminders.all() == []


def test_list_and_delete(violet):
    violet.reminders.add(NOW.timestamp() + 3600, "Rückruf Volker")
    violet.reminders.add(NOW.timestamp() + 60, "Tee")
    violet.handle_command("erinnerungen")
    out = violet.say.call_args.args[0]
    assert out.index("1. Do 22.10. um 10:01 – Tee") < out.index("2. Do 22.10. um 11:00 – Rückruf Volker")
    violet.handle_command("erinnerung löschen 1")
    assert [r["text"] for r in violet.reminders.all()] == ["Rückruf Volker"]


def test_fire_slack_and_avatar_and_late_note(violet):
    violet.fire_reminder({"id": "x", "due": NOW.timestamp() - 3600, "text": "Rückruf Volker"})
    msg = violet.say.call_args.args[0]
    assert msg.startswith(":alarm_clock: *Erinnerung:* Rückruf Volker") and "fällig war Do 22.10. um 09:00" in msg
    violet.avatar.announce.assert_called_once_with("Violet", "Erinnerung: Rückruf Volker", "einer Erinnerung")
    violet.store.set("speak", False)
    violet.fire_reminder({"id": "y", "due": NOW.timestamp(), "text": "leise"})
    assert violet.avatar.announce.call_count == 1                 # „vorlesen aus“ gilt auch hier


def test_snooze_and_done_buttons(violet, monkeypatch):
    monkeypatch.setattr("violet.app.time.time", lambda: NOW.timestamp())
    violet.fire_reminder({"id": "x", "due": NOW.timestamp(), "text": "Tee"})
    blocks = violet.say.call_args.args[1]
    btn = next(e for b in blocks if b.get("type") == "actions" for e in b["elements"]
               if e["action_id"] == "violet_remind_10")
    body = {"actions": [{"value": btn["value"]}], "message": {"ts": "1.1", "text": "x", "blocks": blocks}}
    violet._on_remind(MagicMock(), body, 10)
    assert [(r["text"], r["due"]) for r in violet.reminders.all()] == [("Tee", NOW.timestamp() + 600)]
    upd = violet.bot.chat_update.call_args.kwargs["blocks"]
    assert not any(b["type"] == "actions" for b in upd) and "10:10" in json.dumps(upd)
    violet._on_remind(MagicMock(), body, None)
    assert "Erledigt" in json.dumps(violet.bot.chat_update.call_args.kwargs["blocks"])
