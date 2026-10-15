from unittest.mock import MagicMock

import pytest

from violet.app import HELP_TEXT, NOT_UNDERSTOOD, Violet
from violet.store import Store


@pytest.fixture
def violet(tmp_path):
    v = Violet.__new__(Violet)
    v.store = Store(tmp_path)
    v.say = MagicMock(return_value="1.0")
    for name in ("start_focus", "answer_focus", "digest", "update_focus",
                 "start_announcement", "preview", "apply_edit"):
        setattr(v, name, MagicMock())
    return v


@pytest.mark.parametrize("text,method,args", [
    ("focus", "start_focus", ()),
    ("digest", "digest", (None,)),
    ("digest 48", "digest", (48,)),
    ("status Mailtastic erledigt", "update_focus", ("Mailtastic erledigt",)),
    ("erledigt fix broken laptop", "update_focus", ("erledigt fix broken laptop",)),
    ("arbeite an Update Mailtastic artikel in Wiki", "update_focus",
     ("arbeite an Update Mailtastic artikel in Wiki",)),
    ("unplanned Drucker 2. OG erledigt", "update_focus", ("unplanned Drucker 2. OG erledigt",)),
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


def test_focus_answer_uses_state(violet):
    violet.store.set("state", {"mode": "awaiting_focus", "previous": {"info": "HO"}})
    violet.handle_command("Info: MyCorner\nFocus: Drucker")
    violet.answer_focus.assert_called_once_with("Info: MyCorner\nFocus: Drucker", {"info": "HO"})
    assert violet.store.get("state") is None


def test_live_toggle(violet):
    violet.handle_command("live aus")
    assert violet.store.get("live") is False
