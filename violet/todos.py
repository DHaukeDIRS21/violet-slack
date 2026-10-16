"""Deine To-dos als Slack-Liste (Lists-API, User-Token mit lists:read/lists:write).

Slacks eigene „To-dos“ (früher „Später“) haben keine öffentliche API – deshalb eine Liste
im To-do-Modus: Titel-Spalte + Erledigt-Häkchen (todo_completed). Violet legt sie beim ersten
Mal selbst an (gehört dir) oder nutzt VIOLET_TODO_LIST.
"""

from __future__ import annotations

from slack_sdk import WebClient

LIST_NAME = "To-dos"


class TodoList:
    def __init__(self, user: WebClient, store, list_id: str | None = None):
        self.user = user
        self.store = store
        self.configured_id = list_id

    def _call(self, method: str, **payload) -> dict:
        return self.user.api_call(method, json=payload).data

    # --- Liste finden/anlegen --------------------------------------------
    def meta(self) -> dict:
        """{'id', 'title_col', 'done_col', 'created'} – legt die Liste beim ersten Mal an."""
        info = self.store.get("todo_list")
        if info and (not self.configured_id or info["id"] == self.configured_id):
            return info
        created = False
        if self.configured_id:
            list_id = self.configured_id
            resp = self._call("slackLists.items.list", list_id=list_id, limit=1, include_list=True)
            schema = (resp.get("list") or {}).get("list_metadata", {}).get("schema") or []
        else:
            resp = self._call("slackLists.create", name=LIST_NAME, todo_mode=True)
            list_id, schema, created = resp["list_id"], resp["list_metadata"]["schema"], True
        info = {
            "id": list_id,
            "title_col": next((c["id"] for c in schema if c.get("is_primary_column")), None),
            "done_col": next((c["id"] for c in schema
                              if c.get("key") == "todo_completed" or c.get("type") in ("todo_completed", "checkbox")),
                             None),
        }
        if not info["done_col"]:
            raise RuntimeError("Die To-do-Liste hat keine Erledigt-Spalte (To-do-Modus/Checkbox).")
        self.store.set("todo_list", info)
        return {**info, "created": created}

    def permalink(self, list_id: str) -> str | None:
        try:
            return self.user.files_info(file=list_id)["file"].get("permalink")
        except Exception:  # noqa: BLE001 – Link ist nur Komfort
            return None

    # --- Einträge ---------------------------------------------------------
    def open_items(self) -> list[dict]:
        """Offene Einträge: [{'id', 'title', 'link'}], älteste zuerst."""
        info = self.meta()
        items, cursor = [], None
        while True:
            resp = self._call("slackLists.items.list", list_id=info["id"], limit=100, **({"cursor": cursor} if cursor else {}))
            items += resp.get("items") or []
            cursor = (resp.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
        result = []
        for it in sorted(items, key=lambda i: float(i.get("date_created") or 0)):
            if it.get("archived") or it.get("parent_record_id"):
                continue
            fields = {f.get("column_id"): f for f in it.get("fields") or []}
            if _is_done(fields.get(info["done_col"])):
                continue
            title_field = fields.get(info["title_col"]) or {}
            title = (title_field.get("text") or _plain(title_field.get("value"))).strip()
            link = next((m.get("value") for f in fields.values() for m in f.get("message") or [] if m.get("value")), None)
            if title or link:
                result.append({"id": it["id"], "title": title or "(Nachricht)", "link": link})
        return result

    def complete(self, row_id: str) -> None:
        info = self.meta()
        self._call("slackLists.items.update", list_id=info["id"],
                   cells=[{"row_id": row_id, "column_id": info["done_col"], "checkbox": True}])  # kein [True]!


def _is_done(field: dict | None) -> bool:
    if not field:
        return False
    box = field.get("checkbox")
    if box is not None:  # Slack liefert mal true, mal [true]
        return bool(box[0] if isinstance(box, list) and box else box)
    return str(field.get("value")).lower() in ("true", "1", "yes", "completed")


def _plain(value) -> str:
    return value if isinstance(value, str) and not value.lstrip().startswith(("[", "{")) else ""
