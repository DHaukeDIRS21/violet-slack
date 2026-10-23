from unittest.mock import MagicMock

import pytest

from violet import focus as F
from violet.app import Violet
from violet.store import Store

POST = """Info: HO :house_with_garden:
Recap :checkered_flag::
• Setup my Laptop :white_check_mark:
Focus :dart::
• Sophos Whitelisting Launchpad App :hourglass_flowing_sand:
• Schedule Bogy
• Daily SysAdmin Requests :construction:
Other Topics :zustimmen: (unplanned):
• Invite testgroup for sysadmin :construction:
:sos::
:information_source::"""


def test_ensure_daily():
    post = F.parse_post(POST)                      # Daily steht im Focus mit :construction:, im Recap fehlt es
    post["focus"].insert(0, {"text": "daily sysadmin requests", "status": "done"})
    out = F.ensure_daily(post)
    assert out["recap"][-1] == {"text": "Daily SysAdmin Requests", "status": "done"}
    assert out["focus"][-1] == {"text": "Daily SysAdmin Requests", "status": "wip"}
    assert sum("daily sysadmin" in i["text"].lower() for i in out["focus"] + out["recap"]) == 2
    rendered = F.render_post(out)
    assert "• Daily SysAdmin Requests :white_check_mark:\nFocus :dart::" in rendered
    assert "• Daily SysAdmin Requests :construction:\nOther Topics" in rendered


def test_new_post_gets_daily(violet):
    violet.slack.today_post.return_value = None
    violet.llm = MagicMock()
    violet.llm.new_focus_post.return_value = {"info": "HO", "recap": [{"text": "Laptop", "status": "done"}],
                                              "focus": [{"text": "VPN", "status": "open"}], "other": [],
                                              "sos": "", "information": ""}
    violet.answer_focus("Focus: VPN", None)
    post = violet.preview.call_args.args[0]["post"]
    assert [i["text"] for i in post["recap"]] == ["Laptop", "Daily SysAdmin Requests"]
    assert post["focus"][-1] == {"text": "Daily SysAdmin Requests", "status": "wip"}


def test_cancelled_roundtrip():
    post = F.parse_post(POST.replace("• Schedule Bogy\n", "• Schedule Bogy :x:\n"))
    bogy = next(i for i in post["focus"] if i["text"] == "Schedule Bogy")
    assert bogy["status"] == "cancelled"
    assert "• Schedule Bogy :x:" in F.render_post(post)
    assert "cancelled" in F.POST_SCHEMA["properties"]["focus"]["items"]["properties"]["status"]["enum"]


def test_split_topics():
    assert F.split_topics("VPN für Praktikant, Drucker 2. OG; • Mailtastic") == \
        ["VPN für Praktikant", "Drucker 2. OG", "Mailtastic"]


def test_add_focus_items_before_daily_and_no_duplicates():
    post = F.add_focus_items(F.parse_post(POST), ["VPN für Praktikant", "schedule bogy"])
    assert [i["text"] for i in post["focus"]] == [
        "Sophos Whitelisting Launchpad App", "Schedule Bogy", "VPN für Praktikant", "Daily SysAdmin Requests"]
    assert post["focus"][2]["status"] == "open"
    # Rest unverändert
    assert post["other"] == F.parse_post(POST)["other"] and post["recap"] == F.parse_post(POST)["recap"]
    assert "• VPN für Praktikant\n• Daily SysAdmin Requests :construction:" in F.render_post(post)


@pytest.fixture
def violet(tmp_path):
    v = Violet.__new__(Violet)
    v.store = Store(tmp_path)
    v.say = MagicMock()
    v.preview = MagicMock()
    v.slack = MagicMock()
    v.slack.today_post.return_value = {"ts": "2", "root_ts": "1", "text": POST}
    return v


@pytest.mark.parametrize("cmd", ["focus + VPN für Praktikant", "Focus+ VPN für Praktikant",
                                 "ergänze VPN für Praktikant", "focus ergänzen: VPN für Praktikant"])
def test_command_updates_todays_post(violet, cmd):
    violet.handle_command(cmd)
    draft = violet.preview.call_args.args[0]
    assert draft["target_ts"] == "2" and draft["root_ts"] == "1"
    assert "VPN für Praktikant" in [i["text"] for i in draft["post"]["focus"]]


@pytest.mark.parametrize("cmd,topic", [
    ("focus GPO Timeserver and Printer Leipzig", "GPO Timeserver and Printer Leipzig"),
    ("Focus Install RustDesk on Cancellara-02", "Install RustDesk on Cancellara-02"),
    ('focus "Install RustDesk on Cancellara-02"', "Install RustDesk on Cancellara-02"),
])
def test_bare_focus_topic_adds(violet, cmd, topic):
    violet.handle_command(cmd)
    assert topic in [i["text"] for i in violet.preview.call_args.args[0]["post"]["focus"]]


def test_focus_colon_answer_is_not_bare_command(violet):
    violet.store.set("state", {"mode": "awaiting_focus", "previous": None})
    violet.answer_focus = MagicMock()
    violet.handle_command("Focus: Drucker")
    violet.answer_focus.assert_called_once()


def test_second_focus_today_keeps_recap(violet):
    """Nachgestellt vom 21.10.: zweites `focus` mit heutigem Post darf den Recap nicht neu bauen."""
    violet.suggest_todos = MagicMock()
    violet.llm = MagicMock()
    edited = F.parse_post(POST)
    edited["recap"] = [{"text": "Schedule Bogy", "status": "open"}]   # Claude „baut“ falschen Recap
    edited["focus"].append({"text": "GPO Timeserver", "status": "open"})
    violet.llm.edit_focus_post.return_value = edited
    violet.start_focus()
    assert "der Recap bleibt" in violet.say.call_args_list[0].args[0]
    violet.handle_command("1 MyCorner\n3 GPO Timeserver")
    violet.llm.new_focus_post.assert_not_called()
    post = violet.preview.call_args.args[0]["post"]
    assert post["recap"] == F.parse_post(POST)["recap"]                # Recap unverändert
    assert "GPO Timeserver" in [i["text"] for i in post["focus"]]


def test_command_while_answering_focus(violet):
    violet.store.set("state", {"mode": "awaiting_focus", "previous": None, "todo_picks": ["Aus To-do"]})
    violet.handle_command("focus + Drucker 2. OG, Mailtastic")
    assert violet.store.get("state")["todo_picks"] == ["Aus To-do", "Drucker 2. OG", "Mailtastic"]
    violet.preview.assert_not_called()


def test_command_without_post(violet):
    violet.slack.today_post.return_value = None
    violet.handle_command("focus + RZ Patching")      # „RZ“ setzt hier keinen Slack-Status
    assert "noch keinen Focus-Post" in violet.say.call_args.args[0]
