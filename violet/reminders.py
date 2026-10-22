"""Erinnerungen: „erinnere mich morgen um 9 an …“ – gespeichert im Store, gemeldet in Slack und über den Avatar."""

from __future__ import annotations

import re
import threading
import time
import uuid
from datetime import datetime

ADD = re.compile(r"^\s*(?:erinnere?|erinner)\s+mich\b|^\s*(?:reminder|erinnerung)\s*:?\s+(?!löschen|loeschen|entfernen)\S",
                 re.IGNORECASE)
LIST = re.compile(r"^\s*(?:erinnerungen|reminders?)\s*$", re.IGNORECASE)
DELETE = re.compile(r"^\s*(?:erinnerung|reminder)\s+(?:löschen|loeschen|entfernen|delete)\s+(?P<n>\d+)\s*$|"
                    r"^\s*(?:erinnerung|reminder)\s+(?P<n2>\d+)\s+(?:löschen|loeschen|entfernen|delete)\s*$",
                    re.IGNORECASE)

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def fmt(ts: float, tz) -> str:
    dt = datetime.fromtimestamp(ts, tz)
    return f"{WEEKDAYS[dt.weekday()]} {dt:%d.%m.} um {dt:%H:%M}"


class Reminders:
    """Liste offener Erinnerungen im Store („reminders“), nach Fälligkeit sortiert."""

    _lock = threading.Lock()

    def __init__(self, store):
        self.store = store

    def all(self) -> list[dict]:
        return sorted(self.store.get("reminders") or [], key=lambda r: r["due"])

    def add(self, due: float, text: str, key: str | None = None, title: str | None = None) -> dict | None:
        """`key` (z. B. Outlook-Termin) verhindert Doppelte – dann None. `title` = Termintitel für Absagen."""
        item = {"id": uuid.uuid4().hex[:8], "due": due, "text": text, "created": time.time()}
        if key:
            item["key"] = key
        if title:
            item["title"] = title
        with self._lock:
            items = self.all()
            if key and (key in (r.get("key") for r in items) or key in (self.store.get("reminder_keys_done") or [])):
                return None
            self.store.set("reminders", items + [item])
        return item

    def remove_where(self, pred) -> list[dict]:
        with self._lock:
            items = self.all()
            hit = [r for r in items if pred(r)]
            if hit:
                self.store.set("reminders", [r for r in items if r not in hit])
        return hit

    def remove(self, reminder_id: str) -> dict | None:
        with self._lock:
            items = self.all()
            hit = next((r for r in items if r["id"] == reminder_id), None)
            self.store.set("reminders", [r for r in items if r is not hit])
        return hit

    def pop_due(self, now: float) -> list[dict]:
        """Fällige herausnehmen (sie werden gemeldet) – der Rest bleibt."""
        with self._lock:
            items = self.all()
            due = [r for r in items if r["due"] <= now]
            if due:
                self.store.set("reminders", [r for r in items if r["due"] > now])
                # gemeldete Termin-Schlüssel merken, damit eine nachgeholte Übersicht sie nicht neu anlegt
                keys = [r["key"] for r in due if r.get("key")]
                if keys:
                    self.store.set("reminder_keys_done", ((self.store.get("reminder_keys_done") or []) + keys)[-300:])
        return due
