"""Violet – persönlicher Slack-Assistent für Daniel.

Befehle per DM an Violet: siehe HELP_TEXT. Violet postet nie ohne Klick auf ✅ Posten.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from slack_bolt import App
from slack_bolt.error import BoltError
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

from . import focus as F
from .avatar import Avatar, plain
from . import lunch as L
from . import monitor as M
from . import status as S
from . import worktime as W
from . import wrike as WR
from .config import Config, load_dotenv
from .llm import Claude, LLMError
from .slackops import SlackOps, make_client
from .store import Store
from .todos import TodoList

log = logging.getLogger("violet")

HELP_TEXT = """*Was ich kann:*
• `focus` – Focus of the day für #improver-squad, mit Vorschlägen aus deiner To-do-Liste (dein heutiger Focus steht immer im Canvas oben in diesem Chat – rechts als Seitenleiste öffnen)
• `@channel :information_source: Titel` + Text – zweisprachiger Post in #allgemein
• `allgemein: Text` – Post in #allgemein, unverändert
• `focus + VPN für Praktikant, Drucker 2. OG` (oder `ergänze …`) – vergessene Themen unter Focus :dart: ergänzen
• `status Mailtastic erledigt, arbeite an Prakti Laptop, warte VMWare` – aktualisiert deinen heutigen Focus-Post (erledigt :white_check_mark:, arbeite an :construction:, warte :hourglass_flowing_sand:, abgesagt/abgebrochen/hat sich erledigt :x:)
• `unplanned Drucker 2. OG, Teams-Ausfall Vertrieb erledigt` – ergänzt ungeplante Themen unter Other Topics in deinem heutigen Post (ohne Status: :construction:)
• `recap` oder `recap 4` – Zusammenfassung deiner Focus-Posts der letzten 3 (bzw. 4) Wochen
• `unslop` + Text – entfernt typische KI-Formulierungen (Unslop-Regeln, gelten auch für meine #allgemein-Posts, Digest und Recap)
• `essen` + kopierter Thread (oder `essen <Link zum Thread>`) – Mittagsbestellung: was wie oft, wer was
• `digest` oder `digest 48` – DM-Zusammenfassung (seit letztem Digest bzw. letzte 48 h)
• `live an` / `live aus` – neue DMs sofort hier anzeigen (Standard: an; außerhalb der Arbeitszeit nur VIPs)
• `arbeitszeit` – Mo–Fr 8:00 bis 17:30 oder „Feierabend“; danach nur VIPs und Monitoring-Alerts
• `vorlesen an` / `vorlesen aus` – Violet-Avatar liest neue DMs vor (Standard: an)
• `eskalation an` / `eskalation aus` – kritische Meldungen aus #monitoring-torz / #monitoring-wernau sofort hier melden (Standard: an)
• Slack-Status: `ich geh laufen` · `ich muss ins RZ` · `Feierabend` (freitags „bis Montag“) · `bin unterwegs` · `ich fahre ins Büro` · `lasst mich in Ruhe` · `status weg`
  eigene: `status neu :fork_and_knife: Mittagspause = mittag, essen` · `status liste` · `status entfernen Mittagspause`
• `abbrechen` – laufenden Vorgang beenden
Ich poste nie ohne deinen Klick auf :white_check_mark: Posten."""

FOCUS_QUESTIONS = """*Für heute – antworte in einer Nachricht:*
1. *Info:* Wo arbeitest du? (MyCorner / HO / OoO …)
2. *Recap:* Was von gestern ist erledigt / läuft / wartet? (ohne Angabe: Status bleibt)
3. *Focus:* Was sind deine Ziele für heute?
4. *Other Topics:* Was kam ungeplant dazu?
5. *SOS / Info* fürs Team (optional)"""

REQUIRED_USER_SCOPES = {"chat:write", "channels:history", "im:history", "im:read",
                        "mpim:history", "mpim:read", "users:read", "files:read", "files:write",
                        "groups:history", "lists:read", "lists:write", "users.profile:write"}
REQUIRED_BOT_SCOPES = {"chat:write", "im:history", "im:write", "users:read", "files:write",
                       "canvases:write"}

CANVAS_TITLE = "Daily Focus"
S_WEEKDAY = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

NOT_UNDERSTOOD ="Das habe ich nicht verstanden. Z. B. „Mailtastic erledigt“, `focus`, `digest` – oder `hilfe`."

STATUS_WORDS = re.compile(
    r"\b(erledigt|done|fertig|arbeite an|arbeite am|in arbeit|läuft|wartet|warte|warten|blockiert"
    r"|abgesagt|abgebrochen|fällt aus|faellt aus|entfällt|entfaellt|storniert|cancelled|canceled)\b",
    re.IGNORECASE,
)
FOCUS_PLUS = re.compile(
    r"^\s*(?:focus\s*\+|focus\s+(?:ergänzen|ergänze|ergaenze|plus)|ergänze|ergänzen|ergaenze)\s*:?\s*(?P<topics>\S.*)$",
    re.IGNORECASE | re.DOTALL,
)
# „focus GPO Timeserver“ (einzeilig, ohne Doppelpunkt) = focus + … – „Focus: …“ bleibt eine Focus-Antwort
FOCUS_BARE = re.compile(r"^\s*focus\s+(?P<topics>[^\s:][^\n]*?)\s*$", re.IGNORECASE)
UNSLOP_CMD = re.compile(r"^\s*unslop\b\s*:?\s*(?P<text>.*)$", re.IGNORECASE | re.DOTALL)
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
        self.bot.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=3))
        self.user = make_client(cfg.user_token)
        self.store = Store(cfg.data_dir)
        self.slack = SlackOps(self.user, cfg.owner_user_id, cfg.focus_channel, cfg.timezone)
        self.llm = Claude(cfg.model)
        self.avatar = Avatar(cfg.backend_url, cfg.backend_token, cfg.backend_user)
        self.dedup = M.Dedup()
        self.todos = TodoList(self.user, self.store, cfg.todo_list or None)
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
        self.app.action("violet_todo_take")(lambda ack, body: self._on_todo(ack, body, take=True))
        self.app.action("violet_todo_defer")(lambda ack, body: self._on_todo(ack, body, take=False))

    def _guard(self, fn, *args) -> None:
        try:
            fn(*args)
        except LLMError as exc:
            self.say(f":warning: {exc}")
        except Exception as exc:  # noqa: BLE001 – Fehler sichtbar machen statt schweigen
            log.exception("Fehler")
            self.say(f":warning: Fehler: `{exc}`")

    def _on_message(self, event: dict) -> None:
        channel = event.get("channel")
        if channel in self.cfg.monitor_channels:
            if event.get("subtype") in (None, "bot_message"):
                self._guard(self.escalate, event)
            return
        if event.get("subtype") not in (None, "file_share"):
            return
        if channel == self.dm:
            if event.get("user") == self.cfg.owner_user_id and not event.get("bot_id"):
                self._guard(self.handle_command, event.get("text") or "")
        elif event.get("channel_type") == "im" and self.cfg.wrike_bot and event.get("user") == self.cfg.wrike_bot:
            self._guard(self.wrike_forward, event)
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
        if m := L.COMMAND.match(raw):
            return self.lunch(m.group("rest"))
        if m := UNSLOP_CMD.match(raw):
            return self.unslop(m.group("text"))
        if m := FOCUS_PLUS.match(raw) or FOCUS_BARE.match(raw):
            return self.add_to_focus(F.split_topics(m.group("topics").strip().strip('"„“')))
        if cmd in ("arbeitszeit", "arbeitszeiten"):
            return self.show_work_time()
        if S.LIST.match(raw):
            return self.say(S.listing(self.store.get("custom_status") or []))
        if re.match(r"^\s*status\s+(neu|hinzufügen|hinzufuegen|add)\b", raw, re.IGNORECASE):
            return self.status_add(raw)
        if m := S.REMOVE.match(raw):
            return self.status_remove(m.group("text"))
        if m := re.fullmatch(r"recap(?:\s+(\d+))?(?:\s*(?:w|wochen?))?", cmd):
            return self.focus_recap(int(m.group(1)) if m.group(1) else 3)
        if m := re.fullmatch(r"digest(?:\s+(\d+))?\s*h?", cmd):
            return self.digest(int(m.group(1)) if m.group(1) else None)
        if m := re.fullmatch(r"live\s+(an|aus|on|off)", cmd):
            on = m.group(1) in ("an", "on")
            self.store.set("live", on)
            self.say(f"Live-DMs {'an' if on else 'aus'}.")
            return
        if m := re.fullmatch(r"vorlesen\s+(an|aus|on|off)", cmd):
            on = m.group(1) in ("an", "on")
            self.store.set("speak", on)
            hint = "" if self.avatar.enabled else " (VIOLET_BACKEND_URL/-TOKEN fehlen in der .env)"
            self.say(f"Vorlesen durch den Violet-Avatar {'an' if on else 'aus'}.{hint}")
            return
        if m := re.fullmatch(r"eskalation\s+(an|aus|on|off)", cmd):
            on = m.group(1) in ("an", "on")
            self.store.set("escalate", on)
            self.say(f"Eskalation aus #monitoring-torz / #monitoring-wernau {'an' if on else 'aus'}.")
            return

        if state.get("mode") == "awaiting_focus":
            self.store.delete("state")
            return self.answer_focus(raw, state.get("previous"), state.get("todo_picks") or [])
        if state.get("mode") == "awaiting_edit":
            self.store.delete("state")
            return self.apply_edit(state["draft_id"], raw)

        is_focus_cmd = cmd.startswith(("status ", "unplanned")) or STATUS_WORDS.search(raw)
        preset = S.match(raw, self.slack.now().date(), self.store.get("custom_status") or [])
        if preset and (preset["name"] == "clear" or not is_focus_cmd):
            return self.set_status(preset)

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
        last, label = self.slack.today_post(), "Dein heutiger Post (wird ergänzt – der Recap bleibt)"
        if not last:
            last, label = self.slack.last_post(), "Dein letzter Post"
        previous = F.parse_post(last["text"]) if last else None
        self.store.set("state", {"mode": "awaiting_focus", "previous": previous})
        intro = f"*{label}:*\n{last['text']}\n\n" if last else "_Keinen früheren Post gefunden._\n\n"
        self.say(intro + FOCUS_QUESTIONS)
        try:
            self.suggest_todos()
        except Exception as exc:  # noqa: BLE001 – Focus soll auch ohne To-do-Liste gehen
            log.warning("To-dos nicht geladen: %s", exc)
            self.say(f"_Deine To-do-Liste konnte ich nicht lesen ({exc})._")

    def answer_focus(self, answer: str, previous: dict | None, todo_picks: list[str] | None = None) -> None:
        if todo_picks:
            answer += "\n\nZusätzliche neue Focus-Ziele (Status open):\n" + \
                      "\n".join(f"- {t}" for t in todo_picks)
        self.say(":hourglass_flowing_sand: Baue deinen Focus …")
        existing = self.slack.today_post()
        if existing:
            # Heute schon gepostet: nur ergänzen. Neu bauen würde den Recap aus dem heutigen Focus
            # erzeugen statt aus dem von gestern – der Recap bleibt deshalb fest.
            current = F.parse_post(existing["text"])
            post = self.llm.edit_focus_post(current, "Ergänzungen/Änderungen für heute (Recap nicht anfassen):\n"
                                            + answer)
            post["recap"] = current["recap"]
        else:
            today = self.slack.now().strftime("%A, %d.%m.%Y")
            post = self.llm.new_focus_post(previous, answer, today)
        self.preview({
            "kind": "focus",
            "post": post,
            "target_ts": existing["ts"] if existing else None,
            "root_ts": existing["root_ts"] if existing else None,
        })

    # --- Unslop -----------------------------------------------------------------
    def unslop(self, text: str) -> None:
        if not text.strip():
            self.say("Schick mir den Text mit: `unslop` und darunter der Text. Ich entferne typische "
                     "KI-Formulierungen und lasse Sprache, Anrede und Inhalt gleich.")
            return
        self.say(":broom: Räume den Text auf …")
        out = self.llm.unslop(text)
        self.say(out, [{"type": "section", "text": {"type": "mrkdwn", "text": p}} for p in chunk(out)])

    # --- Mittagsbestellung ------------------------------------------------------
    def lunch(self, rest: str) -> None:
        if ref := L.thread_ref(rest):
            channel, thread_ts = ref
            msgs, cursor = [], None
            while True:
                resp = self.user.conversations_replies(channel=channel, ts=thread_ts, limit=200,
                                                       **({"cursor": cursor} if cursor else {}))
                msgs += resp["messages"]
                cursor = (resp.get("response_metadata") or {}).get("next_cursor")
                if not cursor:
                    break
            thread = "\n".join(f"{self.slack.author(m)}: {m.get('text') or ''}" for m in msgs)
            source = f"{len(msgs)} Nachrichten aus dem Thread"
        else:
            thread, source = rest, "deinem kopierten Thread"
        self.say(f":hourglass_flowing_sand: Zähle die Bestellungen aus {source} …")
        out = L.render(self.llm.lunch_orders(thread))
        self.say(out, [{"type": "section", "text": {"type": "mrkdwn", "text": p}} for p in chunk(out)])

    # --- Slack-Status ------------------------------------------------------------
    def set_status(self, preset: dict) -> None:
        now = self.slack.now()
        expiration = 0
        if preset["name"] == "feierabend":
            # Arbeitszeit endet jetzt; der Status läuft zum nächsten Arbeitsbeginn ab
            start = W.parse_hhmm(self.cfg.work_start)
            expiration = int(W.next_work_start(now, start).timestamp())
            self.store.set("feierabend_day", now.date().isoformat())
        elif preset["name"] == "clear":
            self.store.delete("feierabend_day")
        self.user.users_profile_set(profile={
            "status_text": preset["text"], "status_emoji": preset["emoji"], "status_expiration": expiration,
        })
        if preset["name"] == "clear":
            self.say(":broom: Status gelöscht.")
        elif preset["name"] == "feierabend":
            until = datetime.fromtimestamp(expiration, now.tzinfo)
            self.say(f":white_check_mark: Status gesetzt: {preset['emoji']} {preset['text']}\n"
                     f":crescent_moon: Feierabend – bis {S_WEEKDAY[until.weekday()]} {until:%H:%M} melde ich nur "
                     "noch VIPs und Monitoring-Alerts.")
        else:
            self.say(f":white_check_mark: Status gesetzt: {preset['emoji']} {preset['text']}")

    def is_work_time(self) -> bool:
        return W.is_work_time(self.slack.now(), W.parse_hhmm(self.cfg.work_start),
                              W.parse_hhmm(self.cfg.work_end), self.store.get("feierabend_day"))

    def show_work_time(self) -> None:
        state = "läuft" if self.is_work_time() else "vorbei – nur VIPs und Monitoring-Alerts"
        if self.store.get("feierabend_day") == self.slack.now().date().isoformat():
            state = "Feierabend – nur VIPs und Monitoring-Alerts (`status weg` holt dich zurück)"
        self.say(f":clock8: *Arbeitszeit* Mo–Fr {self.cfg.work_start}–{self.cfg.work_end} "
                 f"(oder bis „Feierabend“). Gerade: {state}.\n"
                 f"VIPs: {', '.join(f'<@{u}>' for u in self.cfg.vip_users)}")

    def status_add(self, raw: str) -> None:
        new = S.parse_new(raw)
        if not new:
            self.say("So legst du einen Status an: `status neu :fork_and_knife: Mittagspause = mittag, essen`\n"
                     "(Emoji, Statustext, `=`, dann die Wörter, auf die ich reagieren soll – durch Komma getrennt)")
            return
        custom = self.store.get("custom_status") or []
        replaced = any(c["text"].lower() == new["text"].lower() for c in custom)
        self.store.set("custom_status", S.add_custom(custom, new))
        self.say(f":white_check_mark: Status {'geändert' if replaced else 'angelegt'}: {new['emoji']} {new['text']}\n"
                 f"Ich reagiere auf: {', '.join(new['words'])} – probier's mit „{new['words'][0]}“.")

    def status_remove(self, text: str) -> None:
        custom, hit = S.remove_custom(self.store.get("custom_status") or [], text)
        if not hit:
            builtin = any(t and t.lower() == text.strip().lower() for _, _, t, _, _ in S.PRESETS)
            self.say("Eingebaute Status kann ich nicht entfernen – leg einen eigenen mit denselben Wörtern an, "
                     "der hat Vorrang." if builtin else f"Keinen eigenen Status „{text}“ gefunden. `status liste` zeigt alle.")
            return
        self.store.set("custom_status", custom)
        self.say(f":wastebasket: Status entfernt: {hit['emoji']} {hit['text']}")

    # --- To-dos als Focus-Vorschläge -----------------------------------------
    def suggest_todos(self) -> None:
        meta = self.todos.meta()
        today = self.slack.now().date().isoformat()
        deferred = {k for k, d in (self.store.get("todo_deferred") or {}).items() if d == today}
        items = [i for i in self.todos.open_items() if i["id"] not in deferred]
        link = self.todos.permalink(meta["id"])
        list_ref = f"<{link}|To-do-Liste>" if link else "To-do-Liste"
        if meta.get("created"):
            self.say(f":clipboard: Ich habe dir eine Slack-Liste {list_ref} angelegt. Trag dort deine To-dos ein "
                     "(auch per Nachricht → *Zu Liste hinzufügen*) – beim `focus` schlage ich sie dir vor.")
        if not items:
            return
        shown = items[:10]
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text":
                   f":clipboard: *Offene To-dos* aus deiner {list_ref} – in den Focus aufnehmen?"
                   + (f" _(die ersten 10 von {len(items)})_" if len(items) > 10 else "")}}]
        for item in shown:
            title = item["title"][:200] + (" …" if len(item["title"]) > 200 else "")
            text = f"• {title}" + (f"  <{item['link']}|Nachricht>" if item.get("link") else "")
            value = json.dumps({"id": item["id"], "t": item["title"][:1500]}, ensure_ascii=False)
            blocks += [
                {"type": "section", "text": {"type": "mrkdwn", "text": text}},
                {"type": "actions", "block_id": f"todo_{item['id']}", "elements": [
                    {"type": "button", "action_id": "violet_todo_take", "value": value, "style": "primary",
                     "text": {"type": "plain_text", "text": "➕ Aufnehmen"}},
                    {"type": "button", "action_id": "violet_todo_defer", "value": value,
                     "text": {"type": "plain_text", "text": "⏸ Zurückstellen"}},
                ]},
            ]
        self.say(f"{len(items)} offene To-dos", blocks)

    def _on_todo(self, ack, body, take: bool) -> None:
        ack()
        action = body["actions"][0]
        item = json.loads(action["value"])
        message = body.get("message", {})

        def run():
            if take:
                self.todos.complete(item["id"])
                state = self.store.get("state") or {}
                if state.get("mode") == "awaiting_focus":
                    state.setdefault("todo_picks", []).append(item["t"])
                    self.store.set("state", state)
                    note = ":heavy_plus_sign: Kommt in deinen Focus · in der Liste abgehakt"
                elif self.slack.today_post():
                    note = ":heavy_plus_sign: Wird in deinen heutigen Post aufgenommen · in der Liste abgehakt"
                    self.update_focus(f"Neues Focus-Ziel (Status open): {item['t']}")
                else:
                    note = ":heavy_plus_sign: In der Liste abgehakt – starte `focus`, um es einzutragen"
            else:
                deferred = self.store.get("todo_deferred") or {}
                today = self.slack.now().date().isoformat()
                deferred = {k: d for k, d in deferred.items() if d == today}
                deferred[item["id"]] = today
                self.store.set("todo_deferred", deferred)
                note = ":double_vertical_bar: Zurückgestellt – morgen wieder"
            blocks = [{"type": "context", "elements": [{"type": "mrkdwn", "text": note}]}
                      if b.get("block_id") == action.get("block_id") else b
                      for b in message.get("blocks", [])]
            self.bot.chat_update(channel=self.dm, ts=message["ts"], text=message.get("text", ""), blocks=blocks)

        self._guard(run)

    def add_to_focus(self, topics: list[str]) -> None:
        """Vergessene Themen unter Focus :dart: ergänzen – ohne Claude, der Rest bleibt exakt gleich."""
        if not topics:
            self.say("Was soll in den Focus? Z. B. `focus + VPN für Praktikant, Drucker 2. OG`")
            return
        state = self.store.get("state") or {}
        if state.get("mode") == "awaiting_focus":  # Focus wird gerade gebaut → mit in die Antwort
            state["todo_picks"] = (state.get("todo_picks") or []) + topics
            self.store.set("state", state)
            self.say(f":heavy_plus_sign: Kommt mit in deinen Focus: {', '.join(topics)}")
            return
        existing = self.slack.today_post()
        if not existing:
            self.say("Ich finde heute noch keinen Focus-Post von dir. Starte mit `focus`.")
            return
        post = F.add_focus_items(F.parse_post(existing["text"]), topics)
        self.preview({"kind": "focus", "post": post,
                      "target_ts": existing["ts"], "root_ts": existing["root_ts"]})

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

    _canvas_lock = threading.Lock()  # Timer und „Posten“-Klick nicht gleichzeitig

    def focus_recap(self, weeks: int) -> None:
        weeks = max(1, min(weeks, 12))
        self.say(f":hourglass_flowing_sand: Sammle deine Focus-Posts der letzten {weeks} Wochen …")
        posts = self.slack.posts_since(weeks * 7)
        if not posts:
            self.say(f"Keine Focus-Posts von dir in den letzten {weeks} Wochen gefunden.")
            return
        days = [self.slack.fmt_time(p["ts"], True).split()[0] for p in posts]
        period = f"{days[0]} – {days[-1]}"
        text = "\n\n".join(f"### Post vom {F.WEEKDAYS[datetime.fromtimestamp(float(p['ts']), self.slack.tz).weekday()]}, "
                           f"{d}\n{p['text']}" for p, d in zip(posts, days))
        summary = self.llm.focus_recap(text, period)
        out = f":checkered_flag: *Focus-Recap* {period} ({len(posts)} Posts)\n\n{summary}"
        self.say(out, [{"type": "section", "text": {"type": "mrkdwn", "text": p}} for p in chunk(out)])

    def refresh_focus_canvas(self) -> None:
        """Den heutigen Focus in den Canvas des Violet-Chats schreiben (rechts als Seitenleiste öffnen)."""
        with self._canvas_lock:
            self._refresh_focus_canvas()

    def _refresh_focus_canvas(self) -> None:
        post = self.slack.today_post()
        link = self.slack.permalink(self.cfg.focus_channel, post["ts"], post["root_ts"]) if post else None
        md = F.render_markdown(F.parse_post(post["text"]) if post else None, self.slack.now(), link)
        if md == self.store.get("canvas_md"):
            return
        doc = {"type": "markdown", "markdown": md}
        canvas_id = self.store.get("canvas_id")
        if canvas_id:
            try:
                self._write_canvas(canvas_id, doc)
            except SlackApiError as exc:
                if exc.response.get("error") not in ("canvas_not_found", "file_not_found", "invalid_canvas"):
                    raise
                canvas_id = None
        if not canvas_id:
            try:
                canvas_id = self.bot.conversations_canvases_create(
                    channel_id=self.dm, title=CANVAS_TITLE, document_content=doc)["canvas_id"]
            except SlackApiError as exc:
                if exc.response.get("error") != "channel_canvas_already_exists":
                    raise
                # der Bot-Token hat kein im:read – Canvas-ID über deinen Token holen
                canvas_id = self.user.conversations_info(channel=self.dm)["channel"]["properties"]["canvas"]["file_id"]
                self._write_canvas(canvas_id, doc)
        self.store.set("canvas_id", canvas_id)
        self.store.set("canvas_md", md)

    def _write_canvas(self, canvas_id: str, doc: dict) -> None:
        """Nur den Text unter dem Titel austauschen – Titel, Titelbild und Aussehen bleiben."""
        edit = lambda change: self.bot.canvases_edit(canvas_id=canvas_id, changes=[change])  # noqa: E731
        try:
            title, old = self.slack.canvas_blocks(canvas_id)
        except (SlackApiError, RuntimeError) as exc:
            log.warning("Canvas-Aufbau nicht lesbar (%s) – ersetze den ganzen Inhalt", exc)
            title, old = None, []
        if not title:
            edit({"operation": "replace", "document_content": doc})
            return
        edit({"operation": "insert_after", "section_id": title, "document_content": doc})
        for block in old:
            edit({"operation": "delete", "section_id": block})

    def _canvas_loop(self) -> None:
        # Auch Änderungen, die du direkt in Slack machst, landen so im Canvas.
        while True:
            try:
                self.refresh_focus_canvas()
            except Exception as exc:  # noqa: BLE001 – nur loggen, nicht alle 10 min per DM nerven
                log.warning("Focus-Canvas nicht aktualisiert: %s", exc)
            time.sleep(600)

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
            if draft["kind"] == "focus":
                try:
                    self.refresh_focus_canvas()
                except Exception as exc:  # noqa: BLE001 – Posten hat geklappt, Canvas ist Beiwerk
                    log.warning("Focus-Canvas nicht aktualisiert: %s", exc)

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
        sender = event.get("user")
        vip = sender in self.cfg.vip_users
        wanted_bot = vip or sender in self.cfg.forward_bots
        if not sender or sender == self.cfg.owner_user_id or (event.get("bot_id") and not wanted_bot):
            return
        if not vip and not self.is_work_time():
            log.info("Live-DM von %s außerhalb der Arbeitszeit – nicht gemeldet (kommt im Digest)", sender)
            return
        if self.store.get("speak", True):
            group = "einer Gruppen-DM" if event.get("channel_type") == "mpim" else None
            self.avatar.announce(self.slack.name(sender), plain(event.get("text") or "", self.slack.name), group)
        if not self.store.get("live", True):
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

    def wrike_forward(self, event: dict) -> None:
        """Wrike: neues Ticket (zugewiesen) und Kommentar (erwähnt) melden – „aktualisiert“ ignorieren."""
        item = WR.parse(event.get("text") or "")
        if not item:
            return
        if not self.store.get("live", True) or not self.is_work_time():
            log.info("Wrike-Meldung außerhalb der Arbeitszeit/Live aus – nicht gemeldet: %s", item["title"])
            return
        msg = WR.render(item)
        self.say(msg, [{"type": "section", "text": {"type": "mrkdwn", "text": msg}}])

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
    # Eskalation aus den Monitoring-Channels
    # ======================================================================
    def escalate(self, event: dict) -> None:
        if not self.store.get("escalate", True):
            return
        channel, ts = event["channel"], event["ts"]
        if done := M.closed(event):
            return self.close_escalation(channel, ts, done)
        for alert in M.alerts(event):
            if not self.dedup.first(channel, alert["title"]):
                continue
            title = f"<{alert['link']}|{alert['title']}>" if alert.get("link") else alert["title"]
            msg = (f":rotating_light: *Eskalation* aus <#{channel}> · "
                   f"<{self.slack.permalink(channel, ts)}|im Channel öffnen>\n{title}")
            dm_ts = self.say(msg)
            open_ = self._open_escalations()
            open_[dm_ts] = {"channel": channel, "key": M.key(alert["title"]),
                            "title": alert["title"], "time": time.time()}
            self.store.set("escalations", open_)
            log.info("Eskaliert: %s (%s)", alert["title"], alert["pattern"])

    def _open_escalations(self) -> dict:
        """{dm_ts: {...}} – offene Eskalationen; ältere als 7 Tage fallen raus."""
        cutoff = time.time() - 7 * 24 * 3600
        return {k: v for k, v in (self.store.get("escalations") or {}).items() if v["time"] > cutoff}

    def close_escalation(self, channel: str, ts: str, done: dict) -> None:
        """„closed“ mit demselben Titel: die Eskalation(en) im Violet-Chat überschreiben."""
        open_ = self._open_escalations()
        k = M.key(done["title"])
        hits = [dm_ts for dm_ts, e in open_.items() if e["channel"] == channel and e["key"] == k]
        when = self.slack.fmt_time(ts)
        by = f" von {done['by']}" if done["by"] else ""
        for dm_ts in hits:
            e = open_.pop(dm_ts)
            text = (f":white_check_mark: *Closed*{by} um {when} · <#{channel}> · "
                    f"<{self.slack.permalink(channel, ts)}|im Channel öffnen>\n~{e['title']}~")
            self.bot.chat_update(channel=self.dm, ts=dm_ts, text=text)
            log.info("Eskalation geschlossen: %s", e["title"])
        self.dedup.forget(channel, done["title"])
        self.store.set("escalations", open_)

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
        threading.Thread(target=self._canvas_loop, name="focus-canvas", daemon=True).start()
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
    log.info("Violet läuft. Vorlesen über Avatar: %s", "an" if violet.avatar.enabled else "nicht konfiguriert")
    violet.run()


if __name__ == "__main__":
    main()
