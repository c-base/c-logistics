# Offene TODOs

Priorisiert: oben steht, was den Betrieb blockiert. Erledigtes abhaken oder löschen.

## P1 – vor dem ersten gedruckten Label

- [x] **Endgültige Adresse festlegen**: `https://crates.c-base.org`, als
      `PUBLIC_BASE_URL` in `.env` und `.env.example` eingetragen. Sie steht in
      jedem QR-Code und NFC-Tag und lässt sich danach nicht mehr ändern, ohne alle
      Labels neu zu drucken.
- [x] **Druckdatei „Labels QL-700“ am Drucker testen**: Die Rasterdatei mit
      Schneidbefehl ging roh an den Drucker (`lp -o raw`); Druckbild und Schnitt
      passen.
- [x] **Testdruck als PDF** am QL-570 (62 mm endlos, `ptouch`-Treiber): passt mit
      `-o PageSize=Custom.62x33mm -o nopdfAutoRotate`, siehe README.
- [x] **QR-Code scannen**: gedrucktes Label mit Android gescannt, funktioniert.
- [ ] **Noch offen beim Drucken**: Sammel-PDF mit mehreren Labels (Schnitt nach
      jeder Seite?) und der QL-700 mit dem Brother-Treiber (`PageSize` dort
      `62X1` … `62X4`).

## P1 – vor dem Betrieb

- [x] **OIDC einrichten**: Die Anmeldung läuft auf dem Server gegen den echten
      Provider (c-base-account).
- [x] **Container zum ersten Mal bauen und starten**: Die App läuft auf dem
      Server im Container, mit SQLite.
- [ ] **Postgres-Variante** (`compose.postgres.yaml`) ist weiterhin ungetestet.
- [x] **Zielrechner und Reverse Proxy**: `https://crates.c-base.org` ist mit
      HTTPS erreichbar.
- [x] **`.env` auf dem Zielrechner**: `DJANGO_SECRET_KEY`,
      `DJANGO_ALLOWED_HOSTS`, OIDC-Daten.
- [ ] **Mailversand einrichten**: SMTP-Zugang in die `.env` auf dem Server
      (`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
      `DEFAULT_FROM_EMAIL` – der Absender `crates@c-base.org` ist nur geraten).
      Ohne `EMAIL_HOST` ist „Verantwortliche erinnern“ gesperrt. Danach einen
      Member in die Gruppe „Manager“ aufnehmen und eine Erinnerung testen.
- [ ] **Alte Doppelkonten zusammenführen**: auf dem Server
      `python manage.py merge_duplicate_members` ausführen, die angezeigten
      Paare (`<name>-2` → `<name>`) prüfen und mit `--apply` zusammenführen.
- [ ] **Datensicherung** einrichten: Volume `data` (SQLite-Datei und Fotos),
      bei Postgres zusätzlich die Datenbank.
- [ ] **Cron-Job fürs Aufräumen** auf dem Server einrichten: Crontab-Eintrag
      aus der README („Betrieb im Container“, Punkt „Aufräumen“) übernehmen,
      Pfad und Logdatei anpassen. Er entfernt monatlich Stände aus dem Verlauf,
      die älter als 180 Tage sind (ein Vorschlag), und danach die Fotodateien,
      die keine Crate und kein Stand mehr zeigt. Vorher einmal
      `docker compose exec app python manage.py purge_photo_files --dry-run`
      ansehen. Ohne den Job bleiben gelöschte Fotos für immer auf der Platte.
- [ ] **Upload-Grenze am Reverse Proxy** anheben (nginx: `client_max_body_size`,
      Standard 1 MB) – Handyfotos haben 3–12 MB, die App nimmt bis 30 MB je Bild.
- [x] **Auf echtem Android-Gerät testen**: Scan → Login → Crate, Formulare,
      aufklappbare Navigation, Foto aufnehmen und hochladen – funktioniert.

## P2 – fachliche Entscheidungen

- [ ] **Rechte**: Darf jeder angemeldete Member jede Crate bearbeiten und
      löschen (aktuell ja) oder nur Verantwortliche / Admins?
- [ ] **Zugang einschränken**: Aktuell wird jeder Member, den der Provider
      durchlässt. Zugang und Admin-Rechte an eine OIDC-Gruppe koppeln?
- [ ] **Lesen ohne Login**: Soll eine gescannte Crate ohne Anmeldung sichtbar
      sein?
- [x] **Verantwortliche vor dem ersten Login**: Manager merken im Suchfeld der
      Verantwortlichen einen Nick vor; bei der ersten Anmeldung übernimmt die
      Person das Konto. Ein Abgleich mit einem Member-Verzeichnis bleibt möglich.
- [ ] **Nummernvergabe**: Die höchste Nummer wird nach dem Löschen neu vergeben
      (altes Label zeigt dann auf die neue Crate). Festen Zähler einbauen?
- [ ] **`0000` /dev/null**: Löschschutz? Sollen entfernte Inhaltspositionen
      dorthin verschoben statt gelöscht werden?
- [ ] **Theme als Submodul?** Die Bootstrap-5-Fassung liegt jetzt bei c-base im
      Branch `bootstrap5` (nicht in `master`, das bleibt Bootstrap 3). Offen: die
      Kopie unter `static/c-base-bootstrap/` durch ein Git-Submodul ersetzen,
      und mit c-base klären, ob und wann `bootstrap5` der Hauptzweig wird.
- [ ] **App-Icons aus einer größeren Logo-Vorlage** erzeugen (`manage.py
      make_icons <logo>`); bisher das 96-px-Stationslogo aus c-beam-droid,
      hochskaliert und unscharf.
- [x] **App auf Android installieren**: installiert; ein gescannter QR-Code
      öffnet die App.
- [x] **Logo** stammt von c-beam (`crates/static/crates/logo.png`) – geklärt,
      es darf hier im Repository liegen.

## P3 – Aufräumen

- [ ] Nicht gewählte Label-Schriften aus `crates/fonts/` und `FONTS` entfernen
      (Anybody; Standard ist Bai Jamjuree mit Orbitron-Nummer).
- [x] **Lizenz von `XScale.ttf` klären**: geklärt; die Schrift für das
      NFC-Logo darf im öffentlichen Repository liegen.
- [ ] `LABEL_WIDTH_PX` für andere Rollenbreiten testen (29 mm).
- [ ] Oberfläche nur deutsch – Englisch / Übersetzungen bei Bedarf.

## Später – Feature-Ideen

- [ ] NFC-Tags direkt aus der App beschreiben (Web NFC, Chrome auf Android,
      benötigt HTTPS) statt über eine externe App.
- [ ] Labels direkt vom Server auf dem QL-700 drucken, sobald feststeht, an
      welchem Gerät der Drucker hängt.
- [x] Mehrere Labels in einem Rutsch drucken (in der Liste anhaken, dann
      „Labels als PDF“ oder „Labels als QL-Druckdatei“).
- [ ] Lagerorte pflegen, sobald es beschriftete Lagerflächen gibt (Feld ist
      schon vorhanden).
- [ ] Verlauf: wer hat wann was geändert oder bewegt.
- [x] Fotos von Crate und Inhalt.
