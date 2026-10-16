"""Standard-Status für Slack, per kurzer Nachricht an Violet („ich geh laufen“, „Feierabend“ …).

Eigene Status legst du direkt in Violet an (`status neu :emoji: Text = wort, wort`); sie liegen
im Store unter „custom_status“ und werden vor den eingebauten geprüft.
"""

from __future__ import annotations

import re
from datetime import date

# (Name, Emoji, Text, Muster, Beispiele für `status liste`) – das erste passende Muster gewinnt,
# deshalb Spezielles zuerst.
PRESETS = [
    ("laufen", ":man-running::skin-tone-2:", "laufen",
     r"\b(laufen|joggen|lauf(e|en)? gehen|geh(e)? laufen)\b", "laufen, joggen"),
    ("rz", ":office:", "datacenter",
     r"\b(rz|rechenzentrum|datacenter|data center)\b", "RZ, Rechenzentrum, datacenter"),
    ("buero", ":blue_car:", "On the Road to Office :office:",
     r"\b(fahre|fahr|auf dem weg)\b.*\b(büro|buero|office)\b|\bins (büro|buero|office)\b", "ich fahre ins Büro"),
    ("unterwegs", ":blue_car:", "Unterwegs",
     r"\bunterwegs\b", "unterwegs"),
    ("fokus", ":fokuszeit:", "Bitte nicht stören",
     r"\b(nicht stören|nicht stoeren|in ruhe|fokus(zeit)?|dnd)\b", "nicht stören, in Ruhe, Fokus"),
    ("feierabend", ":x:", None,
     r"\b(feierabend|schluss für heute|bin weg)\b", "Feierabend (Mo–Do „morgen wieder“, Fr–So „bis Montag“)"),
]

CLEAR = re.compile(r"^\s*(status\s+(weg|löschen|loeschen|aus|leer|clear)|bin (wieder )?da|zurück|zurueck)\s*[.!]*\s*$",
                   re.IGNORECASE)
MAX_LEN = 60  # längere Nachrichten sind keine Status-Befehle (z. B. Focus-Antworten)

# Verwaltung eigener Status
EMOJI = r":[a-z0-9_+\-']+:(?::skin-tone-[2-6]:)?"
NEW = re.compile(rf"^\s*status\s+(?:neu|hinzufügen|hinzufuegen|add)\s+(?P<emoji>{EMOJI})\s*(?P<text>[^=\n]+?)\s*=\s*(?P<words>[^\n]+?)\s*$",
                 re.IGNORECASE)
REMOVE = re.compile(r"^\s*status\s+(?:entfernen|remove)\s+(?P<text>.+?)\s*$", re.IGNORECASE)
LIST = re.compile(r"^\s*status\s+(?:liste|list|vorlagen|alle)\s*$", re.IGNORECASE)


def feierabend_text(day: date) -> str:
    """Freitag (und Wochenende): bis Montag – sonst morgen wieder."""
    return "Feierabend - bis Montag" if day.weekday() >= 4 else "Feierabend - morgen wieder"


def _words_pattern(words: list[str]) -> str:
    return r"\b(" + "|".join(re.escape(w.lower()) for w in words) + r")\b"


def match(text: str, day: date, custom: list[dict] | None = None) -> dict | None:
    """{'name', 'emoji', 'text'} für einen Status-Befehl, emoji/text leer zum Löschen, sonst None."""
    text = (text or "").strip()
    if not text or len(text) > MAX_LEN or "\n" in text:
        return None
    if CLEAR.match(text):
        return {"name": "clear", "emoji": "", "text": ""}
    low = text.lower()
    for c in custom or []:
        if re.search(_words_pattern(c["words"]), low):
            return {"name": "custom", "emoji": c["emoji"], "text": c["text"]}
    for name, emoji, status_text, pattern, _ in PRESETS:
        if re.search(pattern, low):
            return {"name": name, "emoji": emoji, "text": status_text or feierabend_text(day)}
    return None


def parse_new(text: str) -> dict | None:
    """`status neu :emoji: Text = wort, wort` → {'emoji', 'text', 'words'} oder None."""
    m = NEW.match(text or "")
    if not m:
        return None
    words = [w.strip() for w in re.split(r"[,;]| oder ", m.group("words")) if w.strip()]
    status_text = m.group("text").strip()
    if not words or not status_text:
        return None
    return {"emoji": m.group("emoji"), "text": status_text[:100], "words": words}


def add_custom(custom: list[dict], new: dict) -> list[dict]:
    """Neuer Status (gleicher Text ersetzt den alten); neueste zuerst."""
    rest = [c for c in custom if c["text"].lower() != new["text"].lower()]
    return [new] + rest


def remove_custom(custom: list[dict], text: str) -> tuple[list[dict], dict | None]:
    key = text.strip().lower()
    hit = next((c for c in custom if c["text"].lower() == key or key in (w.lower() for w in c["words"])), None)
    return [c for c in custom if c is not hit], hit


def listing(custom: list[dict]) -> str:
    lines = ["*Deine Status* (Violet nimmt den ersten passenden):"]
    if custom:
        lines.append("_Eigene:_")
        lines += [f"• {c['emoji']} {c['text']} ← {', '.join(c['words'])}" for c in custom]
    lines.append("_Eingebaut:_")
    lines += [f"• {emoji} {text or 'Feierabend …'} ← {examples}" for _, emoji, text, _, examples in PRESETS]
    lines += ["", "Neu: `status neu :fork_and_knife: Mittagspause = mittag, essen` · "
              "Entfernen: `status entfernen Mittagspause` · Löschen des aktuellen Status: `status weg`"]
    return "\n".join(lines)
