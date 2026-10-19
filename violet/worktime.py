"""Arbeitszeit für Violets Benachrichtigungen (Live-DMs).

Mo–Fr ab 8:00, Ende um 17:30 – oder früher, sobald du Violet „Feierabend“ schreibst.
Außerhalb kommen nur VIPs und Monitoring-Eskalationen durch.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta


def parse_hhmm(value: str) -> time:
    h, m = value.strip().split(":")
    return time(int(h), int(m))


def is_work_time(now: datetime, start: time, end: time, feierabend_day: str | None) -> bool:
    if now.weekday() >= 5:
        return False
    if not start <= now.time() < end:
        return False
    return feierabend_day != now.date().isoformat()


def next_work_start(now: datetime, start: time) -> datetime:
    """Nächster Arbeitsbeginn nach `now` (Mo–Fr) – dann läuft der Feierabend-Status ab."""
    day = now.date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return datetime.combine(day, start, tzinfo=now.tzinfo)
