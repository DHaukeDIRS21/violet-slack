from datetime import datetime
from unittest.mock import MagicMock

import pytest

from violet import wrike as WR
from violet.app import Violet
from violet.store import Store

URL = "https://www.wrike.com/open.htm?id=4587462588"
ASSIGNED = f"Sarah Pause hat Ihnen ein Element zugewiesen: <{URL}|Anderes Problem - Weiterleitung an Hubspot>"
MENTIONED = (f"Linda Fröhlich hat Sie in <{URL}|Vorlage IT-Administration Austritt> erwähnt\n"
             "&gt;@Daniel Hauke kann man schließen oder?")
UPDATED = f"Wrike Bot hat eine Freigabe in <{URL}|Anderes Problem> aktualisiert"
GREETING = "Greetings! Wrike bot at your service. Here's what I can do for you:"


def test_parse_assigned():
    assert WR.parse(ASSIGNED) == {"kind": "assigned", "who": "Sarah Pause", "url": URL,
                                  "title": "Anderes Problem - Weiterleitung an Hubspot", "comment": ""}


def test_parse_mentioned_with_comment():
    item = WR.parse(MENTIONED)
    assert item["kind"] == "mentioned" and item["who"] == "Linda Fröhlich"
    assert item["comment"] == "@Daniel Hauke kann man schließen oder?"


def test_parse_title_with_gt():
    text = f"Automation Bot hat Sie in <{URL}|<Vorlage> Hotel X> extension nights cannot be added&gt; erwähnt\n&gt;Hi"
    item = WR.parse(text)
    assert item["kind"] == "mentioned" and item["who"] == "Automation Bot"
    assert "extension nights cannot be added" in item["title"] and item["comment"] == "Hi"


@pytest.mark.parametrize("text", [UPDATED, GREETING, ""])
def test_ignored(text):
    assert WR.parse(text) is None


def test_render():
    assert WR.render(WR.parse(ASSIGNED)).startswith(":new: *Neues Ticket in Wrike* · von Sarah Pause\n<")
    msg = WR.render(WR.parse(MENTIONED))
    assert msg.startswith(":speech_balloon: *Neuer Kommentar für dich* in <")
    assert msg.endswith("\n> @Daniel Hauke kann man schließen oder?")


@pytest.fixture
def violet(tmp_path):
    v = Violet.__new__(Violet)
    v.store = Store(tmp_path)
    v.say = MagicMock()
    v.dm = "DVIOLET"
    v.cfg = MagicMock(owner_user_id="UME", wrike_bot="UWRIKE", monitor_channels=())
    v.is_work_time = MagicMock(return_value=True)
    v.live_forward = MagicMock()
    return v


def ev(text):
    return {"user": "UWRIKE", "bot_id": "BWRIKE", "channel": "DWRIKE", "channel_type": "im",
            "ts": "1.0", "text": text}


def test_routing_assigned_mentioned_updated(violet):
    violet._on_message(ev(ASSIGNED))
    violet._on_message(ev(MENTIONED))
    violet._on_message(ev(UPDATED))
    assert violet.say.call_count == 2
    assert ":new:" in violet.say.call_args_list[0].args[0]
    assert ":speech_balloon:" in violet.say.call_args_list[1].args[0]
    violet.live_forward.assert_not_called()            # Wrike nie als normale DM


def test_outside_work_time_not_reported(violet):
    violet.is_work_time.return_value = False
    violet._on_message(ev(ASSIGNED))
    violet.say.assert_not_called()
