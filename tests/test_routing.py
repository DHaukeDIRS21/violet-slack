from datetime import datetime
from unittest.mock import MagicMock

import pytest

from violet.app import HELP_TEXT, NOT_UNDERSTOOD, Violet
from violet.store import Store


@pytest.fixture
def violet(tmp_path):
    v = Violet.__new__(Violet)
    v.store = Store(tmp_path)
    v.say = MagicMock(return_value="1.0")
    v.avatar = MagicMock()
    v.slack = MagicMock()
    v.slack.now.return_value = datetime(2026, 10, 15, 17, 0)  # Donnerstag
    v.is_work_time = MagicMock(return_value=True)  # Arbeitszeit: eigene Tests in test_worktime.py
    for name in ("start_focus", "answer_focus", "digest", "update_focus", "focus_recap", "set_status",
                 "start_announcement", "preview", "apply_edit"):
        setattr(v, name, MagicMock())
    return v


@pytest.mark.parametrize("text,method,args", [
    ("focus", "start_focus", ()),
    ("digest", "digest", (None,)),
    ("digest 48", "digest", (48,)),
    ("recap", "focus_recap", (3,)),
    ("Recap 4 Wochen", "focus_recap", (4,)),
    ("status Mailtastic erledigt", "update_focus", ("Mailtastic erledigt",)),
    ("erledigt fix broken laptop", "update_focus", ("erledigt fix broken laptop",)),
    ("arbeite an Update Mailtastic artikel in Wiki", "update_focus",
     ("arbeite an Update Mailtastic artikel in Wiki",)),
    ("unplanned Drucker 2. OG erledigt", "update_focus", ("unplanned Drucker 2. OG erledigt",)),
    ("warte VMWare lizenzing", "update_focus", ("warte VMWare lizenzing",)),
    ("status warte VMWare", "update_focus", ("warte VMWare",)),
    ("<!channel> :information_source: Titel\nText", "start_announcement",
     ("<!channel> :information_source: Titel\nText",)),
])
def test_routes(violet, text, method, args):
    violet.handle_command(text)
    getattr(violet, method).assert_called_once_with(*args)


def test_help_and_unknown(violet):
    violet.handle_command("Hilfe")
    violet.say.assert_called_with(HELP_TEXT)
    violet.handle_command("blabla")
    violet.say.assert_called_with(NOT_UNDERSTOOD)


def test_allgemein_unchanged(violet):
    violet.handle_command("allgemein: Kuchen in der Küche")
    violet.preview.assert_called_once_with({"kind": "allgemein", "text": "Kuchen in der Küche"})


def test_focus_answer_starting_with_recap_is_not_a_command(violet):
    violet.store.set("state", {"mode": "awaiting_focus", "previous": None})
    violet.handle_command("Recap: alles erledigt\nFocus: Drucker")
    violet.focus_recap.assert_not_called()
    violet.answer_focus.assert_called_once()


def test_focus_answer_uses_state(violet):
    violet.store.set("state", {"mode": "awaiting_focus", "previous": {"info": "HO"}})
    violet.handle_command("Info: MyCorner\nFocus: Drucker")
    violet.answer_focus.assert_called_once_with("Info: MyCorner\nFocus: Drucker", {"info": "HO"}, [])
    assert violet.store.get("state") is None


def test_live_toggle(violet):
    violet.handle_command("live aus")
    assert violet.store.get("live") is False


@pytest.mark.parametrize("today,last,shown", [
    ({"text": "Focus: heute", "ts": "2", "root_ts": "2"}, {"text": "Focus: gestern"}, "heute"),
    (None, {"text": "Focus: gestern", "ts": "1", "root_ts": "1"}, "gestern"),
])
def test_start_focus_prefers_today(tmp_path, today, last, shown):
    v = Violet.__new__(Violet)
    v.store = Store(tmp_path)
    v.say = MagicMock()
    v.slack = MagicMock()
    v.slack.today_post.return_value = today
    v.slack.last_post.return_value = last
    v.suggest_todos = MagicMock()
    v.start_focus()
    v.suggest_todos.assert_called_once()
    assert f"Focus: {shown}" in v.say.call_args.args[0]
    assert v.store.get("state")["mode"] == "awaiting_focus"


def test_forward_text_format():
    from violet.app import forward_text
    draft = {"user": "UMAX", "text": "Hi Daniel, mein Outlook fragt …\n",
             "files": [{"name": "screenshot.png"}]}
    assert forward_text("U0BQPJLUV34", draft) == (
        "<@U0BQPJLUV34> :incoming_envelope: Anfrage von <@UMAX> (per DM an mich):\n"
        "Hi Daniel, mein Outlook fragt …\n"
        ":paperclip: screenshot.png"
    )
    assert forward_text("S07AHDLTN3A", draft).startswith("<!subteam^S07AHDLTN3A> :incoming_envelope:")
    assert forward_text("", {"user": "UMAX", "text": "Hallo"}).startswith(":incoming_envelope: Anfrage von")


