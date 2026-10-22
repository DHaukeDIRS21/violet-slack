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
    listing = violet.say.call_args_list[0].args[0]
    assert listing.startswith(":calendar: *Deine Termine heute* (aus Outlook):")
    assert "Ich erinnere dich jeweils 5 Min vorher" in listing
    assert "Ich erinnere" not in violet.say.call_args_list[1].args[0]     # beim 2. Mal nichts Neues


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


JOIN = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_x%40thread.v2/0"
ITEM = "https://outlook.office365.com/owa/?itemid=ABC123&amp;exvsurl=1&amp;path=/calendar/item"
UPCOMING = {"user": "UOUTLOOK", "channel_type": "im", "channel": "DOUT", "ts": "3.0", "text": "", "attachments": [
    {"pretext": ":loudspeaker: _1 minute until this event:_", "author_name": "Every week on Thursday",
     "title": f"<!date^{T(11, 30)}^{{time}}|11:30 AM> - <!date^{T(12)}^{{time}}|12:00 PM> <{ITEM}|VS/DHa Weekly>",
     "text": f"*Where:* Microsoft Teams-Besprechung; Kaminzimmer\n*Guests:* You\n*What:* <{JOIN}|Jetzt teilnehmen>"},
    {"actions": [{"type": "button", "text": "Join Microsoft Teams Meeting", "url": JOIN}]}]}


def test_parse_upcoming():
    up = O.parse_upcoming(UPCOMING)
    assert (up["lead"], up["start"], up["end"], up["title"], up["join"]) == ("1 Min", T(11, 30), T(12), "VS/DHa Weekly", JOIN)
    assert up["where"] == "Microsoft Teams-Besprechung; Kaminzimmer"
    assert O.teams_links(UPCOMING) == {"ABC123": JOIN}


def test_upcoming_copied_with_join_button(violet):
    violet._on_message(UPCOMING)
    msg, blocks = violet.say.call_args.args
    assert msg.startswith(":loudspeaker: *In 1 Min:* <") and "11:30–12:00" in msg and "Kaminzimmer" in msg
    btn = blocks[1]["elements"][0]
    assert btn["url"] == JOIN and btn["text"]["text"] == "🎥 Teams beitreten"
    violet.avatar.announce.assert_not_called()        # nicht doppelt vorlesen


def test_known_teams_link_goes_into_agenda_reminder(violet):
    violet._on_message(UPCOMING)                       # Link für itemid ABC123 gelernt
    agenda = {**AGENDA, "attachments": [{"text": f"<!date^{T(15)}^{{time}}|x>-<!date^{T(16)}^{{time}}|x> "
                                                 f"*<{ITEM}|VS/DHa Weekly>*\nTeams\n*Going?* Yes"}]}
    violet._on_message(agenda)
    assert violet.reminders.all()[0]["text"].endswith(f"· <{JOIN}|Teams beitreten>")
    assert f"<{JOIN}|Teams beitreten>" in violet.say.call_args.args[0]       # auch in der Terminliste


def test_change_copied(violet):
    violet._on_message({"user": "UOUTLOOK", "channel_type": "im", "channel": "DOUT", "ts": "4.0", "attachments": [
        {"pretext": ":white_circle: _Event updated! Location changed:_", "title": "Daily (d@dirs21.de)",
         "text": f"*Where:* Teams <{JOIN}|Join>"}]})
    assert violet.say.call_args.args[0] == f":white_circle: Termin Ort geändert: *Daily* · <{JOIN}|Teams beitreten>"


def test_meeting_reminder_spoken_without_markup(violet):
    violet.store.set("speak", True)
    violet.slack.name.side_effect = lambda u: u
    violet.fire_reminder({"id": "x", "due": NOW.timestamp(), "text": "*Termin um 09:00:* <https://o/x|Daily> · Teams"})
    violet.avatar.announce.assert_called_once_with("Violet", "Erinnerung: Termin um 09:00: Daily · Teams",
                                                   "einer Erinnerung")
