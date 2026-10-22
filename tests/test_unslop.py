from unittest.mock import MagicMock

import pytest

from violet import llm
from violet.app import Violet
from violet.store import Store


def test_rules_loaded_without_frontmatter():
    assert not llm.UNSLOP.startswith("---")
    assert llm.UNSLOP.startswith("# Unslop")
    assert "Darüber hinaus" in llm.UNSLOP and "Gedankenstriche" in llm.UNSLOP
    assert llm.STYLE.endswith(llm.UNSLOP) and "gehen vor" in llm.STYLE


@pytest.mark.parametrize("method,args", [
    ("bilingual_announcement", ("Titel", "Text", "Daniel")),
    ("edit_text", ("Post", "kürzer")),
    ("focus_recap", ("posts", "01.10. – 21.10.")),
])
def test_style_appended_to_text_prompts(method, args):
    c = llm.Claude.__new__(llm.Claude)
    c._create = MagicMock(return_value="ok")
    getattr(c, method)(*args)
    assert c._create.call_args.args[0].endswith(llm.UNSLOP)


def test_focus_prompts_stay_without_style():
    c = llm.Claude.__new__(llm.Claude)
    c._json = MagicMock(return_value={})
    c.edit_focus_post({}, "x")
    assert llm.UNSLOP not in c._json.call_args.args[0]


@pytest.fixture
def violet(tmp_path):
    v = Violet.__new__(Violet)
    v.store = Store(tmp_path)
    v.say = MagicMock()
    v.llm = MagicMock()
    v.llm.unslop.return_value = "Sauberer Text."
    return v


def test_unslop_command(violet):
    violet.handle_command("unslop\nDarüber hinaus fungiert das Tool als zentraler Baustein.")
    violet.llm.unslop.assert_called_once_with("Darüber hinaus fungiert das Tool als zentraler Baustein.")
    assert violet.say.call_args.args[0] == "Sauberer Text."


def test_unslop_without_text_explains(violet):
    violet.handle_command("unslop")
    violet.llm.unslop.assert_not_called()
    assert "Schick mir den Text" in violet.say.call_args.args[0]