def test_live_forward_shares_images(violet):
    violet.cfg = MagicMock(owner_user_id="UMP9T403C")
    violet.dm = "DVIOLET"
    violet.bot = MagicMock()
    violet.slack = MagicMock()
    violet.slack.name.return_value = "Tina"
    violet.slack.permalink.return_value = "https://x/msg"
    violet.slack.fmt_time.return_value = "08:52"
    violet.slack.download.side_effect = [b"png-bytes", None]
    event = {"user": "UTINA", "channel": "DTINA", "ts": "1.0", "text": "Zugriff?", "files": [
        {"id": "F1", "name": "screen.png", "mimetype": "image/png", "permalink": "https://x/F1"},
        {"id": "F2", "name": "kaputt.png", "mimetype": "image/png", "permalink": "https://x/F2"},
        {"id": "F3", "name": "liste.pdf", "mimetype": "application/pdf", "permalink": "https://x/F3"},
    ]}
    violet.live_forward(event)
    msg = violet.say.call_args.args[0]
    assert "<https://x/F1|screen.png>" in msg and "<https://x/F3|liste.pdf>" in msg
    # nur Bilder werden hochgeladen; ein nicht ladbares Bild wird übersprungen
    violet.bot.files_upload_v2.assert_called_once_with(
        channel="DVIOLET", thread_ts=None, content=b"png-bytes", filename="screen.png")
    draft = violet.store.get_draft(violet.say.call_args.args[1][1]["elements"][0]["value"])
    assert [f["id"] for f in draft["files"]] == ["F1", "F2", "F3"]


def test_live_forward_reads_aloud_even_when_live_off(violet):
    violet.cfg = MagicMock(owner_user_id="UMP9T403C")
    violet.slack.name.side_effect = {"UTINA": "Tina", "UMAX": "Max"}.get
    violet.store.set("live", False)
    violet.live_forward({"user": "UTINA", "channel": "DTINA", "ts": "1.0",
                         "channel_type": "im", "text": "Hast du <@UMAX> gesehen?"})
    violet.avatar.announce.assert_called_once_with("Tina", "Hast du @Max gesehen?", None)
    violet.say.assert_not_called()


def test_live_forward_vorlesen_aus(violet):
    violet.cfg = MagicMock(owner_user_id="UMP9T403C")
    violet.store.set("speak", False)
    violet.store.set("live", False)
    violet.live_forward({"user": "UTINA", "channel": "DTINA", "ts": "1.0", "text": "Hi"})
    violet.avatar.announce.assert_not_called()


def test_vorlesen_command(violet):
    violet.cfg = MagicMock(owner_user_id="UMP9T403C")
    violet.handle_command("vorlesen aus")
    assert violet.store.get("speak") is False


def _client(scopes, user_id="UMP9T403C"):
    resp = MagicMock()
    resp.headers = {"x-oauth-scopes": ",".join(scopes)}
    resp.get = {"user_id": user_id}.get
    client = MagicMock()
    client.auth_test.return_value = resp
    return client


def test_check_setup_ok_and_missing_scope(violet):
    from violet.app import REQUIRED_BOT_SCOPES, REQUIRED_USER_SCOPES
    violet.cfg = MagicMock(owner_user_id="UMP9T403C")
    violet.bot = _client(REQUIRED_BOT_SCOPES)
    violet.user = _client(REQUIRED_USER_SCOPES)
    assert violet.check_setup() == []
    violet.user = _client(REQUIRED_USER_SCOPES - {"channels:history"}, user_id="UOTHER")
    problems = violet.check_setup()
    assert "channels:history" in problems[0] and "UOTHER" in problems[1]


def test_start_fails_fast_on_bad_token(monkeypatch):
    from slack_bolt.error import BoltError
    from slack_sdk.errors import SlackApiError

    import violet.app as app_mod

    for exc in (BoltError("invalid_auth"),
                SlackApiError("x", {"ok": False, "error": "invalid_auth"})):
        def boom(cfg, exc=exc):
            raise exc
        monkeypatch.setattr(app_mod, "Violet", boom)
        monkeypatch.setattr(app_mod.time, "sleep", lambda s: pytest.fail("sollte nicht warten"))
        with pytest.raises(RuntimeError, match="Token"):
            app_mod._start(MagicMock())
