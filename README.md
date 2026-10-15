# Violet – Slack-Assistentin (Neuaufbau)

Violet ist ein persönlicher Slack-Bot für Daniel. Bedient wird er per DM an Violet.
Dieser Code ist aus dem Verhalten der alten App in Slack nachgebaut (DM-Verlauf 14./15.10.2026),
weil der ursprüngliche Code verloren gegangen ist.

| Befehl | Wirkung |
|---|---|
| `focus` | Zeigt deinen letzten Focus-Post + 5 Fragen. Aus deiner Antwort baut Claude den neuen Post (Recap = gestriger Focus, offene Punkte wandern weiter). Gepostet wird als Antwort im heutigen „Focus of the day“-Thread in #improver-squad; gibt es noch keinen, legt Violet ihn an. |
| `status Mailtastic erledigt, arbeite an Prakti Laptop` | Aktualisiert deinen heutigen Post. Funktioniert auch ohne `status`, z. B. `erledigt fix broken laptop`. |
| `unplanned Drucker 2. OG, Teams-Ausfall erledigt` | Ergänzt *Other Topics (unplanned)*; ohne Status → :construction: |
| `@channel :information_source: Titel` + Text | Zweisprachiger Post (DE/EN) in #allgemein im Stil deiner bisherigen Ankündigungen |
| `allgemein: Text` | Post in #allgemein, unverändert |
| `digest` / `digest 48` | DM-Zusammenfassung seit dem letzten Digest (sonst 24 h) bzw. der letzten 48 h: :red_circle: Braucht Antwort / :large_yellow_circle: FYI / :white_check_mark: Bereits beantwortet |
| `live an` / `live aus` | Neue DMs an dich sofort bei Violet anzeigen, mit Button „➡️ An #dirs21_sysadmin“ |
| `abbrechen` | Laufenden Vorgang beenden |
| `hilfe` | Befehlsübersicht |

Jeder Post kommt erst als Vorschau mit **✅ Posten / ✏️ Ändern / ✖️ Abbrechen**. Violet postet nie ohne deinen Klick.
Posts erscheinen unter deinem Namen (User-Token), Violet selbst schreibt nur in eure DM.

## Einrichtung

1. **Slack-App anlegen**: <https://api.slack.com/apps> → *Create New App* → *From a manifest* → Inhalt von
   [`manifest.yaml`](manifest.yaml) einfügen. (Existiert die alte App „Violet“ noch, dort unter
   *App Manifest* den Inhalt ersetzen – dann bleibt die DM erhalten.)
2. *Install to Workspace* – dabei autorisierst du auch die User-Scopes.
3. Tokens holen:
   - *OAuth & Permissions* → **Bot User OAuth Token** (`xoxb-…`) und **User OAuth Token** (`xoxp-…`)
   - *Basic Information* → *App-Level Tokens* → Token mit Scope `connections:write` (`xapp-…`)
4. Claude-API-Key unter <https://platform.claude.com> anlegen (der alte Key war zwischendurch deaktiviert – 401-Fehler am 14.10.).
5. `.env.example` nach `.env` kopieren und ausfüllen.

## Installation auf dem Windows-Laptop (Autostart)

1. Den Ordner `violet` (bzw. `violet-windows.zip` entpacken) irgendwo ablegen.
2. `install\install.cmd` doppelklicken. Das Skript
   - installiert bei Bedarf Python 3.13 (per winget, ohne Admin),
   - kopiert Violet nach `%LOCALAPPDATA%\Violet` und installiert die Pakete,
   - **öffnet die `.env` im Editor** – Keys eintragen, speichern, im Fenster Enter drücken,
   - legt die Aufgabe „Violet“ in der Aufgabenplanung an (Start 30 s nach deiner Anmeldung,
     Neustart bei Absturz; falls die Aufgabenplanung gesperrt ist: Verknüpfung im Autostart-Ordner),
   - startet Violet sofort.
3. In Slack Violet `hilfe` schreiben.

Log: `%LOCALAPPDATA%\Violet\data\violet.log`. Update = `install.cmd` erneut ausführen
(.env und Daten bleiben). Entfernen: `install\uninstall.cmd`.
Falls Sophos `pythonw.exe` blockiert, eine Ausnahme für `%LOCALAPPDATA%\Violet\.venv\Scripts\pythonw.exe` anlegen.

## Starten (manuell / Server)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
set -a; . ./.env; set +a
python -m violet
```

Dauerbetrieb: `violet.service` (systemd) oder Docker:

```bash
docker build -t violet .
docker run -d --restart always --env-file .env -v violet-data:/data --name violet violet
```

Socket Mode braucht keine öffentliche URL – ein Server/VM im Firmennetz reicht.

## Daten & Backup

Violet speichert nur Kleinkram in `data/violet.sqlite3` (Gesprächszustand, offene Entwürfe,
Zeitpunkt des letzten Digests, Live an/aus). Alles Wichtige liest Violet direkt aus Slack:
Geht die Datei verloren, findet Violet den heutigen Focus-Post wieder und der nächste Digest
deckt einfach 24 h ab. **Der Code liegt jetzt in Git** – damit ist der eigentliche Verlust von
diesmal nicht mehr möglich. Tokens nie committen (`.env` steht in `.gitignore`).

## Entwicklung

```bash
pip install pytest
python -m pytest -q
```

| Datei | Inhalt |
|---|---|
| `violet/app.py` | Befehls-Routing, Vorschau/Buttons, Posten, Digest, Live-DMs |
| `violet/focus.py` | Focus-Post parsen/rendern (Status-Emojis :white_check_mark: :construction: :hourglass_flowing_sand:) |
| `violet/llm.py` | Claude-Aufrufe (Focus bauen/ändern, zweisprachige Posts, Digest) |
| `violet/slackops.py` | Slack-Lesezugriffe: Focus-Thread finden, DMs sammeln |
| `violet/store.py` | SQLite-Zustand |
