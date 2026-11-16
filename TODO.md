# Offene TODOs

Priorisiert: oben steht, was den Betrieb blockiert. Erledigtes abhaken oder löschen.

## P1 – vor dem ersten gedruckten Label

- [ ] **Endgültige Adresse festlegen** und als `PUBLIC_BASE_URL` setzen. Sie steht
      in jedem QR-Code und NFC-Tag und lässt sich danach nicht mehr ändern, ohne
      alle Labels neu zu drucken.
- [ ] **Testdruck auf dem Brother QL-700** (62 mm endlos): passende `PageSize`
      der CUPS-Warteschlange finden (`62X1` … `62X4`), Schnitt prüfen, QR-Code
      aus üblichem Abstand mit Android scannen.

## P1 – vor dem Betrieb

- [ ] **OIDC einrichten**: Issuer-URL, Client-ID und Client-Secret besorgen,
      Redirect-URI `<Adresse>/accounts/oidc/callback/` beim Provider eintragen,
      Anmeldung gegen den echten Provider testen (bisher nur simuliert).
- [ ] **Deployment**: Zielrechner festlegen, HTTPS, App-Server (z. B. gunicorn)
      hinter Reverse Proxy, statische Dateien ausliefern (`collectstatic`).
- [ ] **Produktions-Einstellungen**: `DJANGO_DEBUG=0`, eigenes
      `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, sichere Cookies / CSRF hinter
      dem Proxy (`manage.py check --deploy`).
- [ ] **Datensicherung** für `db.sqlite3` (oder Wechsel auf PostgreSQL).
- [ ] **Auf echtem Android-Gerät testen** (Chrome): Scan → Login → Crate,
      Formulare, Navigation. Bisher nur per Screenshot in Handybreite geprüft.

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
- [ ] **Hintergrundbild und Logo** stammen von c-beam
      (`crates/static/crates/`) – klären, ob sie hier im Repository liegen dürfen.

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
