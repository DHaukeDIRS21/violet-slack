"""Alle Claude-Aufrufe von Violet."""

from __future__ import annotations

import json

import anthropic

from .focus import POST_SCHEMA

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    pass


FOCUS_RULES = """\
Du pflegst Daniels "Focus of the day"-Post für den Slack-Channel #improver-squad.
Daniel ist SysAdmin bei DIRS21. Der Post hat die Abschnitte:
- info: Arbeitsort/Abwesenheit, z. B. "MyCorner :office:", "HO :house_with_garden:", "OoO".
- recap: Rückblick auf den letzten Arbeitstag.
- focus: Ziele für heute.
- other: ungeplante Themen ("Other Topics (unplanned)").
- sos: Hilferufe ans Team (optional, sonst leer).
- information: Infos ans Team (optional, sonst leer).
Jeder Punkt hat einen Status: done (erledigt), wip (in Arbeit), waiting (wartet/blockiert), open (noch nicht begonnen).

Regeln:
- Übernimm Formulierungen der Punkte wörtlich; korrigiere nur offensichtliche Tippfehler.
- Erfinde keine Punkte. Ändere nur, was Daniel sagt.
- Ordne Aussagen unscharf zu: "erledigt mailtastic" meint den Punkt, der Mailtastic enthält.
- "erledigt"/"done"/"fertig" → done; "arbeite an"/"läuft"/"dran" → wip; "wartet"/"blockiert"/"pending" → waiting.
- Neue ungeplante Themen ohne Statusangabe bekommen wip.
- Daniel schreibt Punkte meist auf Englisch, manchmal Deutsch – Sprache des Punkts beibehalten.
"""


class Claude:
    def __init__(self, model: str):
        self.client = anthropic.Anthropic()
        self.model = model

    def _create(self, system: str, user: str, *, schema: dict | None = None,
                effort: str = "low", max_tokens: int = 16000) -> str:
        output_config: dict = {"effort": effort}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config=output_config,
            )
        except anthropic.AuthenticationError as exc:
            raise LLMError("Claude-API-Key ungültig oder deaktiviert (401).") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Claude-API: Rate-Limit erreicht, bitte gleich nochmal.") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Claude-API-Fehler {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Claude-API nicht erreichbar.") from exc

        if response.stop_reason == "refusal":
            raise LLMError("Claude hat die Anfrage abgelehnt.")
        if response.stop_reason == "max_tokens":
            raise LLMError("Antwort zu lang – bitte kürzer formulieren.")
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if not text:
            raise LLMError("Leere Antwort von Claude.")
        return text

    def _json(self, system: str, user: str, schema: dict, **kw) -> dict:
        return json.loads(self._create(system, user, schema=schema, **kw))

    # --- Focus ------------------------------------------------------------
    def new_focus_post(self, previous: dict | None, answer: str, today: str) -> dict:
        system = FOCUS_RULES + """
Aufgabe: Erstelle den Post für HEUTE aus dem letzten Post und Daniels Antwort.
- recap = die focus-Punkte des letzten Posts, mit den Status, die Daniel nennt.
  Ohne Angabe bleibt der Status, wie er war. Ungeplante Themen vom letzten Post nicht in recap.
- focus = Daniels neue Ziele für heute, danach alle recap-Punkte, die nicht done sind
  (mit ihrem Status). Wiederkehrendes wie "Daily SysAdmin Requests" bleibt mit wip drin.
  Neue Ziele haben Status open.
- other = nur ungeplante Themen, die Daniel heute nennt.
- info: übernimm aus der Antwort; ohne Angabe aus dem letzten Post.
"""
        user = (
            f"Heute ist {today}.\n\n"
            f"Letzter Post (JSON):\n{json.dumps(previous or {}, ensure_ascii=False, indent=1)}\n\n"
            f"Daniels Antwort:\n{answer}"
        )
        return self._json(system, user, POST_SCHEMA, effort="medium")

    def edit_focus_post(self, post: dict, instruction: str) -> dict:
        system = FOCUS_RULES + """
Aufgabe: Wende Daniels Anweisung auf den bestehenden Post an und gib den vollständigen Post zurück.
Alles, was die Anweisung nicht betrifft, bleibt exakt gleich (Text, Reihenfolge, Status).
"unplanned …" fügt Punkte unter other hinzu. Mehrere Themen können durch Komma oder Zeilen getrennt sein.
"""
        user = (
            f"Aktueller Post (JSON):\n{json.dumps(post, ensure_ascii=False, indent=1)}\n\n"
            f"Anweisung:\n{instruction}"
        )
        return self._json(system, user, POST_SCHEMA)

    # --- #allgemein -------------------------------------------------------
    def bilingual_announcement(self, title: str, body: str, signature: str) -> str:
        system = f"""\
Du schreibst Ankündigungen für den Slack-Channel #allgemein bei DIRS21 im Namen von {signature} (SysAdmin).
Erst Deutsch, dann Englisch, getrennt durch eine Zeile "-----------------------".
Ton: freundlich, klar, kurz, du-Form im Deutschen. Inhalt nicht erfinden, nur sauber formulieren.
Exakt dieses Format (Slack-mrkdwn, keine Überschriften mit #):

<!channel> :information_source: <Titel DE> :information_source:
Hallo zusammen,
<Text DE>

Viele Grüße
{signature}
-----------------------
:information_source: <Title EN> :information_source:
Hi everyone,
<Text EN>

Best regards,
{signature}

Gib nur den fertigen Post aus, ohne Kommentar.
"""
        return self._create(system, f"Titel: {title}\n\nText:\n{body}", effort="medium")

    def edit_text(self, text: str, instruction: str) -> str:
        system = (
            "Überarbeite den Slack-Post gemäß der Anweisung. Behalte Format, Sprache(n), "
            "Emojis und <!channel> bei, sofern die Anweisung nichts anderes sagt. "
            "Gib nur den fertigen Post aus."
        )
        return self._create(system, f"Post:\n{text}\n\nAnweisung:\n{instruction}")

    # --- DM-Digest --------------------------------------------------------
    DIGEST_SCHEMA = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "conversation": {"type": "string", "description": "conversation id aus der Eingabe"},
                        "category": {"type": "string", "enum": ["needs_reply", "fyi", "answered"]},
                        "summary": {"type": "string"},
                        "message_ts": {"type": "string", "description": "ts der wichtigsten Nachricht"},
                    },
                    "required": ["conversation", "category", "summary", "message_ts"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }

    def digest(self, owner_name: str, conversations: str) -> dict:
        system = f"""\
Du fasst die Slack-Direktnachrichten von {owner_name} (SysAdmin bei DIRS21) zusammen.
Pro Konversation genau ein Eintrag, ein bis zwei Sätze auf Deutsch, in der 3. Person über die
anderen ("Linda bedankt sich …") und mit "du" für {owner_name}.
Kategorien:
- needs_reply: Die letzte relevante Nachricht kommt von jemand anderem und erwartet eine
  Antwort oder Aktion von {owner_name}.
- answered: {owner_name} hat zuletzt geantwortet bzw. gehandelt; nenne offene Punkte trotzdem.
- fyi: Infos, Danke, Bestätigungen, automatische Benachrichtigungen.
Persönliche/private Themen nur andeuten ("persönliches Thema – bitte direkt lesen").
Keine Passwörter oder Zugangsdaten wiedergeben.
"""
        return self._json(system, conversations, self.DIGEST_SCHEMA, effort="medium")
