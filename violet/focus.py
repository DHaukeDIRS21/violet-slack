"""Focus-of-the-day posts for #improver-squad: parse, render, JSON schema.

Format (as posted in the "Focus of the day" thread):

    Info: MyCorner :office:
    Recap :checkered_flag::
    • Fix broken Slack SSO :white_check_mark:
    Focus :dart::
    • VMWare lizenzing :hourglass_flowing_sand:
    Other Topics :zustimmen: (unplanned):
    • Prepare sparepart laptop for AR :white_check_mark:
    :sos::
    :information_source::
"""

from __future__ import annotations

import re

STATUS_EMOJI = {
    "done": ":white_check_mark:",
    "wip": ":construction:",
    "waiting": ":hourglass_flowing_sand:",
    "open": "",
}
EMOJI_STATUS = {v: k for k, v in STATUS_EMOJI.items() if v}

HEADERS = {
    "recap": "Recap :checkered_flag::",
    "focus": "Focus :dart::",
    "other": "Other Topics :zustimmen: (unplanned):",
}

ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "status": {"type": "string", "enum": list(STATUS_EMOJI)},
    },
    "required": ["text", "status"],
    "additionalProperties": False,
}

POST_SCHEMA = {
    "type": "object",
    "properties": {
        "info": {"type": "string"},
        "recap": {"type": "array", "items": ITEM_SCHEMA},
        "focus": {"type": "array", "items": ITEM_SCHEMA},
        "other": {"type": "array", "items": ITEM_SCHEMA},
        "sos": {"type": "string"},
        "information": {"type": "string"},
    },
    "required": ["info", "recap", "focus", "other", "sos", "information"],
    "additionalProperties": False,
}


def empty_post() -> dict:
    return {"info": "", "recap": [], "focus": [], "other": [], "sos": "", "information": ""}


def _parse_item(line: str) -> dict:
    text = re.sub(r"^\s*(?:[•\-*◦▪]|\d+\.)\s*", "", line).strip()
    status = "open"
    for emoji, name in EMOJI_STATUS.items():
        if text.endswith(emoji):
            text = text[: -len(emoji)].strip()
            status = name
            break
    return {"text": text, "status": status}


def _section_of(line: str) -> tuple[str | None, str]:
    """Return (section, rest-of-line) if the line is a section header."""
    plain = line.replace("*", "").strip()
    low = plain.lower()
    if low.startswith("info:"):
        return "info", plain[5:].strip()
    if low.startswith(":sos:"):
        return "sos", plain[5:].lstrip(":").strip()
    if low.startswith(":information_source:"):
        return "information", plain[len(":information_source:"):].lstrip(":").strip()
    for key, word in (("recap", "recap"), ("focus", "focus"), ("other", "other topics")):
        if low.startswith(word):
            # "Recap :checkered_flag::" / "Focus :" / "Other Topics … (unplanned):"
            rest = plain.split("::", 1)[1] if "::" in plain else ""
            if not rest and plain.rstrip().endswith(":"):
                rest = ""
            return key, rest.strip()
    return None, ""


def parse_post(text: str) -> dict:
    post = empty_post()
    section = None
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        new_section, rest = _section_of(line)
        if new_section:
            section = new_section
            if section in ("info", "sos", "information"):
                post[section] = rest
            elif rest:
                post[section].append(_parse_item(rest))
            continue
        if section in ("recap", "focus", "other"):
            post[section].append(_parse_item(line))
        elif section in ("info", "sos", "information"):
            post[section] = (post[section] + "\n" + line.strip()).strip()
    return post


def _render_item(item: dict) -> str:
    emoji = STATUS_EMOJI.get(item.get("status", "open"), "")
    return f"• {item['text'].strip()}" + (f" {emoji}" if emoji else "")


def render_post(post: dict) -> str:
    lines = [f"Info: {post.get('info', '').strip()}".rstrip()]
    for key in ("recap", "focus", "other"):
        lines.append(HEADERS[key])
        lines.extend(_render_item(i) for i in post.get(key, []) if i.get("text", "").strip())
    lines.append(f":sos:: {post.get('sos', '').strip()}".rstrip())
    lines.append(f":information_source:: {post.get('information', '').strip()}".rstrip())
    return "\n".join(lines)


def looks_like_focus_post(text: str) -> bool:
    low = (text or "").lower()
    return "info:" in low and "focus" in low
