from datetime import datetime
from unittest.mock import MagicMock

import pytest
from slack_sdk.errors import SlackApiError

from violet import focus as F
from violet.app import Violet
from violet.store import Store

POST = """Info: HO :house_with_garden:
Recap :checkered_flag::
• Fix broken Slack SSO :white_check_mark:
Focus :dart::
• VMWare licensing :hourglass_flowing_sand:
• Prakti Laptop :construction:
Other Topics :zustimmen: (unplanned):
:sos::
:information_source::"""

DAY = datetime(2026, 10, 16, 9, 0)


def test_render_markdown():
    md = F.render_markdown(F.parse_post(POST), DAY, "https://slack/p1")
    assert md.splitlines()[0] == "# Freitag, 16.10.2026"
    assert "**Info:** HO :house_with_garden:" in md
    # Focus vor Recap, leere Abschnitte fehlen
    assert md.index("## Focus") < md.index("## Recap") and "Other Topics" not in md and "SOS" not in md
    assert "- VMWare licensing :hourglass_flowing_sand:" in md and "- Prakti Laptop :construction:" in md
    assert md.endswith("[Post in #improver-squad öffnen](https://slack/p1)")


def test_render_markdown_no_post():
    assert "noch kein Focus-Post" in F.render_markdown(None, DAY)


@pytest.fixture
def violet(tmp_path):
    v = Violet.__new__(Violet)
    v.store = Store(tmp_path)
    v.dm = "DVIOLET"
    v.cfg = MagicMock(focus_channel="CFOCUS")
    v.bot = MagicMock()
    v.bot.conversations_canvases_create.return_value = {"canvas_id": "F_CANVAS"}
    v.user = MagicMock()
    v.slack = MagicMock()
    v.slack.canvas_blocks.return_value = ("TITLE", ["old1", "old2"])
    v.slack.now.return_value = DAY
    v.slack.permalink.return_value = "https://slack/p1"
    v.slack.today_post.return_value = {"text": POST, "ts": "2", "root_ts": "1"}
    return v


def _changes(violet):
    return [c.kwargs["changes"][0] for c in violet.bot.canvases_edit.call_args_list]


def test_canvas_created_then_only_text_under_title_replaced(violet):
    violet.refresh_focus_canvas()
    create = violet.bot.conversations_canvases_create.call_args.kwargs
    assert create["channel_id"] == "DVIOLET" and create["title"] == "Daily Focus"
    violet.refresh_focus_canvas()          # unverändert → kein API-Aufruf
    violet.bot.canvases_edit.assert_not_called()
    violet.slack.today_post.return_value = {"text": POST.replace(":construction:", ":white_check_mark:"),
                                            "ts": "2", "root_ts": "1"}
    violet.refresh_focus_canvas()
    ch = _changes(violet)
    # neuer Text hinter den Titel, dann die alten Blöcke weg – der Titel selbst bleibt
    assert ch[0]["operation"] == "insert_after" and ch[0]["section_id"] == "TITLE"
    assert "- Prakti Laptop :white_check_mark:" in ch[0]["document_content"]["markdown"]
    assert ch[1:] == [{"operation": "delete", "section_id": "old1"}, {"operation": "delete", "section_id": "old2"}]
    assert all(c.get("section_id") != "TITLE" or c["operation"] == "insert_after" for c in ch)


def test_canvas_without_title_is_replaced_whole(violet):
    violet.store.set("canvas_id", "F_CANVAS")
    violet.slack.canvas_blocks.return_value = (None, ["a"])
    violet.refresh_focus_canvas()
    assert [c["operation"] for c in _changes(violet)] == ["replace"]


def test_canvas_already_exists(violet):
    violet.bot.conversations_canvases_create.side_effect = SlackApiError(
        "x", {"ok": False, "error": "channel_canvas_already_exists"})
    violet.user.conversations_info.return_value = {"channel": {"properties": {"canvas": {"file_id": "F_OLD"}}}}
    violet.refresh_focus_canvas()
    assert violet.bot.canvases_edit.call_args.kwargs["canvas_id"] == "F_OLD"
    assert violet.store.get("canvas_id") == "F_OLD"


def test_canvas_block_ids_from_html():
    from violet.slackops import _TopLevelIds
    html = ('<div class="quip-canvas-content"><h1 id="T">Daily Focus</h1><h1 id="D">Freitag</h1>'
            '<p id="P" class="line"><b>Info:</b> HO <control id="C1"><img src="x">:house:</img></control></p>'
            '<div data-section-style="5"><ul id="U"><li id="L1" value="1"><span id="L1">a</span><br/></li>'
            '<li id="L2"><span id="L2">b</span><br/></li></ul></div><p id="Z">Link</p></div>')
    p = _TopLevelIds()
    p.feed(html)
    assert p.ids == ["T", "D", "P", "L1", "L2", "Z"]
