"""Alle Claude-Aufrufe von Violet."""

from __future__ import annotations

import json
import re
from pathlib import Path

import anthropic

from .focus import POST_SCHEMA

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _load_unslop() -> str:
    """Regeln aus dem Unslop-Skill (Kopie von ~/.claude/skills/unslop/SKILL.md), ohne Frontmatter."""
    text = Path(__file__).with_name("unslop.md").read_text(encoding="utf-8")
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.DOTALL).strip()


UNSLOP = _load_unslop()
# Für Violets eigene Texte – ihre festen Formate gehen vor
STYLE = ("\n\nSchreibstil: Wende auf deinen Text die folgenden Unslop-Regeln an. Die festen Formatvorgaben "
         "oben (Emojis, :information_source:-Zeilen, Trennlinie, Grußformel, Slack-Links, Abschnittsüberschriften) "
         "gehen vor und bleiben genau so.\n\n" + UNSLOP)


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
Jeder Punkt hat einen Status: done (erledigt), wip (in Arbeit), waiting (wartet/blockiert),
cancelled (abgesagt/abgebrochen/hat sich erledigt, angezeigt als :x:), open (noch nicht begonnen).

Regeln:
- Übernimm Formulierungen der Punkte wörtlich; korrigiere nur offensichtliche Tippfehler.
- Erfinde keine Punkte. Ändere nur, was Daniel sagt.
- Ordne Aussagen unscharf zu: "erledigt mailtastic" meint den Punkt, der Mailtastic enthält.
- "erledigt"/"done"/"fertig" → done; "arbeite an"/"läuft"/"dran" → wip; "warte"/"warte auf"/"wartet"/"blockiert"/"pending" → waiting.
  Beispiel: "warte VMWare" → der Punkt mit VMWare bekommt waiting (wird als :hourglass_flowing_sand: angezeigt).
