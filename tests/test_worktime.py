from datetime import datetime, time
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from violet import worktime as W
from violet.app import Violet
from violet.store import Store

TZ = ZoneInfo("Europe/Berlin")
START, END = time(8, 0), time(17, 30)


def at(day, hh, mm=0):
    return datetime(2026, 10, day, hh, mm, tzinfo=TZ)  # 19.10.2026 = Montag


@pytest.mark.parametrize("now,expected", [
    (at(19, 7, 59), False),
    (at(19, 8, 0), True),
    (at(19, 17, 29), True),
    (at(19, 17, 30), False),
    (at(23, 12), True),        # Freitag
    (at(24, 12), False),       # Samstag
    (at(25, 12), False),       # Sonntag
])
def test_is_work_time(now, expected):
    assert W.is_work_time(now, START, END, None) is expected


def test_feierabend_ends_work_only_that_day():
    assert not W.is_work_time(at(19, 15), START, END, "2026-10-19")
    assert W.is_work_time(at(20, 9), START, END, "2026-10-19")


def test_next_work_start():
    assert W.next_work_start(at(19, 16), START) == at(20, 8)
    assert W.next_work_start(at(23, 16), START) == at(26, 8)   # Freitag → Montag


@pytest.fixture
def violet(tmp_path):
    v = Violet.__new__(Violet)
    v.store = Store(tmp_path)
    v.say = MagicMock()
    v.bot = MagicMock()
    v.user = MagicMock()
    v.dm = "DVIOLET"
    v.cfg = MagicMock(owner_user_id="UME", vip_users=("UADRIAN", "USYSMIN"), forward_bots=("UCHARGING",),
                      work_start="08:00", work_end="17:30")
    v.slack = MagicMock()
    v.slack.name.return_value = "Jemand"
    v.slack.permalink.return_value = "https://slack/msg"
    v.slack.fmt_time.return_value = "19:00"
    v.share_images = MagicMock()
    v.avatar = MagicMock()
    return v


def dm(user, **extra):
    return {"user": user, "channel": "D1", "ts": "1.0", "text": "Hallo", **extra}


def test_outside_work_only_vips(violet):
    violet.slack.now.return_value = at(19, 19)
    violet.live_forward(dm("UKOLLEGE"))
    violet.say.assert_not_called()
    violet.avatar.announce.assert_not_called()          # auch nicht vorlesen
    violet.live_forward(dm("UADRIAN"))
    assert violet.say.call_count == 1
    violet.avatar.announce.assert_called_once()


def test_vip_bot_gets_through_other_bots_not(violet):
    violet.slack.now.return_value = at(19, 10)
    violet.live_forward(dm("UANDERERBOT", bot_id="B1"))
    violet.say.assert_not_called()
    violet.live_forward(dm("USYSMIN", bot_id="B2"))
    assert violet.say.call_count == 1


def test_forward_bot_like_normal_dm(violet):
    violet.slack.now.return_value = at(19, 10)
    violet.live_forward(dm("UCHARGING", bot_id="B0B6V9G5L84"))
    assert violet.say.call_count == 1
    violet.slack.now.return_value = at(19, 19)           # nach Feierabendzeit: wie normale DMs stumm
    violet.live_forward(dm("UCHARGING", bot_id="B0B6V9G5L84"))
    assert violet.say.call_count == 1


def test_feierabend_status_mutes_and_expires_next_workday(violet):
    violet.slack.now.return_value = at(23, 15)              # Freitag 15:00
    violet.handle_command("Feierabend")
    profile = violet.user.users_profile_set.call_args.kwargs["profile"]
    assert profile["status_text"] == "Feierabend - bis Montag"
    assert profile["status_expiration"] == int(at(26, 8).timestamp())
    assert "bis Montag 08:00" in violet.say.call_args.args[0]
    violet.say.reset_mock()
    violet.live_forward(dm("UKOLLEGE"))
    violet.say.assert_not_called()
    violet.handle_command("bin wieder da")                  # zurück → Arbeitszeit läuft wieder
    violet.say.reset_mock()
    violet.live_forward(dm("UKOLLEGE"))
    assert violet.say.call_count == 1


def test_arbeitszeit_command(violet):
    violet.slack.now.return_value = at(19, 10)
    violet.handle_command("arbeitszeit")
    assert "Gerade: läuft" in violet.say.call_args.args[0]
