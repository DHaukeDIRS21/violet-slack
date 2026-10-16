from unittest.mock import MagicMock

import pytest

from violet import monitor as M
from violet.app import Violet
from violet.store import Store


def _event(*titles, channel="C051KH975T6"):
    return {"channel": channel, "ts": "1.0", "subtype": "bot_message",
            "attachments": [{"title": t, "title_link": f"https://opsg/{i}"} for i, t in enumerate(titles)]}


@pytest.mark.parametrize("title,pattern", [
    ("#90129: [Datadog] [Warn] TORZ Server - Freier Festplattenspeicher ist unter 10 % auf Edberg-03",
     "Freier Festplattenspeicher ist unter 10"),
    ("#90083: [Datadog] [No data on {host:Landis-01}] TONW Server - Landis-01 sendet keine Daten mehr",
     "sendet keine Daten mehr"),
    ("#9: WARNING: Controller rebooted unexpectedly", "WARNING: Controller rebooted unexpectedly"),
    ("#1: [Datadog] DIRS21 Messaging Mail Queue too high", "DIRS21 Messaging Mail Queue"),
    ("#2: Backup job failed on Host-01", "Failed"),
    ("#3: [Datadog] Free RAM is low on Edberg-02", "Free RAM is low on"),
])
def test_alerts_match(title, pattern):
    assert M.alerts(_event(title)) == [{"title": title, "link": "https://opsg/0", "pattern": pattern}]


def test_alerts_ignore_other_messages():
    assert M.alerts(_event("#5: [Datadog] CPU high on Edberg-01")) == []
    assert M.alerts(_event(":white_check_mark: Confirmed by Daniel Hauke on Monday")) == []
    # „closed alert“-Meldungen haben keinen Titel
    assert M.alerts({"attachments": [{"fallback": "System closed alert #90123", "text": "Failed"}]}) == []


def test_dedup_ignores_alert_number_and_expires():
    d = M.Dedup(window=600)
    assert d.first("C1", "#90129: Freier Festplattenspeicher ist unter 10 % auf X", now=0)
    assert not d.first("C1", "#90130: Freier Festplattenspeicher ist unter 10 % auf X", now=60)
    assert d.first("C2", "#90130: Freier Festplattenspeicher ist unter 10 % auf X", now=60)
    assert d.first("C1", "#90131: Freier Festplattenspeicher ist unter 10 % auf X", now=700)


@pytest.fixture
def violet(tmp_path):
    v = Violet.__new__(Violet)
    v.store = Store(tmp_path)
    v.say = MagicMock(side_effect=lambda *a, **k: f"dm.{v.say.call_count}")
    v.bot = MagicMock()
    v.slack = MagicMock()
    v.slack.permalink.return_value = "https://slack/msg"
    v.slack.fmt_time.return_value = "10:22"
    v.dedup = M.Dedup()
    v.cfg = MagicMock(monitor_channels=("C051KH975T6", "C0526PWJ3J4"), owner_user_id="UME")
    v.dm = "DVIOLET"
    return v


def test_escalate_sends_once(violet):
    ev = _event("#90129: [Datadog] [Warn] TORZ Server - Freier Festplattenspeicher ist unter 10 % auf Edberg-03")
    violet._on_message(ev)
    violet._on_message(ev)
    violet.say.assert_called_once()
    msg = violet.say.call_args.args[0]
    assert ":rotating_light:" in msg and "<#C051KH975T6>" in msg and "<https://opsg/0|#90129:" in msg


DISK = "[Datadog] [Warn] TORZ Server - Freier Festplattenspeicher ist unter 10 % auf Edberg-03"


def _closed(title, by="System", channel="C051KH975T6"):
    text = f'{by} closed alert <https://eu.opsg.in/a/i/x|#90129> "{title}"'
    return {"channel": channel, "ts": "2.0", "attachments": [{"text": text, "fallback": text}]}


def test_closed_parse():
    assert M.closed(_closed(DISK, by="daniel.hauke")) == {"title": DISK, "by": "daniel.hauke"}
    assert M.closed(_event("#90129: " + DISK)) is None


def test_closed_overwrites_escalation(violet):
    violet._on_message(_event("#90129: " + DISK))
    violet._on_message(_event("#90130: [Datadog] Free RAM is low on Edberg-02"))
    violet._on_message(_closed(DISK, by="daniel.hauke"))
    violet.bot.chat_update.assert_called_once()
    upd = violet.bot.chat_update.call_args.kwargs
    assert upd["channel"] == "DVIOLET" and upd["ts"] == "dm.1"
    assert ":white_check_mark: *Closed* von daniel.hauke um 10:22" in upd["text"] and f"~#90129: {DISK}~" in upd["text"]
    # RAM-Eskalation bleibt offen, Disk ist weg
    assert [e["title"] for e in violet.store.get("escalations").values()] == ["#90130: [Datadog] Free RAM is low on Edberg-02"]
    # nach „closed“ wird dieselbe Meldung sofort wieder eskaliert
    violet._on_message(_event("#90131: " + DISK))
    assert violet.say.call_count == 3


def test_closed_other_channel_or_title_ignored(violet):
    violet._on_message(_event("#90129: " + DISK))
    violet._on_message(_closed(DISK, channel="C0526PWJ3J4"))
    violet._on_message(_closed(DISK.replace("Edberg-03", "Edberg-04")))
    violet.bot.chat_update.assert_not_called()


def test_escalate_off(violet):
    violet.store.set("escalate", False)
    violet._on_message(_event("#1: Backup Failed"))
    violet.say.assert_not_called()


def test_monitor_channel_does_not_trigger_live_forward(violet):
    violet.live_forward = MagicMock()
    violet._on_message({**_event("#1: CPU high"), "channel_type": "group"})
    violet.live_forward.assert_not_called()
    violet.say.assert_not_called()
