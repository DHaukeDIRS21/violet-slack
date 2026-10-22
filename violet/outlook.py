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


TEAMS = re.compile(r"https://teams\.microsoft\.com/(?:l/meetup-join|meet)/[^\s|>\"]+")
ITEM_ID = re.compile(r"[?&]itemid=([^&|>\s]+)")
OUTLOOK_LINK = re.compile(r"<(?P<url>https://outlook\.[^|>]+)\|(?P<title>[^>]+)>")
WHERE = re.compile(r"\*Where:\*\s*([^\n]+)")


def item_id(url: str | None) -> str | None:
    m = ITEM_ID.search(html.unescape(url or ""))
    return m.group(1) if m else None


def join_url(event: dict) -> str | None:
    """Teams-Beitrittslink: bevorzugt der „Join“-Button, sonst der erste Teams-Link im Text."""
    for att in event.get("attachments") or []:
        for act in att.get("actions") or []:
            if (act.get("text") or "").lower().startswith("join") and act.get("url"):
                return html.unescape(act["url"])
    for att in event.get("attachments") or []:
        if m := TEAMS.search(att.get("text") or ""):
            return html.unescape(m.group(0))
    return None


def teams_links(event: dict) -> dict:
    """{itemid: Teams-Link} aus einer Einzelmeldung – damit kommt der Link später auch in die Erinnerung."""
    join = join_url(event)
    if not join:
        return {}
    ids = {}
    for att in event.get("attachments") or []:
        for src in (att.get("title_link"), att.get("title"), att.get("text")):
            if src and (i := item_id(src)):
                ids[i] = join
    return ids


def parse_upcoming(event: dict) -> dict | None:
    """„:loudspeaker: _1 minute until this event:_“ → {'lead', 'start', 'end', 'title', 'url', 'where', 'join'}."""
    for att in event.get("attachments") or []:
        pre = att.get("pretext") or ""
        if "until this event" not in pre:
            continue
        head = att.get("title") or ""
        stamps = [int(s) for s in DATE.findall(head)]
        link_m = OUTLOOK_LINK.search(head)
        where = WHERE.search(att.get("text") or "")
        lead = re.sub(r"[:_]", "", pre.replace(":loudspeaker:", "")).replace("until this event", "").strip()
        lead = re.sub(r"(\d+)\s*minutes?", r"\1 Min", lead)
        return {
            "lead": lead,
            "start": stamps[0] if stamps else None,
            "end": stamps[1] if len(stamps) > 1 else None,
            "title": html.unescape(link_m.group("title")) if link_m else html.unescape(DATE.sub("", head)).strip(),
            "url": link_m.group("url") if link_m else None,
            "where": html.unescape("; ".join(dict.fromkeys(p.strip() for p in where.group(1).split(";")))) if where else "",
            "join": join_url(event),
        }
    return None


def change_note(event: dict) -> str | None:
    """Kurztext für Änderungen/Absagen: „Ort geändert“, „abgesagt“ …"""
    for att in event.get("attachments") or []:
        pre = (att.get("pretext") or "").lower()
        if "cancelled" in pre or "canceled" in pre:
            return "Serie abgesagt" if "series" in pre else "abgesagt"
        if "updated" in pre:
            for en, de in (("location", "Ort geändert"), ("recurrence time", "Serienzeit geändert"),
                           ("recurrence", "Serie geändert"), ("time", "Zeit geändert")):
                if en in pre:
                    return de
            return "geändert"
    return None


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
