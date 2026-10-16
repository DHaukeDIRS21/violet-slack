"""Standard-Status für Slack, per kurzer Nachricht an Violet („ich geh laufen“, „Feierabend“ …)."""

from __future__ import annotations

import re
from datetime import date

# (Name, Emoji, Text, Muster) – das erste passende Muster gewinnt, deshalb Spezielles zuerst.
PRESETS = [
    ("laufen", ":man-running::skin-tone-2:", "laufen",
     r"\b(laufen|joggen|lauf(e|en)? gehen|geh(e)? laufen)\b"),
    ("rz", ":office:", "datacenter",
     r"\b(rz|rechenzentrum|datacenter|data center)\b"),
    ("buero", ":blue_car:", "On the Road to Office :office:",
     r"\b(fahre|fahr|auf dem weg)\b.*\b(büro|buero|office)\b|\bins (büro|buero|office)\b"),
    ("unterwegs", ":blue_car:", "Unterwegs",
     r"\bunterwegs\b"),
    ("fokus", ":fokuszeit:", "Bitte nicht stören",
     r"\b(nicht stören|nicht stoeren|in ruhe|fokus(zeit)?|dnd)\b"),
    ("feierabend", ":x:", None,
     r"\b(feierabend|schluss für heute|bin weg)\b"),
]

CLEAR = re.compile(r"^\s*(status\s+(weg|löschen|loeschen|aus|leer|clear)|bin (wieder )?da|zurück|zurueck)\s*[.!]*\s*$",
                   re.IGNORECASE)
MAX_LEN = 60  # längere Nachrichten sind keine Status-Befehle (z. B. Focus-Antworten)


def feierabend_text(day: date) -> str:
    """Freitag (und Wochenende): bis Montag – sonst morgen wieder."""
    return "Feierabend - bis Montag" if day.weekday() >= 4 else "Feierabend - morgen wieder"


def match(text: str, day: date) -> dict | None:
    """{'emoji', 'text'} für einen Status-Befehl, {'emoji': '', 'text': ''} zum Löschen, sonst None."""
    text = (text or "").strip()
    if not text or len(text) > MAX_LEN or "\n" in text:
        return None
    if CLEAR.match(text):
        return {"name": "clear", "emoji": "", "text": ""}
    low = text.lower()
    for name, emoji, status_text, pattern in PRESETS:
        if re.search(pattern, low):
            return {"name": name, "emoji": emoji, "text": status_text or feierabend_text(day)}
    return None
