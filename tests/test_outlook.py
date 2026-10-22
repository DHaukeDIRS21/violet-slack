from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from violet import outlook as O
from violet import reminders as R
from violet.app import Violet
from violet.store import Store

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 10, 23, 7, 30, tzinfo=TZ)
T = lambda h, m=0: int(datetime(2026, 10, 23, h, m, tzinfo=TZ).timestamp())  # noqa: E731


def att(start, end, title, where="Microsoft Teams Meeting; Raum Wernau; Raum Wernau", going="Yes"):
    return {"text": f"<!date^{start}^{{time}}|x>-<!date^{end}^{{time}}|x> *<https://outlook/{title}|{title}>*\n"
                    f"{where}\n*Going?* {going}"}


AGENDA = {"user": "UOUTLOOK", "channel_type": "im", "channel": "DOUT", "ts": "1.0",
          "text": "*Today*-<!date^1792000000^{date_long}|Friday>",
          "attachments": [att(T(9), T(9, 30), "Daily Standup"),
                          att(T(13, 30), T(15), "Improver Review", going="Maybe"),
                          att(T(16), T(17), "Abgelehnt", going="No"),
                          {"text": "All-day *<https://outlook/x|Bestand Firmenhandy>*"}]}


def test_parse_agenda():
    items = O.parse_agenda(AGENDA)
    assert [(i["title"], i["all_day"], i["going"]) for i in items] == [
        ("Daily Standup", False, "Yes"), ("Improver Review", False, "Maybe"),
        ("Abgelehnt", False, "No"), ("Bestand Firmenhandy", True, "")]
    assert items[0]["start"] == T(9) and items[0]["end"] == T(9, 30)
    assert items[0]["where"] == "Microsoft Teams Meeting; Raum Wernau"     # doppelte Orte raus


def test_parse_change():
    ev = {"attachments": [{"pretext": "_Event instance cancelled._", "title": "Daily Standup (daniel@dirs21.de)"}]}
    assert O.parse_change(ev) == {"kind": "cancelled", "title": "Daily Standup"}
    ev = {"attachments": [{"pretext": ":white_circle: _Event updated! Time changed:_", "title": "X (a@b.de)"}]}
    assert O.parse_change(ev)["kind"] == "updated"


@pytest.fixture
def violet(tmp_path):
    v = Violet.__new__(Violet)
    v.store = Store(tmp_path)
    v.reminders = R.Reminders(v.store)
    v.say = MagicMock()
    v.bot = MagicMock()
    v.user = MagicMock()
    v.avatar = MagicMock()
    v.dm = "DVIOLET"
    v.cfg = MagicMock(outlook_bot="UOUTLOOK", wrike_bot="UWRIKE", monitor_channels=(), meeting_lead_min=5)
    v.slack = MagicMock()
    v.slack.now.return_value = NOW
    v.slack.day_start.return_value = T(0)
    return v


def test_agenda_creates_reminders_once(violet):
    violet._on_message(AGENDA)
    violet._on_message(AGENDA)                     # doppelt geschickt → keine Doppelten
    items = violet.reminders.all()
    assert [(r["due"], r["title"]) for r in items] == [(T(8, 55), "Daily Standup"), (T(13, 25), "Improver Review")]
    assert items[0]["text"] == "*Termin um 09:00:* <https://outlook/Daily Standup|Daily Standup> · Microsoft Teams Meeting; Raum Wernau"
    assert "2 Termine heute" in violet.say.call_args_list[0].args[0] and violet.say.call_count == 1


def test_fired_meeting_not_recreated_by_catch_up(violet):
    violet.outlook_agenda(AGENDA)
    for item in violet.reminders.pop_due(T(9)):
        pass
    violet.outlook_agenda(AGENDA)
    assert [r["title"] for r in violet.reminders.all()] == ["Improver Review"]


def test_cancel_removes_reminder(violet):
    violet.outlook_agenda(AGENDA)
    violet._on_message({"user": "UOUTLOOK", "channel_type": "im", "channel": "DOUT", "ts": "2.0", "attachments": [
        {"pretext": "_Event instance cancelled._", "title": "Daily Standup (daniel.hauke@dirs21.de)"}]})
    assert [r["title"] for r in violet.reminders.all()] == ["Improver Review"]
    assert "Termin abgesagt" in violet.say.call_args.args[0]


def test_catch_up_fetches_todays_agenda(violet):
    violet.user.users_conversations.return_value = {"channels": [{"id": "DOUT", "user": "UOUTLOOK"}],
                                                    "response_metadata": {"next_cursor": ""}}
    violet.user.conversations_history.return_value = {"messages": [AGENDA]}
    violet.outlook_catch_up()
    assert len(violet.reminders.all()) == 2 and violet.store.get("outlook_dm") == "DOUT"
    violet.user.conversations_history.reset_mock()
    violet.outlook_catch_up()                      # heute schon erledigt → keine weitere Abfrage
    violet.user.conversations_history.assert_not_called()


def test_termine_command(violet):
    violet.outlook_agenda(AGENDA)
    violet.handle_command("termine")
    out = violet.say.call_args.args[0]
    assert "• 09:00–09:30 <https://outlook/Daily Standup|Daily Standup>" in out
    assert "_(vielleicht)_" in out and "ganztägig" in out and "_(abgesagt von dir)_" in out


def test_meeting_reminder_spoken_without_markup(violet):
    violet.store.set("speak", True)
    violet.slack.name.side_effect = lambda u: u
    violet.fire_reminder({"id": "x", "due": NOW.timestamp(), "text": "*Termin um 09:00:* <https://o/x|Daily> · Teams"})
    violet.avatar.announce.assert_called_once_with("Violet", "Erinnerung: Termin um 09:00: Daily · Teams",
                                                   "einer Erinnerung")
