# Offene TODOs

Priorisiert: oben steht, was den Betrieb blockiert. Erledigtes abhaken oder löschen.

## P1 – vor dem ersten gedruckten Label

- [x] **Endgültige Adresse festlegen**: `https://crates.c-base.org`, als
      `PUBLIC_BASE_URL` in `.env` und `.env.example` eingetragen. Sie steht in
      jedem QR-Code und NFC-Tag und lässt sich danach nicht mehr ändern, ohne alle
      Labels neu zu drucken.
- [ ] **Testdruck auf dem Brother QL-700** (62 mm endlos): passende `PageSize`
      der CUPS-Warteschlange finden (`62X1` … `62X4`), Schnitt prüfen, QR-Code
      aus üblichem Abstand mit Android scannen.

## P1 – vor dem Betrieb

- [ ] **OIDC einrichten**: Issuer-URL, Client-ID und Client-Secret besorgen,
      Redirect-URI `<Adresse>/accounts/oidc/callback/` beim Provider eintragen,
      Anmeldung gegen den echten Provider testen (bisher nur simuliert).
- [ ] **Container zum ersten Mal bauen und starten** (`docker compose up -d
      --build` bzw. `podman-compose`): Dockerfile und Compose-Dateien sind
      geschrieben, aber noch nie gebaut worden – auf dem Entwicklungsrechner
      gibt es weder Docker noch Podman. Auch die Postgres-Variante ist ungetestet.
- [ ] **Zielrechner und Reverse Proxy**: wo läuft der Container, wer macht HTTPS
      für `crates.c-base.org`? Proxy auf `127.0.0.1:8000`, `Host` und
      `X-Forwarded-Proto` durchreichen.
- [ ] **`.env` auf dem Zielrechner**: neues `DJANGO_SECRET_KEY`,
      `DJANGO_ALLOWED_HOSTS=crates.c-base.org`, OIDC-Daten.
- [ ] **Datensicherung** einrichten: Volume `data` (SQLite-Datei und Fotos),
      bei Postgres zusätzlich die Datenbank.
- [ ] **Upload-Grenze am Reverse Proxy** anheben (nginx: `client_max_body_size`,
      Standard 1 MB) – Handyfotos haben 3–12 MB, die App nimmt bis 30 MB je Bild.
- [ ] **Auf echtem Android-Gerät testen** (Chrome): Scan → Login → Crate,
      Formulare, aufklappbare Navigation, Foto aufnehmen und hochladen
      (öffnet „Foto aufnehmen“ wirklich die Kamera?). Bisher nur per Screenshot in
      Handybreite geprüft; das Aufklappen des Menüs ist ungetestet.

## P2 – fachliche Entscheidungen

- [ ] **Rechte**: Darf jeder angemeldete Member jede Crate bearbeiten und
      löschen (aktuell ja) oder nur Verantwortliche / Admins?
- [ ] **Zugang einschränken**: Aktuell wird jeder Member, den der Provider
      durchlässt. Zugang und Admin-Rechte an eine OIDC-Gruppe koppeln?
- [ ] **Lesen ohne Login**: Soll eine gescannte Crate ohne Anmeldung sichtbar
      sein?
- [ ] **Verantwortliche vor dem ersten Login**: Member existieren erst nach
      ihrer ersten Anmeldung. Vorab anlegen oder aus dem Provider synchronisieren?
- [ ] **Nummernvergabe**: Die höchste Nummer wird nach dem Löschen neu vergeben
      (altes Label zeigt dann auf die neue Crate). Festen Zähler einbauen?
- [ ] **`0000` /dev/null**: Löschschutz? Sollen entfernte Inhaltspositionen
      dorthin verschoben statt gelöscht werden?
- [ ] **Theme veröffentlichen**: Die Bootstrap-5-Fassung von c-base-bootstrap
      liegt nur lokal (`~/projects/c-base-bootstrap`, Branch `bootstrap5`). Mit
      c-base abstimmen, pushen bzw. Pull Request stellen und die Kopie unter
      `static/c-base-bootstrap/` danach durch ein Git-Submodul ersetzen.
- [ ] **Logo** stammt von c-beam (`crates/static/crates/logo.png`) – klären,
      ob es hier im Repository liegen darf.

## P3 – Aufräumen

- [ ] Nicht gewählte Label-Schriften aus `crates/fonts/` und `FONTS` entfernen
      (Anybody; Standard ist Bai Jamjuree mit Orbitron-Nummer); `XScale.ttf` ist
      bereits unbenutzt.
- [ ] `LABEL_WIDTH_PX` für andere Rollenbreiten testen (29 mm).
- [ ] Oberfläche nur deutsch – Englisch / Übersetzungen bei Bedarf.

## Später – Feature-Ideen

- [ ] NFC-Tags direkt aus der App beschreiben (Web NFC, Chrome auf Android,
      benötigt HTTPS) statt über eine externe App.
- [ ] Labels direkt vom Server auf dem QL-700 drucken, sobald feststeht, an
      welchem Gerät der Drucker hängt.
- [ ] Mehrere Labels in einem Rutsch drucken.
- [ ] Lagerorte pflegen, sobald es beschriftete Lagerflächen gibt (Feld ist
      schon vorhanden).
- [ ] Verlauf: wer hat wann was geändert oder bewegt.
- [ ] Fotos von Crate und Inhalt.
