---
name: dev-server
description: Lokalen Django-Entwicklungsserver von c-logistics prüfen, starten, neu starten und Änderungen im Browser verifizieren. Verwenden bei "läuft der Dev-Server", "starte den runserver", "restarte", "Migrations ausführen", oder wenn eine Änderung an Templates, CSS, Views oder Druckansichten sichtbar geprüft werden soll.
---

# Dev-Server c-logistics

## Läuft er?

```sh
pgrep -af 'manage.p[y] runserver'; ss -ltnp 2>/dev/null | grep ':8000'
```

Zwei `runserver`-Prozesse sind normal: der ältere ist Djangos Autoreloader, der jüngere sein Kindprozess, der den Port hält (`pgrep -P <pid>` zeigt die Beziehung). Unterschiedliche Startzeiten bedeuten nur, dass der Reloader neu geladen hat.

Es kann ein Server aus einer früheren Session oder aus dem Terminal des Nutzers laufen. Einen zweiten auf Port 8000 nicht starten; den vorhandenen verwenden oder, wenn ein Neustart verlangt ist, erst beenden.

## Starten

```sh
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver        # im Hintergrund starten
```

- Immer `.venv/bin/python`, nie das System-Python.
- Fehlt `.venv`: `python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt`. Fehlt `.env`: `cp .env.example .env` und den Nutzer auf die Einstellungen hinweisen.
- Nach einem Merge oder Branch-Wechsel vor dem Start `migrate` ausführen; `showmigrations | grep '\[ \]'` zeigt, ob etwas offen ist.
- Mit `run_in_background` starten und danach warten, bis `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/` eine Antwort liefert.

## Neu starten

```sh
pkill -f 'manage.py runserver'
```

Warten, bis `pgrep` nichts mehr findet, dann wie oben starten. Der Autoreloader lädt Python-Änderungen selbst neu; ein Neustart ist nötig nach Änderungen an `.env`, an installierten Paketen oder wenn der Server hängt.

## Änderungen prüfen

- Tests: `.venv/bin/python manage.py test 2>&1 | grep -E '^(Ran|OK|FAILED|FAIL|ERROR)'`.
- Sichtprüfung ohne den Nutzer: `chromium --headless --disable-gpu --hide-scrollbars --window-size=1300,1000 --virtual-time-budget=8000 --screenshot=<scratchpad>/x.png '<url>'`, das Bild dann mit dem Read-Tool ansehen.
- Druckansichten (`/cards/?c=…&copies=…&format=a6`): mit `--print-to-pdf=<scratchpad>/x.pdf --no-pdf-header-footer` rendern und die Seitenzahl und Kartenanzahl prüfen, nicht nur den Bildschirm-Screenshot.
- Seiten hinter dem Login brauchen eine Session; dafür eine temporäre Session in der lokalen Datenbank anlegen und danach wieder löschen. Hilfsskripte gehören ins Scratchpad.
- Meldet der Nutzer nach einer CSS- oder JS-Änderung den alten Stand, zuerst Shift-Reload vorschlagen: der Browser hält statische Dateien im Cache.

## Benutzer und Daten

- Admin anlegen: `.venv/bin/python manage.py createsuperuser` ist interaktiv; in der Agent-Shell stattdessen über `manage.py shell -c` mit einem Passwort, das dem Nutzer genannt wird.
- `db.sqlite3`, `media/` und `.env` sind lokal und nicht im Repository. Nicht löschen oder zurücksetzen, ohne zu fragen.
- Die KI-Bildbeschreibung gibt es nur auf dem Branch `feature/ai_support`, nicht auf `main`. Sie ruft die interne KI auf; nicht von sich aus auslösen.

## Git

Committen und pushen nur auf Aufforderung ("commit und push"). Feature-Arbeit auf einem `feature/…`-Branch, wenn der Nutzer einen nennt.
