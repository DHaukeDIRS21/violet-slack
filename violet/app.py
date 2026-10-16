"""Violet – persönlicher Slack-Assistent für Daniel.

Befehle per DM an Violet: siehe HELP_TEXT. Violet postet nie ohne Klick auf ✅ Posten.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from datetime import timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from slack_bolt import App
from slack_bolt.error import BoltError
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError

from . import focus as F
from .config import Config, load_dotenv
from .llm import Claude, LLMError
from .slackops import SlackOps, make_client
from .store import Store

log = logging.getLogger("violet")

HELP_TEXT = """*Was ich kann:*
• `focus` – Focus of the day für #improver-squad
• `@channel :information_source: Titel` + Text – zweisprachiger Post in #allgemein
• `allgemein: Text` – Post in #allgemein, unverändert
• `status Mailtastic erledigt, arbeite an Prakti Laptop, warte VMWare` – aktualisiert deinen heutigen Focus-Post (erledigt :white_check_mark:, arbeite an :construction:, warte :hourglass_flowing_sand:)
• `unplanned Drucker 2. OG, Teams-Ausfall Vertrieb erledigt` – ergänzt ungeplante Themen unter Other Topics in deinem heutigen Post (ohne Status: :construction:)
• `digest` oder `digest 48` – DM-Zusammenfassung (seit letztem Digest bzw. letzte 48 h)
• `live an` / `live aus` – neue DMs sofort hier anzeigen (Standard: an)
• `abbrechen` – laufenden Vorgang beenden
Ich poste nie ohne deinen Klick auf :white_check_mark: Posten."""

FOCUS_QUESTIONS = """*Für heute – antworte in einer Nachricht:*
1. *Info:* Wo arbeitest du? (MyCorner / HO / OoO …)
2. *Recap:* Was von gestern ist erledigt / läuft / wartet? (ohne Angabe: Status bleibt)
3. *Focus:* Was sind deine Ziele für heute?
4. *Other Topics:* Was kam ungeplant dazu?
5. *SOS / Info* fürs Team (optional)"""

REQUIRED_USER_SCOPES = {"chat:write", "channels:history", "im:history", "im:read",
                        "mpim:history", "mpim:read", "users:read", "files:read", "files:write"}
REQUIRED_BOT_SCOPES = {"chat:write", "im:history", "im:write", "users:read", "files:write"}

NOT_UNDERSTOOD = "Das habe ich nicht verstanden. Z. B. „Mailtastic erledigt“, `focus`, `digest` – oder `hilfe`."

STATUS_WORDS = re.compile(
    r"\b(erledigt|done|fertig|arbeite an|arbeite am|in arbeit|läuft|wartet|warte|warten|blockiert)\b",
    re.IGNORECASE,
)
CHANNEL_MENTION = re.compile(r"^\s*(<!channel>|@channel)\s*", re.IGNORECASE)


def chunk(text: str, size: int = 2900) -> list[str]:
    parts, current = [], ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > size and current:
            parts.append(current)
            current = ""
        current += line
    return parts + [current] if current else parts


def quote(text: str, limit: int = 400) -> str:
    text = text.strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + " …"
    return "\n".join("> " + line for line in text.splitlines()) or "> "


def forward_text(who: str, draft: dict) -> str:
    """Weiterleitung nach #dirs21_sysadmin (`who`: User- U… oder Gruppen-ID S…, leer = keine Erwähnung):
    @sysmin :incoming_envelope: Anfrage von @Name (per DM an mich):
    <Text>
    :paperclip: datei.png"""
    mention = (f"<!subteam^{who}> " if who.startswith("S") else f"<@{who}> ") if who else ""
    text = draft.get("text", "").strip()
    if len(text) > 3500:
        text = text[:3500].rstrip() + " …"
    lines = [f"{mention}:incoming_envelope: Anfrage von <@{draft['user']}> (per DM an mich):"]
    if text:
        lines.append(text)
    lines += [f":paperclip: {f.get('name') or 'Datei'}" for f in draft.get("files") or []]
    return "\n".join(lines)


class Violet:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.app = App(token=cfg.bot_token)
        self.bot = self.app.client
        self.user = make_client(cfg.user_token)
        self.store = Store(cfg.data_dir)
        self.slack = SlackOps(self.user, cfg.owner_user_id, cfg.focus_channel, cfg.timezone)
        self.llm = Claude(cfg.model)
        self.dm = self.bot.conversations_open(users=cfg.owner_user_id)["channel"]["id"]
        self._register()

    # ======================================================================
    # Slack-Plumbing
    # ======================================================================
    def say(self, text: str, blocks: list | None = None) -> str:
        resp = self.bot.chat_postMessage(channel=self.dm, text=text, blocks=blocks)
        return resp["ts"]

    def _register(self) -> None:
        self.app.event("message")(self._on_message)
        self.app.action("violet_post")(self._on_post)
        self.app.action("violet_edit")(self._on_edit)
        self.app.action("violet_cancel")(self._on_cancel)
        self.app.action("violet_forward")(self._on_forward)

    def _guard(self, fn, *args) -> None:
        try:
            fn(*args)
        except LLMError as exc:
            self.say(f":warning: {exc}")
        except Exception as exc:  # noqa: BLE001 – Fehler sichtbar machen statt schweigen
            log.exception("Fehler")
            self.say(f":warning: Fehler: `{exc}`")

    def _on_message(self, event: dict) -> None:
        if event.get("subtype") not in (None, "file_share"):
            return
        channel = event.get("channel")
        if channel == self.dm:
            if event.get("user") == self.cfg.owner_user_id and not event.get("bot_id"):
                self._guard(self.handle_command, event.get("text") or "")
        elif event.get("channel_type") in ("im", "mpim"):
            self._guard(self.live_forward, event)

    # ======================================================================
    # Routing
    # ======================================================================
    def handle_command(self, text: str) -> None:
        raw = text.strip()
        cmd = raw.lower()
        state = self.store.get("state") or {}

        if cmd in ("hilfe", "help", "?"):
            self.say(HELP_TEXT)
            return
        if cmd in ("abbrechen", "cancel", "stop"):
            self.store.delete("state")
            self.say("Ok, abgebrochen.")
            return
        if cmd == "focus":
            return self.start_focus()
        if m := re.fullmatch(r"digest(?:\s+(\d+))?\s*h?", cmd):
            return self.digest(int(m.group(1)) if m.group(1) else None)
        if m := re.fullmatch(r"live\s+(an|aus|on|off)", cmd):
            on = m.group(1) in ("an", "on")
            self.store.set("live", on)
            self.say(f"Live-DMs {'an' if on else 'aus'}.")
            return

        if state.get("mode") == "awaiting_focus":
            self.store.delete("state")
            return self.answer_focus(raw, state.get("previous"))
        if state.get("mode") == "awaiting_edit":
            self.store.delete("state")
            return self.apply_edit(state["draft_id"], raw)

        if cmd.startswith("allgemein:"):
            body = raw.split(":", 1)[1].strip()
            return self.preview({"kind": "allgemein", "text": body})
        if CHANNEL_MENTION.match(raw):
            return self.start_announcement(raw)
        if cmd.startswith("unplanned"):
            return self.update_focus(raw)
        if cmd.startswith("status"):
            return self.update_focus(raw[len("status"):].strip())
        if STATUS_WORDS.search(raw):
            return self.update_focus(raw)
        self.say(NOT_UNDERSTOOD)

    # ======================================================================
    # Focus of the day
    # ======================================================================
    def start_focus(self) -> None:
        # Gibt es heute schon einen Post, ist der der aktuelle Stand (und wird beim Posten aktualisiert).
        last, label = self.slack.today_post(), "Dein heutiger Post (wird aktualisiert)"
        if not last:
            last, label = self.slack.last_post(), "Dein letzter Post"
        previous = F.parse_post(last["text"]) if last else None
        self.store.set("state", {"mode": "awaiting_focus", "previous": previous})
        intro = f"*{label}:*\n{last['text']}\n\n" if last else "_Keinen früheren Post gefunden._\n\n"
        self.say(intro + FOCUS_QUESTIONS)

    def answer_focus(self, answer: str, previous: dict | None) -> None:
        self.say(":hourglass_flowing_sand: Baue deinen Focus …")
        today = self.slack.now().strftime("%A, %d.%m.%Y")
        post = self.llm.new_focus_post(previous, answer, today)
        existing = self.slack.today_post()
        self.preview({
            "kind": "focus",
            "post": post,
            "target_ts": existing["ts"] if existing else None,
            "root_ts": existing["root_ts"] if existing else None,
        })

    def update_focus(self, instruction: str) -> None:
        existing = self.slack.today_post()
        if not existing:
            self.say("Ich finde heute noch keinen Focus-Post von dir. Starte mit `focus`.")
            return
        self.say(":hourglass_flowing_sand: Aktualisiere deinen Focus …")
        current = F.parse_post(existing["text"])
        post = self.llm.edit_focus_post(current, instruction)
        self.preview({
            "kind": "focus", "post": post,
            "target_ts": existing["ts"], "root_ts": existing["root_ts"],
        })

    def publish_focus(self, draft: dict) -> str:
        text = F.render_post(draft["post"])
        ch = self.cfg.focus_channel
        if draft.get("target_ts"):
            self.user.chat_update(channel=ch, ts=draft["target_ts"], text=text)
            return self.slack.permalink(ch, draft["target_ts"], draft["root_ts"])
        root = self.slack.today_root()
        if not root:
            root = self.user.chat_postMessage(channel=ch, text="Focus of the day")["ts"]
        ts = self.user.chat_postMessage(channel=ch, thread_ts=root, text=text)["ts"]
        return self.slack.permalink(ch, ts, root)

    # ======================================================================
    # #allgemein
    # ======================================================================
    def start_announcement(self, raw: str) -> None:
        rest = CHANNEL_MENTION.sub("", raw, count=1)
        first, _, body = rest.partition("\n")
        title = first.replace(":information_source:", "").strip()
        body = body.strip() or title
        self.say(":hourglass_flowing_sand: Formuliere deinen Post …")
        text = self.llm.bilingual_announcement(title, body, self.cfg.signature)
        self.preview({"kind": "allgemein", "text": text})

    def publish_allgemein(self, draft: dict) -> str:
        ch = self.cfg.allgemein_channel
        ts = self.user.chat_postMessage(channel=ch, text=draft["text"])["ts"]
        return self.slack.permalink(ch, ts)

    # ======================================================================
    # Vorschau / Buttons
    # ======================================================================
    def draft_text(self, draft: dict) -> str:
        return F.render_post(draft["post"]) if draft["kind"] == "focus" else draft["text"]

    def draft_title(self, draft: dict) -> str:
        if draft["kind"] == "focus":
            what = "Update deines heutigen Posts" if draft.get("target_ts") else "neuer Post"
            return f"*Vorschau → <#{self.cfg.focus_channel}> ({what})*"
        return f"*Vorschau → <#{self.cfg.allgemein_channel}>*"

    def _preview_blocks(self, draft: dict, footer: str | None, draft_id: str | None) -> list:
        text = self.draft_text(draft)
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": self.draft_title(draft)}}]
        blocks += [{"type": "section", "text": {"type": "mrkdwn", "text": part}} for part in chunk(text)]
        if footer:
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": footer}]})
        if draft_id:
            blocks.append({"type": "actions", "elements": [
                {"type": "button", "action_id": "violet_post", "style": "primary", "value": draft_id,
                 "text": {"type": "plain_text", "text": "✅ Posten"}},
                {"type": "button", "action_id": "violet_edit", "value": draft_id,
                 "text": {"type": "plain_text", "text": "✏️ Ändern"}},
                {"type": "button", "action_id": "violet_cancel", "style": "danger", "value": draft_id,
                 "text": {"type": "plain_text", "text": "✖️ Abbrechen"}},
            ]})
        return blocks

    def preview(self, draft: dict) -> None:
        draft_id = self.store.new_draft(draft)
        ts = self.say(self.draft_title(draft), self._preview_blocks(draft, None, draft_id))
        draft["preview_ts"] = ts
        self.store.save_draft(draft_id, draft)

    def _finish_preview(self, draft: dict, footer: str) -> None:
        self.bot.chat_update(
            channel=self.dm, ts=draft["preview_ts"], text=self.draft_title(draft),
            blocks=self._preview_blocks(draft, footer, None),
        )

    def _on_post(self, ack, body) -> None:
        ack()
        draft_id = body["actions"][0]["value"]

        def run():
            draft = self.store.get_draft(draft_id)
            if not draft:
                self.say("Dieser Entwurf ist nicht mehr da – bitte neu starten.")
                return
            if draft["kind"] == "focus":
                link = self.publish_focus(draft)
                verb = "Aktualisiert" if draft.get("target_ts") else "Gepostet"
            else:
                link = self.publish_allgemein(draft)
                verb = "Gepostet"
            self.store.delete_draft(draft_id)
            self._finish_preview(draft, f":white_check_mark: {verb}: <{link}|ansehen>")

        self._guard(run)

    def _on_edit(self, ack, body) -> None:
        ack()
        draft_id = body["actions"][0]["value"]

        def run():
            draft = self.store.get_draft(draft_id)
            if not draft:
                return
            self._finish_preview(draft, ":pencil2: Wird geändert …")
            self.store.set("state", {"mode": "awaiting_edit", "draft_id": draft_id})
            self.say("Was soll ich ändern? (z. B. „Punkt 3 raus“, „englischer Teil förmlicher“)")

        self._guard(run)

    def apply_edit(self, draft_id: str, instruction: str) -> None:
        draft = self.store.get_draft(draft_id)
        if not draft:
            self.say("Dieser Entwurf ist nicht mehr da – bitte neu starten.")
            return
        self.store.delete_draft(draft_id)
        if draft["kind"] == "focus":
            draft["post"] = self.llm.edit_focus_post(draft["post"], instruction)
        else:
            draft["text"] = self.llm.edit_text(draft["text"], instruction)
        draft.pop("preview_ts", None)
        self.preview(draft)

    def _on_cancel(self, ack, body) -> None:
        ack()
        draft_id = body["actions"][0]["value"]

        def run():
            draft = self.store.get_draft(draft_id)
            if draft:
                self.store.delete_draft(draft_id)
                self._finish_preview(draft, ":x: Verworfen.")
            if (self.store.get("state") or {}).get("draft_id") == draft_id:
                self.store.delete("state")

        self._guard(run)

    # ======================================================================
    # DM-Digest
    # ======================================================================
    def digest(self, hours: int | None) -> None:
        self.say(":hourglass_flowing_sand: Sammle deine DMs …")
        now = self.slack.now()
        if hours:
            oldest = (now - timedelta(hours=hours)).timestamp()
        else:
            oldest = self.store.get("last_digest") or (now - timedelta(hours=24)).timestamp()

        convs = self.slack.collect_dms(oldest, skip={self.dm})
        period = f"{self.slack.fmt_time(str(oldest), True)} – {now.strftime('%d.%m. %H:%M')}"
        if not convs:
            self.store.set("last_digest", time.time())
            self.say(f":incoming_envelope: *DM-Digest* {period}\nKeine neuen DMs.")
            return

        total = sum(len(c["messages"]) for c in convs)
        prompt = []
        for c in convs:
            prompt.append(f"### conversation {c['channel']} ({c['label']})")
            for m in c["messages"]:
                who = "DU" if m.get("user") == self.cfg.owner_user_id else self.slack.author(m)
                text = (m.get("text") or "").strip()[:1500]
                prompt.append(f"[{self.slack.fmt_time(m['ts'], True)} ts={m['ts']}] {who}: {text}")
            prompt.append("")
        result = self.llm.digest(self.slack.name(self.cfg.owner_user_id), "\n".join(prompt))

        by_id = {c["channel"]: c for c in convs}
        sections = {"needs_reply": [], "fyi": [], "answered": []}
        for item in result["items"]:
            conv = by_id.get(item["conversation"])
            if not conv or item["category"] not in sections:
                continue
            who = f"<@{conv['partner']}|{conv['label']}>" if conv["partner"] else f"*{conv['label']}*"
            link = self.slack.permalink(conv["channel"], item["message_ts"] or conv["messages"][-1]["ts"])
            sections[item["category"]].append(f"• {who} – {item['summary']} (<{link}|öffnen>)")

        lines = [f":incoming_envelope: *DM-Digest* {period} ({total} Nachrichten von {len(convs)} Personen/Chats)"]
        for key, head in (("needs_reply", ":red_circle: *Braucht Antwort*"),
                          ("fyi", ":large_yellow_circle: *FYI*"),
                          ("answered", ":white_check_mark: *Bereits beantwortet*")):
            if sections[key]:
                lines += ["", head, *sections[key]]
        text = "\n".join(lines)
        self.say(text, [{"type": "section", "text": {"type": "mrkdwn", "text": p}} for p in chunk(text)])
        self.store.set("last_digest", time.time())

    # ======================================================================
    # Live-DMs
    # ======================================================================
    def live_forward(self, event: dict) -> None:
        if not self.store.get("live", True):
            return
        sender = event.get("user")
        if not sender or sender == self.cfg.owner_user_id or event.get("bot_id"):
            return
        channel, ts = event["channel"], event["ts"]
        thread = event.get("thread_ts")
        name = self.slack.name(sender)
        link = self.slack.permalink(channel, ts, thread)
        text = event.get("text") or ""
        files = [{k: f.get(k) for k in ("id", "name", "mimetype", "permalink",
                                         "url_private", "url_private_download")}
                 for f in event.get("files") or []]
        msg = f":speech_balloon: *{name}* · <{link}|antworten>\n" + quote(
            f"`{self.slack.fmt_time(ts)}` {text}"
        )
        if files:
            msg += "\n" + "  ".join(f":paperclip: <{f['permalink']}|{f['name'] or 'Datei'}>" for f in files)
        draft_id = self.store.new_draft({"kind": "forward", "user": sender, "text": text, "link": link,
                                         "files": files})
        self.say(msg, [
            {"type": "section", "text": {"type": "mrkdwn", "text": msg}},
            {"type": "actions", "elements": [{
                "type": "button", "action_id": "violet_forward", "value": draft_id,
                "text": {"type": "plain_text", "text": "➡️ An #dirs21_sysadmin"},
            }]},
        ])
        self.share_images(self.bot, self.dm, files)

    def share_images(self, client, channel: str, files: list[dict], thread_ts: str | None = None) -> None:
        """Bilder aus einer DM in `channel` hochladen. Klappt das nicht (fehlende Scopes),
        bleibt der :paperclip:-Link in der Nachricht."""
        for f in files:
            if not (f.get("mimetype") or "").startswith("image/"):
                continue
            data = self.slack.download(f)
            if data is None:
                log.warning("Bild %s nicht ladbar – Scope files:read fehlt?", f.get("id"))
                continue
            try:
                client.files_upload_v2(channel=channel, thread_ts=thread_ts, content=data,
                                       filename=f.get("name") or "bild.png")
            except SlackApiError as exc:
                log.warning("Bild-Upload fehlgeschlagen (%s) – Scope files:write fehlt?",
                            exc.response.get("error"))

    def _on_forward(self, ack, body) -> None:
        ack()
        draft_id = body["actions"][0]["value"]
        message = body.get("message", {})

        def run():
            draft = self.store.get_draft(draft_id)
            if not draft:
                self.say("Diese Nachricht ist nicht mehr da.")
                return
            ch = self.cfg.sysadmin_channel
            ts = self.user.chat_postMessage(channel=ch, text=forward_text(self.cfg.sysadmin_mention, draft))["ts"]
            self.share_images(self.user, ch, draft.get("files") or [], thread_ts=ts)
            self.store.delete_draft(draft_id)
            blocks = [b for b in message.get("blocks", []) if b.get("type") != "actions"]
            blocks.append({"type": "context", "elements": [{
                "type": "mrkdwn", "text": f":arrow_right: Weitergeleitet: <{self.slack.permalink(ch, ts)}|ansehen>"}]})
            self.bot.chat_update(channel=self.dm, ts=message["ts"], text=message.get("text", ""), blocks=blocks)

        self._guard(run)

    # ======================================================================
    def check_setup(self) -> list[str]:
        """Prüft Token-Besitzer und Scopes; liefert eine Liste von Problemen."""
        problems = []
        for label, client, required in (("User-Token", self.user, REQUIRED_USER_SCOPES),
                                        ("Bot-Token", self.bot, REQUIRED_BOT_SCOPES)):
            resp = client.auth_test()
            granted = {x.strip() for x in resp.headers.get("x-oauth-scopes", "").split(",") if x.strip()}
            missing = sorted(required - granted)
            if granted and missing:
                problems.append(f"{label}: fehlende Scopes `{', '.join(missing)}` – Manifest prüfen "
                                "und App neu installieren (Reinstall to Workspace).")
            if label == "User-Token" and resp.get("user_id") != self.cfg.owner_user_id:
                problems.append(f"User-Token gehört <@{resp.get('user_id')}>, nicht <@{self.cfg.owner_user_id}> "
                                "– Violet würde unter falschem Namen posten.")
        return problems

    def run(self) -> None:
        problems = self.check_setup()
        for p in problems:
            log.error(p)
        today = self.slack.now().date().isoformat()
        if problems:
            self.say(":warning: *Violet ist gestartet, aber:*\n" + "\n".join(f"• {p}" for p in problems))
        elif self.store.get("last_hello") != today:
            self.say(":wave: Violet läuft wieder. Schreib `hilfe` für alle Befehle.")
        self.store.set("last_hello", today)
        SocketModeHandler(self.app, self.cfg.app_token).start()


FATAL_SLACK_ERRORS = {"invalid_auth", "not_authed", "account_inactive", "token_revoked",
                      "token_expired", "not_allowed_token_type", "missing_scope", "invalid_token"}


def main() -> None:
    base = Path(__file__).resolve().parents[1]  # Installationsordner (enthält .env)
    env_file = os.environ.get("VIOLET_ENV_FILE")
    if not env_file:
        env_file = ".env" if Path(".env").is_file() else str(base / ".env")
    load_dotenv(Path(env_file))
    os.environ.setdefault("VIOLET_DATA_DIR", str(base / "data"))

    # Logging zuerst – unter pythonw (Autostart) gibt es keine Konsole, nur diese Datei.
    data_dir = Path(os.environ["VIOLET_DATA_DIR"])
    data_dir.mkdir(parents=True, exist_ok=True)
    handlers = [RotatingFileHandler(data_dir / "violet.log", maxBytes=2_000_000,
                                    backupCount=3, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log.info("Violet startet (env: %s)", env_file)
    try:
        _start(Config.from_env())
    except Exception:
        log.exception("Violet beendet wegen Fehler")
        sys.exit(1)


def _start(cfg: Config) -> None:
    # Beim Hochfahren ist das Netz (WLAN/VPN) oft noch nicht da – geduldig warten.
    # Falsche Tokens dagegen werden nicht besser: dann sofort klar abbrechen.
    delay = 10
    while True:
        try:
            violet = Violet(cfg)
            break
        except BoltError as exc:  # Bolt prüft den Bot-Token beim Start selbst
            raise RuntimeError(f"Slack lehnt den Bot-Token ab ({exc}). SLACK_BOT_TOKEN in der .env prüfen.") from exc
        except SlackApiError as exc:
            if exc.response.get("error") in FATAL_SLACK_ERRORS:
                raise RuntimeError(
                    f"Slack lehnt einen Token ab ({exc.response.get('error')}). Tokens in der .env "
                    "prüfen; nach Manifest-Änderungen die App neu installieren."
                ) from exc
            log.warning("Start fehlgeschlagen (%s) – neuer Versuch in %s s", exc, delay)
        except Exception as exc:  # noqa: BLE001 – meist Netzwerk
            log.warning("Start fehlgeschlagen (%s) – neuer Versuch in %s s", exc, delay)
        time.sleep(delay)
        delay = min(delay * 2, 300)
    log.info("Violet läuft.")
    violet.run()


if __name__ == "__main__":
    main()
