"""Brücke zum Violet-Backend: neue Slack-DMs liest der Violet-Avatar vor.

Ruft `POST {VIOLET_BACKEND_URL}/slack/notify` im Hintergrund auf – Slack-Events werden
dadurch nicht aufgehalten, und ein Ausfall des Backends stört den Slack-Bot nicht.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import urllib.request

log = logging.getLogger("violet.avatar")

_MENTION = re.compile(r"<@([A-Z0-9]+)(?:\|[^>]*)?>")
_LINK = re.compile(r"<(https?://[^|>]+)(?:\|([^>]*))?>")
_SPECIAL = re.compile(r"<!(here|channel|everyone)[^>]*>")


def plain(text: str, name) -> str:
    """Slack-Markup in vorlesbaren Text: @-Erwähnungen → Namen, Links → Linktext."""
    text = _MENTION.sub(lambda m: "@" + name(m.group(1)), text or "")
    text = _LINK.sub(lambda m: m.group(2) or "Link", text)
    text = _SPECIAL.sub(lambda m: "@" + m.group(1), text)
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").strip()


class Avatar:
    def __init__(self, url: str, token: str, user_id: str):
        self.url, self.token, self.user_id = url, token, user_id

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.token)

    def announce(self, sender: str, text: str, conversation: str | None = None) -> None:
        if not self.enabled or not text.strip():
            return
        body = {"sender": sender, "text": text, "conversation": conversation, "user_id": self.user_id}
        threading.Thread(target=self._post, args=(body,), daemon=True).start()

    def _post(self, body: dict) -> None:
        req = urllib.request.Request(
            self.url + "/slack/notify", data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "X-API-Key": self.token},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                log.info("Avatar: %s vorgelesen (%s)", body["sender"], resp.status)
        except Exception as exc:  # noqa: BLE001 – Backend weg? Slack läuft trotzdem weiter.
            log.warning("Avatar: Vorlesen fehlgeschlagen (%s)", exc)
