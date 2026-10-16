"""Eskalation: Opsgenie/Datadog-Meldungen in #monitoring-torz / #monitoring-wernau erkennen.

Opsgenie postet neue Alerts als Bot-Nachricht mit Attachment-Titel, z. B.
    #90129: [Datadog] [Warn] TORZ Server - Freier Festplattenspeicher ist unter 10 % auf Edberg-03
„closed“/„acknowledged“-Meldungen haben keinen Titel und lösen nichts aus.
"""

from __future__ import annotations

import re
import time

# Teile des Titels, die eskaliert werden (Groß-/Kleinschreibung egal)
PATTERNS = [
    "Freier Festplattenspeicher ist unter 10",
    "sendet keine Daten mehr",
    "WARNING: Controller rebooted unexpectedly",
    "DIRS21 Messaging Failed Messages",
    "DIRS21 Messaging Mail Queue",
    "BackupDrive nicht mehr verbunden",
    "Failed",
    "Free RAM is low on",
]

ALERT_NUMBER = re.compile(r"^\s*#\d+:\s*")
# daniel.hauke closed alert <https://eu.opsg.in/…|#90129> "[Datadog] [Warn] TORZ Server - …"
CLOSED = re.compile(r'closed alert\s*<[^|>]*\|#\d+>\s*"(.+)"', re.IGNORECASE)


def key(title: str) -> str:
    """Titel ohne #Nummer, klein – damit Alert und „closed“-Meldung zusammenpassen."""
    return ALERT_NUMBER.sub("", title).strip().lower()


def closed(event: dict) -> dict | None:
    """{'title', 'by'} wenn die Nachricht ein Alert schließt, sonst None."""
    for att in event.get("attachments") or []:
        text = att.get("text") or att.get("fallback") or ""
        if m := CLOSED.search(text):
            return {"title": m.group(1).strip(), "by": text[: m.start()].strip()}
    return None


def alerts(event: dict) -> list[dict]:
    """[{'title', 'link', 'pattern'}] für alle Attachment-Titel, die auf ein Muster passen."""
    found = []
    for att in event.get("attachments") or []:
        title = (att.get("title") or "").strip()
        low = title.lower()
        pattern = next((p for p in PATTERNS if p.lower() in low), None)
        if pattern:
            found.append({"title": title, "link": att.get("title_link"), "pattern": pattern})
    return found


class Dedup:
    """Gleiche Meldung (ohne #Nummer) innerhalb von `window` Sekunden nur einmal melden."""

    def __init__(self, window: float = 15 * 60):
        self.window = window
        self._seen: dict[str, float] = {}

    def first(self, channel: str, title: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        k = f"{channel}|{key(title)}"
        self._seen = {s: t for s, t in self._seen.items() if now - t < self.window}
        if k in self._seen:
            return False
        self._seen[k] = now
        return True

    def forget(self, channel: str, title: str) -> None:
        """Nach „closed“: die nächste gleiche Meldung wieder sofort melden."""
        self._seen.pop(f"{channel}|{key(title)}", None)
