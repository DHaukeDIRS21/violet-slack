"""Kleiner SQLite-Speicher: Gesprächszustand, Entwürfe, Einstellungen.

Alles hier ist rekonstruierbar – geht die Datei verloren, findet Violet den
heutigen Focus-Post wieder in Slack und der nächste Digest deckt 24 h ab.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path


class Store:
    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(data_dir / "violet.sqlite3", check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, value TEXT NOT NULL);
                """
            )
            self._db.commit()

    # --- key/value -------------------------------------------------------
    def get(self, key: str, default=None):
        with self._lock:
            row = self._db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key: str, value) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
            self._db.commit()

    def delete(self, key: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM kv WHERE key = ?", (key,))
            self._db.commit()

    # --- drafts (Vorschauen mit Posten/Ändern/Abbrechen) ------------------
    def new_draft(self, draft: dict) -> str:
        draft_id = uuid.uuid4().hex[:12]
        self.save_draft(draft_id, draft)
        return draft_id

    def save_draft(self, draft_id: str, draft: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO drafts (id, value) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET value = excluded.value",
                (draft_id, json.dumps(draft)),
            )
            self._db.commit()

    def get_draft(self, draft_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def delete_draft(self, draft_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
            self._db.commit()
