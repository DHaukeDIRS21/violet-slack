"""Mittagsbestellung aus einem Slack-Thread zusammenfassen (`essen` + kopierter Thread oder Thread-Link)."""

from __future__ import annotations

import re

COMMAND = re.compile(r"^\s*(?:essen|mittagessen|mittag|bestellung(?:en)?|lunch)\b\s*:?\s*(?P<rest>\S.*)$",
                     re.IGNORECASE | re.DOTALL)
# https://dirs21.slack.com/archives/C123/p1792565269691899?thread_ts=1792562948.604219&cid=C123
LINK = re.compile(r"https://[\w.-]+\.slack\.com/archives/(?P<channel>[A-Z0-9]+)/p(?P<sec>\d{10})(?P<frac>\d{6})"
                  r"(?:\S*?thread_ts=(?P<thread>\d+\.\d+))?")


def thread_ref(text: str) -> tuple[str, str] | None:
    """(channel, thread_ts) aus einem Slack-Link im Text – der Link darf auf irgendeine Nachricht im
    Thread zeigen; ohne thread_ts ist die verlinkte Nachricht selbst der Thread-Anfang."""
    m = LINK.search(text or "")
    if not m:
        return None
    return m.group("channel"), m.group("thread") or f"{m.group('sec')}.{m.group('frac')}"


PLUS_ONE = re.compile(r"^\+\d+(?![\dx×])")


def split_extras(text: str) -> tuple[str, list[str]]:
    """Zeilen, die mit „+“ beginnen, sind Zusatzbestellungen (nicht im Thread) – Rest bleibt Thread/Link."""
    rest, extras = [], []
    for line in (text or "").splitlines():
        # „+1“/„+1 zu Tom“ aus einem kopierten Thread ist eine Thread-Nachricht, kein Zusatz
        if line.lstrip().startswith("+") and not PLUS_ONE.match(line.lstrip()):
            if entry := line.lstrip()[1:].strip():
                extras.append(entry)
        else:
            rest.append(line)
    return "\n".join(rest).strip(), extras


def with_extras(thread: str, extras: list[str]) -> str:
    if not extras:
        return thread
    return (thread + "\n\nZUSÄTZLICHE BESTELLUNGEN (nicht im Thread, zählen voll mit; je Zeile Person und "
            "Gericht in beliebiger Reihenfolge, ggf. mit Anzahl):\n" + "\n".join(f"- {e}" for e in extras))


def render(result: dict) -> str:
    dishes = [d for d in result.get("dishes") or [] if d.get("orders")]
    for d in dishes:
        d["total"] = sum(max(1, o.get("count") or 1) for o in d["orders"])
    dishes.sort(key=lambda d: (-d["total"], d["dish"].lower()))
    people = {o["person"] for d in dishes for o in d["orders"]}
    total = sum(d["total"] for d in dishes)
    lines = [f":fork_and_knife: *Mittagsbestellung* – {total} Gerichte für {len(people)} Personen", ""]
    for d in dishes:
        who = []
        for o in d["orders"]:
            label = o["person"] + (f" ({o['count']}×)" if (o.get("count") or 1) > 1 else "")
            if o.get("note"):
                label += f" _({o['note']})_"
            who.append(label)
        lines.append(f"• *{d['total']}× {d['dish']}* – {', '.join(who)}")
    if result.get("unclear"):
        lines += ["", ":grey_question: *Unklar – bitte prüfen:*"] + [f"• {u}" for u in result["unclear"]]
    if not dishes:
        lines.append("_Keine Bestellungen erkannt._")
    return "\n".join(lines)
