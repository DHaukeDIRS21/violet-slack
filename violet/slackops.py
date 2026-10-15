"""Slack-Lesezugriffe mit dem User-Token (Focus-Thread finden, DMs sammeln)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

from .focus import looks_like_focus_post

FOCUS_ROOT_MARKER = "focus of the day"


def make_client(token: str) -> WebClient:
    client = WebClient(token=token)
    client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=3))
    return client


class SlackOps:
    def __init__(self, user_client: WebClient, owner_id: str, focus_channel: str, tz: str):
        self.user = user_client
        self.owner_id = owner_id
        self.focus_channel = focus_channel
        self.tz = ZoneInfo(tz)
        self._names: dict[str, str] = {}
        self._base_url = user_client.auth_test()["url"].rstrip("/")

    # --- Helfer -----------------------------------------------------------
    def now(self) -> datetime:
        return datetime.now(self.tz)

    def day_start(self, day: datetime | None = None) -> float:
        day = day or self.now()
        return day.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    def permalink(self, channel: str, ts: str, thread_ts: str | None = None) -> str:
        link = f"{self._base_url}/archives/{channel}/p{ts.replace('.', '')}"
        if thread_ts and thread_ts != ts:
            link += f"?thread_ts={thread_ts}&cid={channel}"
        return link

    def name(self, user_id: str) -> str:
        if user_id not in self._names:
            try:
                profile = self.user.users_info(user=user_id)["user"]
                self._names[user_id] = (
                    profile.get("profile", {}).get("real_name")
                    or profile.get("real_name")
                    or profile.get("name")
                    or user_id
                )
            except SlackApiError:
                self._names[user_id] = user_id
        return self._names[user_id]

    def fmt_time(self, ts: str, with_date: bool = False) -> str:
        dt = datetime.fromtimestamp(float(ts), self.tz)
        return dt.strftime("%d.%m. %H:%M" if with_date else "%H:%M")

    # --- Focus of the day ---------------------------------------------------
    def _focus_roots(self, oldest: float) -> list[dict]:
        roots, cursor = [], None
        while True:
            resp = self.user.conversations_history(
                channel=self.focus_channel, oldest=str(oldest), limit=200, cursor=cursor
            )
            roots += [
                m for m in resp["messages"]
                if FOCUS_ROOT_MARKER in (m.get("text") or "").lower()
                and m.get("thread_ts", m["ts"]) == m["ts"]
            ]
            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
        return sorted(roots, key=lambda m: float(m["ts"]), reverse=True)

    def _my_reply(self, root_ts: str) -> dict | None:
        resp = self.user.conversations_replies(channel=self.focus_channel, ts=root_ts, limit=200)
        mine = [
            m for m in resp["messages"][1:]
            if m.get("user") == self.owner_id and looks_like_focus_post(m.get("text", ""))
        ]
        return mine[-1] if mine else None

    def today_root(self) -> str | None:
        roots = self._focus_roots(self.day_start())
        return roots[-1]["ts"] if roots else None  # der erste Thread des Tages

    def today_post(self) -> dict | None:
        """{'ts', 'root_ts', 'text'} deines heutigen Posts – direkt aus Slack."""
        for root in self._focus_roots(self.day_start()):
            reply = self._my_reply(root["ts"])
            if reply:
                return {"ts": reply["ts"], "root_ts": root["ts"], "text": reply.get("text", "")}
        return None

    def last_post(self, days: int = 21) -> dict | None:
        """Dein letzter Focus-Post vor heute."""
        oldest = self.day_start(self.now() - timedelta(days=days))
        today = self.day_start()
        for root in self._focus_roots(oldest):
            if float(root["ts"]) >= today:
                continue
            reply = self._my_reply(root["ts"])
            if reply:
                return {"ts": reply["ts"], "root_ts": root["ts"], "text": reply.get("text", "")}
        return None

    # --- DMs ------------------------------------------------------------------
    def _dm_channels(self, skip: set[str]) -> list[dict]:
        channels, cursor = [], None
        while True:
            resp = self.user.users_conversations(
                types="im,mpim", exclude_archived=True, limit=200, cursor=cursor
            )
            channels += [c for c in resp["channels"] if c["id"] not in skip]
            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
        return channels

    def _history(self, channel: str, oldest: float) -> list[dict]:
        try:
            resp = self.user.conversations_history(channel=channel, oldest=str(oldest), limit=200)
        except SlackApiError as exc:
            if exc.response.get("error") in ("channel_not_found", "not_in_channel", "missing_scope"):
                return []
            raise
        return [m for m in resp["messages"] if m.get("subtype") in (None, "bot_message", "file_share")]

    def collect_dms(self, oldest: float, skip: set[str]) -> list[dict]:
        """[{'channel', 'label', 'partner', 'messages': [...]}] mit Nachrichten seit `oldest`."""
        channels = self._dm_channels(skip)

        def load(ch: dict) -> dict | None:
            msgs = self._history(ch["id"], oldest)
            if not msgs:
                return None
            msgs.sort(key=lambda m: float(m["ts"]))
            if ch.get("is_im"):
                partner = ch.get("user", "")
                label = self.name(partner)
            else:
                partner = ""
                members = {m.get("user") for m in msgs if m.get("user") and m.get("user") != self.owner_id}
                label = "Gruppe: " + ", ".join(sorted(self.name(u) for u in members if u))
            return {"channel": ch["id"], "label": label, "partner": partner, "messages": msgs}

        with ThreadPoolExecutor(max_workers=6) as pool:
            result = [r for r in pool.map(load, channels) if r]
        return result

    def author(self, msg: dict) -> str:
        if msg.get("user"):
            return self.name(msg["user"])
        return msg.get("username") or msg.get("bot_profile", {}).get("name") or "Bot"
