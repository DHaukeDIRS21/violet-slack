"""Outlook-Calendar-App (Slack): Termine aus der Tagesübersicht lesen.

Tagesübersicht (7:30):  text „*Today*-<!date^…>“, je Termin ein Attachment:
    <!date^1791977400^{time}|…>-<!date^1791982800^{time}|…> *<https://outlook…|Titel>*
    Microsoft Teams Meeting; DIRS21 - Konferenzraum Wernau
    *Going?* Yes
    All-day *<https://outlook…|Titel>*
Einzelmeldungen: pretext „_Event instance cancelled._“ / „_Event updated! …_“, title „Titel (mail@…)“.
"""

from __future__ import annotations

import html
import re

DATE = re.compile(r"<!date\^(\d+)\^")
TITLE = re.compile(r"\*<(?P<url>[^|>]+)\|(?P<title>[^>]+)>\*")
GOING = re.compile(r"\*Going\?\*\s*(\w+)")
EMAIL_SUFFIX = re.compile(r"\s*\([^()@\s]+@[^()\s]+\)\s*$")


def is_agenda(event: dict) -> bool:
    return (event.get("text") or "").startswith("*Today*")


def parse_agenda(event: dict) -> list[dict]:
    """[{'start', 'end', 'title', 'url', 'where', 'going', 'all_day'}] in Reihenfolge der Übersicht."""
    items = []
    for att in event.get("attachments") or []:
        text = att.get("text") or att.get("fallback") or ""
        m = TITLE.search(text)
        if not m:
            continue
        lines = text.splitlines()
        stamps = [int(s) for s in DATE.findall(lines[0])] if lines else []
        where = lines[1].strip() if len(lines) > 1 and not lines[1].startswith("*Going?*") else ""
        # „Microsoft Teams Meeting; Raum; Raum; Raum“ → doppelte Orte raus
        where = "; ".join(dict.fromkeys(p.strip() for p in where.split(";") if p.strip()))
        going = GOING.search(text)
        items.append({
            "start": stamps[0] if stamps else None,
            "end": stamps[1] if len(stamps) > 1 else None,
            "title": html.unescape(m.group("title").strip()),
            "url": m.group("url"),
            "where": html.unescape(where),
            "going": going.group(1) if going else "",
            "all_day": text.lstrip().lower().startswith("all-day") or not stamps,
        })
    return items


def parse_change(event: dict) -> dict | None:
    """{'kind': 'cancelled'|'updated', 'title'} für Einzelmeldungen, sonst None."""
    for att in event.get("attachments") or []:
        pre = (att.get("pretext") or "").lower()
        title = EMAIL_SUFFIX.sub("", html.unescape(att.get("title") or "")).strip()
        if not title:
            continue
        if "cancelled" in pre or "canceled" in pre:
            return {"kind": "cancelled", "title": title}
        if "updated" in pre:
            return {"kind": "updated", "title": title}
    return None


def link(item: dict) -> str:
    title = item["title"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"<{item['url']}|{title}>" if item.get("url") else title