- "abgesagt"/"abgebrochen"/"hat sich erledigt"/"erledigt sich"/"fällt aus"/"entfällt"/"storniert"/"cancelled"
  → cancelled (:x:). Achtung: "hat sich erledigt" ist NICHT done, sondern cancelled.
  Beispiel: "Bogy abgesagt" → der Punkt mit Bogy bekommt cancelled.
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
- focus = Daniels neue Ziele für heute, danach alle recap-Punkte, die nicht done oder cancelled sind
  (mit ihrem Status). "Daily SysAdmin Requests" steht im recap immer als done und im focus immer
  als wip, jeweils als letzter Punkt.
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

    def focus_recap(self, posts: str, period: str) -> str:
        system = FOCUS_RULES + f"""
Aufgabe: Fasse Daniels Focus-Posts aus dem Zeitraum {period} für ihn zusammen (Deutsch, du-Form).
Slack-mrkdwn: *fett* für Überschriften, • für Punkte, keine #-Überschriften, keine Tabellen.
Keine eigene Titelzeile – beginne direkt mit dem ersten Abschnitt.
Gliederung:
*:white_check_mark: Erledigt* – nach Themen gruppiert, mit ungefährem Zeitpunkt (z. B. „KW 41“ oder Datum).
*:construction: Läuft noch* – Punkte, deren letzter Status wip oder open ist; nenne, seit wann sie mitlaufen.
*:hourglass_flowing_sand: Wartet* – Punkte mit letztem Status waiting.
*:x: Abgesagt* – Punkte mit letztem Status cancelled (abgesagt/hat sich erledigt).
*:zap: Ungeplantes* – was unter Other Topics dazukam; Häufungen benennen (z. B. „3× Drucker“).
*:mag: Auffällig* – 1–3 kurze Beobachtungen: Dauerbrenner, die seit vielen Tagen mitgezogen werden,
  Wochen mit viel Ungeplantem, Dinge ohne Fortschritt. Weglassen, wenn nichts auffällt.
Regeln: Punkte desselben Themas über die Tage zusammenführen; ein Punkt kann auf mehreren Tagen
stehen – maßgeblich ist der letzte Stand. Wiederkehrendes wie „Daily SysAdmin Requests“ nur einmal kurz.
Nichts erfinden; Formulierungen der Punkte möglichst beibehalten. Abschnitte ohne Inhalt weglassen.
"""
        return self._create(system + STYLE, posts, effort="medium")

    def unslop(self, text: str) -> str:
        system = UNSLOP + """

Gib nur den überarbeiteten Text aus, ohne Kommentar, ohne Einleitung. Slack-Formatierung bleibt
unverändert: *fett*, _kursiv_, Links <url|Text>, :emoji:-Codes, Erwähnungen <@U…>, <!channel>, Aufzählungen."""
        return self._create(system, text, effort="medium")

    # --- Erinnerungen -----------------------------------------------------
    REMINDER_SCHEMA = {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean", "description": "false, wenn Zeitpunkt oder Inhalt unklar ist"},
            "due": {"type": "string", "description": "Zeitpunkt als YYYY-MM-DD HH:MM (lokale Zeit), sonst leer"},
            "text": {"type": "string", "description": "Woran erinnert werden soll, kurz, ohne Zeitangabe"},
            "question": {"type": "string", "description": "Rückfrage, wenn ok=false, sonst leer"},
        },
        "required": ["ok", "due", "text", "question"],
        "additionalProperties": False,
    }

    def parse_reminder(self, message: str, now: str) -> dict:
        system = f"""\
Daniel bittet seine Assistentin, ihn an etwas zu erinnern. Jetzt ist {now} (Europe/Berlin).
Bestimme den Zeitpunkt und den Inhalt.
- "in 20 Minuten", "in 2 Stunden", "in einer halben Stunde" → relativ zu jetzt.
- "um 15 Uhr"/"15:30" ohne Datum → heute; ist die Zeit heute schon vorbei → morgen.
- "morgen", "übermorgen", "Freitag", "nächste Woche Montag", "am 3.11." ohne Uhrzeit → 09:00.
- "heute Nachmittag" → 14:00, "heute Abend" → 18:00, "mittags" → 12:00, "früh"/"morgens" → 08:00.
- Wochentag ohne "nächste" = der nächste kommende (heute nur, wenn die Uhrzeit noch nicht vorbei ist).
- text: nur der Inhalt („Rückruf bei Volker“), Sprache und Wortlaut von Daniel, ohne „erinnere mich an“.
- Fehlt der Inhalt oder ist der Zeitpunkt nicht bestimmbar, ok=false und eine kurze Rückfrage."""
        return self._json(system, message, self.REMINDER_SCHEMA)

    # --- Mittagsbestellung -------------------------------------------------
    LUNCH_SCHEMA = {
        "type": "object",
        "properties": {
            "dishes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "dish": {"type": "string", "description": "Gericht, einheitlich benannt"},
                        "orders": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "person": {"type": "string"},
                                    "count": {"type": "integer"},
                                    "note": {"type": "string", "description": "Sonderwunsch, sonst leer"},
                                },
                                "required": ["person", "count", "note"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["dish", "orders"],
                    "additionalProperties": False,
                },
            },
            "unclear": {"type": "array", "items": {"type": "string"},
                        "description": "Nachrichten, die keiner Bestellung sicher zuzuordnen sind (mit Name)"},
        },
        "required": ["dishes", "unclear"],
        "additionalProperties": False,
    }

    def lunch_orders(self, thread: str) -> dict:
        system = """\
Du wertest einen Slack-Thread aus, in dem Kollegen ihr Mittagessen bestellen.
Gib jedes bestellte Gericht mit allen Bestellungen (Person, Anzahl, Sonderwunsch) zurück.
Regeln:
- Gleiche Gerichte zusammenfassen, auch bei unterschiedlicher Schreibweise ("Margherita", "Pizza Margh.").
  Unterschiedliche Größen/Varianten bleiben getrennt. Nimm den Namen, wie er auf einer Karte stehen würde.
- "Bowl of the Month" (auch "Bowl des Monats", "Monatsbowl", "BotM") ist IMMER ein eigenes Gericht
  namens "Bowl of the Month" – nie mit anderen Bowls zusammenfassen, auch wenn Zutaten genannt werden.
- "Ich auch", "+1", "dasselbe wie X", ein Daumen-Hoch-Text o. Ä. → gleiche Bestellung wie der Bezug.
- Spätere Änderungen/Abbestellungen derselben Person ersetzen die frühere Bestellung.
- Wer mehrere Gerichte bestellt, taucht bei jedem Gericht auf. "2x"/"zwei" → count 2.
- Sonderwünsche (ohne Zwiebeln, extra scharf, Getränk dazu …) in note; Getränke/Beilagen, die extra
  bestellt werden, als eigenes Gericht.
- Die Startnachricht (Wer bestellt mit? Karte …) und reine Organisation (Zahlung, Abholung) sind keine Bestellung.
- Nichts erfinden. Was du nicht sicher zuordnen kannst, kommt mit Name in unclear.
- Personennamen so, wie sie im Thread stehen (Vor- und Nachname, wenn vorhanden)."""
        return self._json(system, thread, self.LUNCH_SCHEMA, effort="medium")

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
        return self._create(system + STYLE, f"Titel: {title}\n\nText:\n{body}", effort="medium")

    def edit_text(self, text: str, instruction: str) -> str:
        system = (
            "Überarbeite den Slack-Post gemäß der Anweisung. Behalte Format, Sprache(n), "
            "Emojis und <!channel> bei, sofern die Anweisung nichts anderes sagt. "
            "Gib nur den fertigen Post aus."
        )
        return self._create(system + STYLE, f"Post:\n{text}\n\nAnweisung:\n{instruction}")

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
        return self._json(system + STYLE, conversations, self.DIGEST_SCHEMA, effort="medium")
