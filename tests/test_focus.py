from violet.focus import parse_post, render_post

POST = """Info: MyCorner :office:
Recap :checkered_flag::
• Fix broken Slack SSO :white_check_mark:
• VMWare lizenzing :hourglass_flowing_sand:
Focus :dart::
• Mobile phone inventur :white_check_mark:
• Fix broken laptop battery
• Daily SysAdmin Requests :construction:
Other Topics :zustimmen: (unplanned):
• Prepare sparepart laptop for AR :white_check_mark:
:sos::
:information_source::"""


def test_parse():
    post = parse_post(POST)
    assert post["info"] == "MyCorner :office:"
    assert post["recap"][1] == {"text": "VMWare lizenzing", "status": "waiting"}
    assert post["focus"][1] == {"text": "Fix broken laptop battery", "status": "open"}
    assert post["focus"][2]["status"] == "wip"
    assert post["other"] == [{"text": "Prepare sparepart laptop for AR", "status": "done"}]
    assert post["sos"] == "" and post["information"] == ""


def test_roundtrip():
    assert render_post(parse_post(POST)) == POST


def test_other_users_style():
    post = parse_post("*Info: Bench* :working:\n\n*Recap:*\n• School\n*Focus:*\n• Sprint Tickets\n• Deployment")
    assert post["info"] == "Bench :working:"
    assert [i["text"] for i in post["focus"]] == ["Sprint Tickets", "Deployment"]


def test_sos_text():
    post = parse_post(POST.replace(":sos::", ":sos:: Drucker brennt"))
    assert post["sos"] == "Drucker brennt"
    assert ":sos:: Drucker brennt" in render_post(post)
