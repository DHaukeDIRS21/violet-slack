"""Wrike-Benachrichtigungen (Wrike-App-DMs) erkennen.

    Sarah Pause hat Ihnen ein Element zugewiesen: <https://www.wrike.com/open.htm?id=…|Titel>
    Linda Fröhlich hat Sie in <https://www.wrike.com/open.htm?id=…|Titel> erwähnt
    &gt;@Daniel Hauke kann man schließen oder?
    Wrike Bot hat eine Freigabe in <…|Titel> aktualisiert          → ignorieren
"""

from __future__ import annotations

import html
import re

# Enthält der Titel ein „>“, schneidet Slack den Link dort ab – der Rest steht dann als Text
# hinter dem Link („<url|Titel-Anfang> Rest&gt; erwähnt“) und gehört mit zum Titel.
LINK = r"<(?P<url>[^|>]+)\|(?P<title>[^>]+)>(?P<rest>.*?)"
ASSIGNED = re.compile(rf"^(?P<who>.+?) hat Ihnen ein Element zugewiesen:?\s*{LINK}\s*$", re.IGNORECASE)
MENTIONED = re.compile(rf"^(?P<who>.+?) hat Sie in {LINK} erwähnt\s*$", re.IGNORECASE)


def parse(text: str) -> dict | None:
    """{'kind': 'assigned'|'mentioned', 'who', 'url', 'title', 'comment'} – None = ignorieren
    (aktualisiert, Begrüßung, alles Unbekannte)."""
    lines = (text or "").strip().splitlines()
    if not lines:
        return None
    first = lines[0].strip()
    for kind, pattern in (("assigned", ASSIGNED), ("mentioned", MENTIONED)):
        if m := pattern.match(first):
            comment = "\n".join(re.sub(r"^\s*(&gt;|>)\s?", "", line) for line in lines[1:]).strip()
            return {
                "kind": kind,
                "who": html.unescape(m.group("who").strip()),
                "url": m.group("url"),
                "title": html.unescape((m.group("title") + (">" + m.group("rest") if m.group("rest").strip() else ""))
                                       .strip()).replace(">>", ">"),
                "comment": html.unescape(comment),
            }
    return None


def render(item: dict) -> str:
    title = item["title"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    link = f"<{item['url']}|{title}>"
    if item["kind"] == "assigned":
        return f":new: *Neues Ticket in Wrike* · von {item['who']}\n{link}"
    msg = f":speech_balloon: *Neuer Kommentar für dich* in {link} · von {item['who']}"
    if item["comment"]:
        msg += "\n" + "\n".join("> " + line for line in item["comment"][:1500].splitlines())
    return msg
