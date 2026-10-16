from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from violet import status as S
from violet.app import Violet
from violet.store import Store

THU, FRI, SAT = date(2026, 10, 15), date(2026, 10, 16), date(2026, 10, 17)


@pytest.mark.parametrize("text,emoji,status", [
    ("ich geh laufen", ":man-running::skin-tone-2:", "laufen"),
    ("Laufen", ":man-running::skin-tone-2:", "laufen"),
    ("ich muss ins RZ", ":office:", "datacenter"),
    ("bin im Rechenzentrum", ":office:", "datacenter"),
    ("bin unterwegs", ":blue_car:", "Unterwegs"),
    ("ich fahre ins Büro", ":blue_car:", "On the Road to Office :office:"),
    ("lasst mich in Ruhe", ":fokuszeit:", "Bitte nicht stören"),
    ("Bitte nicht stören", ":fokuszeit:", "Bitte nicht stören"),
    ("Feierabend", ":x:", "Feierabend - morgen wieder"),
])
def test_presets_on_thursday(text, emoji, status):
    m = S.match(text, THU)
    assert (m["emoji"], m["text"]) == (emoji, status)


@pytest.mark.parametrize("day,text", [
    (THU, "Feierabend - morgen wieder"),
    (FRI, "Feierabend - bis Montag"),
    (SAT, "Feierabend - bis Montag"),
])
def test_feierabend_weekday(day, text):
    assert S.match("Feierabend", day)["text"] == text


def test_clear_and_no_match():
    assert S.match("status weg", THU) == {"name": "clear", "emoji": "", "text": ""}
    assert S.match("Hallo Violet", THU) is None
    assert S.match("Info: MyCorner\nFocus: RZ Patching", THU) is None  # mehrzeilige Focus-Antwort
    assert S.match("x" * 70 + " laufen", THU) is None


@pytest.fixture
def violet(tmp_path):
    v = Violet.__new__(Violet)
    v.store = Store(tmp_path)
    v.say = MagicMock()
    v.user = MagicMock()
    v.slack = MagicMock()
    v.slack.now.return_value = datetime(2026, 10, 16, 17, 30)  # Freitag
    v.update_focus = MagicMock()
    return v


def test_feierabend_on_friday_sets_profile(violet):
    violet.handle_command("Feierabend")
    violet.user.users_profile_set.assert_called_once_with(profile={
        "status_text": "Feierabend - bis Montag", "status_emoji": ":x:", "status_expiration": 0})
    assert "Status gesetzt" in violet.say.call_args.args[0]


def test_focus_commands_are_not_status(violet):
    violet.handle_command("status RZ task David erledigt")
    violet.handle_command("RZ Patching erledigt")
    violet.user.users_profile_set.assert_not_called()
    assert violet.update_focus.call_count == 2


def test_parse_new():
    assert S.parse_new("status neu :fork_and_knife: Mittagspause = mittag, essen oder lunch") == {
        "emoji": ":fork_and_knife:", "text": "Mittagspause", "words": ["mittag", "essen", "lunch"]}
    assert S.parse_new("status neu :man-biking::skin-tone-2: Radtour =rad")["emoji"] == ":man-biking::skin-tone-2:"
    assert S.parse_new("status neu Mittagspause = mittag") is None       # ohne Emoji
    assert S.parse_new("status neu :x: Mittagspause") is None            # ohne Wörter


def test_custom_add_use_change_remove(violet):
    violet.handle_command("status neu :fork_and_knife: Mittagspause = mittag, essen")
    assert "angelegt" in violet.say.call_args.args[0]
    violet.handle_command("ich geh essen")
    violet.user.users_profile_set.assert_called_with(profile={
        "status_text": "Mittagspause", "status_emoji": ":fork_and_knife:", "status_expiration": 0})
    # gleicher Text → ersetzt, nicht doppelt
    violet.handle_command("status neu :hamburger: Mittagspause = mittag, lunch")
    assert "geändert" in violet.say.call_args.args[0]
    assert len(violet.store.get("custom_status")) == 1
    violet.handle_command("status liste")
    listing = violet.say.call_args.args[0]
    assert ":hamburger: Mittagspause ← mittag, lunch" in listing and "datacenter" in listing
    violet.handle_command("status entfernen Mittagspause")
    assert violet.store.get("custom_status") == []
    violet.user.users_profile_set.reset_mock()
    violet.handle_command("lunch")
    violet.user.users_profile_set.assert_not_called()


def test_custom_overrides_builtin(violet):
    violet.handle_command("status neu :runner: Lauftreff = laufen")
    violet.handle_command("ich geh laufen")
    assert violet.user.users_profile_set.call_args.kwargs["profile"]["status_text"] == "Lauftreff"


def test_remove_builtin_and_bad_syntax(violet):
    violet.handle_command("status entfernen datacenter")
    assert "Eingebaute" in violet.say.call_args.args[0]
    violet.handle_command("status neu Mittagspause")
    assert "So legst du einen Status an" in violet.say.call_args.args[0]


def test_status_clear(violet):
    violet.handle_command("status weg")
    violet.user.users_profile_set.assert_called_once_with(profile={
        "status_text": "", "status_emoji": "", "status_expiration": 0})
