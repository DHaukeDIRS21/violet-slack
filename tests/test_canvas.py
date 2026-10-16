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
    assert md.splitlines()[0] == "# :dart: Focus – Freitag, 16.10.2026"
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
    v.slack = MagicMock()
    v.slack.now.return_value = DAY
    v.slack.permalink.return_value = "https://slack/p1"
    v.slack.today_post.return_value = {"text": POST, "ts": "2", "root_ts": "1"}
    return v


def test_canvas_created_then_edited_only_on_change(violet):
    violet.refresh_focus_canvas()
    violet.bot.conversations_canvases_create.assert_called_once()
    assert violet.bot.conversations_canvases_create.call_args.kwargs["channel_id"] == "DVIOLET"
    violet.refresh_focus_canvas()          # unverändert → kein API-Aufruf
    violet.bot.canvases_edit.assert_not_called()
    violet.slack.today_post.return_value = {"text": POST.replace(":construction:", ":white_check_mark:"),
                                            "ts": "2", "root_ts": "1"}
    violet.refresh_focus_canvas()
    edit = violet.bot.canvases_edit.call_args.kwargs
    assert edit["canvas_id"] == "F_CANVAS" and edit["changes"][0]["operation"] == "replace"
    assert "- Prakti Laptop :white_check_mark:" in edit["changes"][0]["document_content"]["markdown"]
    violet.bot.conversations_canvases_create.assert_called_once()


def test_canvas_already_exists(violet):
    violet.bot.conversations_canvases_create.side_effect = SlackApiError(
        "x", {"ok": False, "error": "channel_canvas_already_exists"})
    violet.bot.conversations_info.return_value = {"channel": {"properties": {"canvas": {"file_id": "F_OLD"}}}}
    violet.refresh_focus_canvas()
    assert violet.bot.canvases_edit.call_args.kwargs["canvas_id"] == "F_OLD"
    assert violet.store.get("canvas_id") == "F_OLD"
