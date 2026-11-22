# c-logistics

Django-App zum Verwalten von c-base cargo crates mit NFC-Tags und gedruckten Labels.

## Konzept

- Die c-base cargo crates werden fortlaufend nummeriert; die ID ist die Nummer
  als vierstellige Hexzahl (`0001`, `0002`, … `000A` … `FFFF`).
- `0000` ist `/dev/null`, die Mülltonne. Sie wird bei der Einrichtung angelegt;
  neue Crates beginnen bei `0001`.
- NFC-Tag und QR-Code auf dem gedruckten Label zeigen beide auf dieselbe URL:
  `https://crates.c-base.org/<ID>` – die Crate-ID ist der letzte Teil der URL.
  Die frühere Form `/c/<ID>/` leitet dorthin um.
- Weil die ID direkt hinter dem Hostnamen steht, gehört jeder Pfad aus höchstens
  vier Hex-Zeichen einer Crate. Neue Seiten der App dürfen deshalb nicht z. B.
  `/add`, `/feed` oder `/cafe` heißen.
- Gescannt wird mit Android-Smartphones; die URL öffnet die Crate-Seite im Browser.
- Pro Crate gibt es Inhalt (Positionen mit Menge) und einen oder mehrere
  verantwortliche Member.
- Lagerorte sind optional, solange es noch keine beschrifteten Lagerflächen gibt.

## Labels

- Das Label ist so breit wie das 62-mm-Endlosband des Brother QL-700
  (Querformat) und je nach Schrift nur gut 17–27 mm lang.
- Links steht der QR-Code mit der Crate-URL und darunter das NFC-Logo
  (Schriftzug „NFC“ in X-Scale mit drei Funkwellen, wie auf den
  c-base-Karten). Rechts daneben drei Zeilen, die jeweils die volle Breite
  füllen: klein „c-base cargo“, groß „crate“, groß die ID. Alles andere ändert
  sich zu oft; ein Label soll nie neu gedruckt werden müssen.
- Das NFC-Logo lässt sich mit `LABEL_NFC_LOGO=0` abschalten, etwa für Labels
  ohne Tag; der QR-Code wird dann größer.
- Schrift: Der Schriftzug steht in Bai Jamjuree Bold, die ID in Orbitron
  Black, weil Orbitron die Null durchstreicht und sie so nicht mit einem O
  verwechselt wird. Über `LABEL_FONT` lässt sich alles auf `orbitron` oder
  `anybody` umstellen (Standard: `baijamjuree`); zum Vergleichen geht auch
  `?font=…` an der Label-URL. Alle drei Schriften liegen mit ihrer SIL Open
  Font License in `crates/fonts/`.
- Die App liefert das Label in Druckauflösung (300 dpi) als PNG unter
  `/<ID>/label.png` und als einseitiges PDF unter `/<ID>/label.pdf`. Von
  welchem Gerät gedruckt wird, ist bewusst offen.
- PDF drucken (erprobt am QL-570 mit dem freien `ptouch`-Treiber):
  `lp -d QL-570 -o PageSize=Custom.62x33mm -o nopdfAutoRotate crate-0001.pdf`
  - Die PDF-Seite ist 62 × 33 mm: das Label (26,5 mm) plus oben und unten gut
    3 mm Rand, die der Drucker nicht bedrucken kann. Die Länge in `PageSize`
    muss zur PDF-Seite passen, sonst wird das Label beschnitten.
  - Ohne `nopdfAutoRotate` und mit `PageSize=62mm` dreht CUPS die querformatige
    Seite und druckt das Label längs aufs Band, mit viel Leerraum. Dasselbe
    passiert beim Drucken aus dem Dialog von Firefox.
- Abschneiden: kein eigener Befehl nötig, das regelt der Druckertreiber. Beim
  `ptouch`-Treiber ist der Schnitt voreingestellt (`AutoCut`); im
  Brother-Treiber des QL-700 heißen die Optionen `BrCutLabel` (alle n
  Etiketten schneiden) und `BrCutAtEnd` (am Ende des Auftrags schneiden).
- Mehrere Labels auf einmal: in der Liste Crates anhaken, dann
  - **„Labels PDF“** – ein PDF mit einer Seite pro Label (`/labels/?c=…`).
    Im PDF steht kein Schneidbefehl; der Druckertreiber schneidet nach jeder
    Seite. Gedruckt wird es mit denselben `lp`-Optionen wie ein einzelnes Label.
  - **„Labels QL-700“** – eine Druckdatei in Brothers Rasterformat
    (`/labels/?c=…&format=ql`), die den Schneidbefehl nach jedem Label selbst
    enthält. Sie geht ohne Treiber roh an den Drucker:
    `lp -d Brother_QL-700 -o raw crates-0001-0003-ql700.bin` oder direkt
    `cat crates-0001-0003-ql700.bin > /dev/usb/lp0`. Nur für 62-mm- und
    29-mm-Endlosband. Dieselbe Datei für eine einzelne Crate gibt es auf
    ihrer Detailseite unter „Label als QL-Druckdatei“.
- `PUBLIC_BASE_URL` (Umgebungsvariable) legt die Adresse fest, die in QR-Code
  und NFC-Tag steht. Sie muss feststehen, bevor Labels gedruckt werden.
- `LABEL_WIDTH_PX` ist die Druckbreite der Rolle in Pixeln und damit die
  Breite des Labels (62 mm = 696, 29 mm = 306); der Inhalt skaliert mit.

## Exemplare

In der Regel braucht man jedes Label und jede Karte doppelt, eins für jede
Stirnseite der Crate. Deshalb kommt alles standardmäßig zweimal heraus:

- In der Liste steht neben den Druckknöpfen das Feld „je … ×“ (1 bis 10).
- Die Knöpfe auf der Crate-Seite nehmen die Voreinstellung; in der
  Kartenansicht lässt sie sich oben umschalten.
- An jeder Druckadresse geht `?copies=N`; die Voreinstellung steht in
  `PRINT_COPIES` (Standard 2).
- Exemplare derselben Crate stehen hintereinander: zwei Label-Seiten in Folge,
  bei A5 beide Karten auf einem Blatt.

## Karte zum Ausdrucken

Neben dem kleinen Label gibt es unter `/<ID>/card/` eine Karte mit allen
Angaben für den Farblaser: QR-Code und ID (das Label, groß), Bezeichnung,
Verantwortliche, Lagerort, Größe, Beschreibung, Inhalt und die bis zu vier
neuesten Fotos.

- Format: DIN A5 quer, zwei Karten pro A4-Blatt im Hochformat, oder mit
  `?format=a6` DIN A6 quer, vier Karten pro A4-Blatt im Querformat. Gedruckt
  wird über den Druckdialog des Browsers in 100 %, danach an den
  gestrichelten Linien schneiden.
- Mehrere Karten zusammen: in der Liste Crates anhaken und „Karten A5“ oder
  „Karten A6“ wählen (`/cards/?c=0001&c=0002&format=a6`). Die Karten füllen
  die Blätter der Reihe nach, damit kein Platz leer bleibt.
- Fotos werden nicht beschnitten; die Seite ordnet sie so an, dass sie
  möglichst groß werden.
- Passt der Text nicht auf die Karte, verkleinert die Seite die Schrift
  schrittweise.
- Anders als das Label veraltet die Karte, wenn sich der Inhalt ändert;
  deshalb steht unten das Druckdatum.

## Fotos vom Inhalt

Auf der Crate-Seite lassen sich Fotos vom Inhalt hochladen – gedacht für das
Smartphone, mit dem man ohnehin gerade den Tag gescannt hat.

- „Foto aufnehmen“ öffnet auf dem Telefon direkt die Rückkamera, „Bilder
  auswählen“ die Galerie (auch mehrere Bilder auf einmal). Hochgeladen wird,
  sobald das Bild gewählt ist.
- Der Server dreht das Bild aufrecht, verkleinert es auf höchstens 1600 px
  Kantenlänge und speichert es als JPEG, dazu eine Vorschau mit 400 px. Dabei
  fallen alle Metadaten weg, auch der Aufnahmeort; der Dateiname vom Telefon
  wird nicht übernommen.
- Die Dateien liegen unter `media/crates/<ID>/` (Ordner über
  `DJANGO_MEDIA_ROOT` einstellbar) und werden nur an angemeldete Member
  ausgeliefert – über die App, nicht direkt vom Webserver.
- Wird ein Foto oder die Crate gelöscht, verschwinden auch die Dateien.

## Anmeldung (OAuth2 / OpenID Connect)

Member melden sich über einen OIDC-Provider an (Authorization Code Flow,
Endpunkte per Discovery). Konfiguration über Umgebungsvariablen:

| Variable | Bedeutung |
| --- | --- |
| `OIDC_ISSUER_URL` | Issuer, unter dem `/.well-known/openid-configuration` liegt |
| `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | Zugangsdaten des Clients |
| `OIDC_SCOPE` | Standard: `openid profile email` |
| `OIDC_PROVIDER_NAME` | Name im Anmeldeknopf („mit … anmelden“), Standard: `c-base-account` |

Beim Provider als Redirect-URI eintragen: `<PUBLIC_BASE_URL>/accounts/oidc/callback/`

- Beim ersten Login wird der Member automatisch angelegt und danach über das
  `sub`-Claim wiedererkannt; Name und E-Mail werden bei jedem Login aktualisiert.
- Ein Member kann erst als Verantwortlicher gewählt werden, nachdem er sich
  einmal angemeldet hat.
- Die Login-Seite zeigt den Knopf für den Provider und darunter das Formular
  für lokale Konten; ohne `OIDC_ISSUER_URL` nur das Formular.
- Admin-Rechte werden nicht vom Provider übernommen, sondern im Admin vergeben.

## Optik

Die Oberfläche nutzt das c-base-Theme
[c-base-bootstrap](https://github.com/c-base/c-base-bootstrap) in der
Bootstrap-5-Fassung (Bootswatch Cyborg 5.3.8 plus `bootstrap.custom.css`).

- Die benötigten Theme-Dateien liegen als Kopie unter
  `static/c-base-bootstrap/` (CSS, Bootstrap-JS, Hintergrundbild). Stand:
  Branch [`bootstrap5`](https://github.com/c-base/c-base-bootstrap/tree/bootstrap5),
  Commit `89659d3`. `master` bleibt die Bootstrap-3-Fassung, die andere
  c-base-Anwendungen einbinden.
- `crates/static/crates/app.css` ergänzt nur, was c-logistics eigen ist:
  Eingabefelder im Stil von `.terminal`, das abgedunkelte Stationsbild als
  Hintergrund, die Inhaltstabelle und Anpassungen für Smartphones.
- Formulare bekommen ihr Bootstrap-Markup über `BootstrapFormMixin` und das
  Template `crates/templates/forms/bootstrap.html`.
- Das Logo unter `crates/static/crates/logo.png` stammt von c-beam.

## Als App auf dem Telefon

c-logistics lässt sich als Web-App installieren (in Chrome auf Android: Menü →
„App installieren“ bzw. „Zum Startbildschirm hinzufügen“). Sie läuft dann ohne
Adressleiste, und Links auf `crates.c-base.org` – also auch gescannte QR-Codes
und NFC-Tags – öffnen sich in der App.

- Das Manifest kommt von `/manifest.webmanifest`, die Icons liegen unter
  `crates/static/crates/icons/`.
- Die Icons zeigen vorerst das Stationslogo aus
  [c-beam-droid](https://github.com/c-base/c-beam-droid) (`ic_launcher.png`,
  WTFPL). Das gibt es dort nur in 96 px, das große Icon ist deshalb unscharf.
  Mit einer größeren Vorlage neu erzeugen:
  `.venv/bin/python manage.py make_icons pfad/zum/logo.png` – mindestens
  512 px, transparenter Hintergrund. Ohne Angabe entsteht ein Schriftzug „crate“.
- Die Installation setzt HTTPS voraus. Offline funktioniert die App nicht; sie
  braucht den Server und die Anmeldung.

## Entwicklung

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # Einstellungen, siehe unten
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

Tests: `.venv/bin/python manage.py test`

## Betrieb im Container

Die App läuft als ein Container (gunicorn, statische Dateien über whitenoise)
und spricht nur HTTP. HTTPS macht ein Reverse Proxy davor, der an
`127.0.0.1:27283` weiterleitet und `Host` sowie `X-Forwarded-Proto` durchreicht.
Die Befehle gelten genauso für `podman-compose`.

```sh
cp .env.example .env     # anpassen: DJANGO_SECRET_KEY, PUBLIC_BASE_URL, OIDC_…
docker compose up -d --build
docker compose exec app python manage.py createsuperuser
```

- **Datenbank:** Standard ist SQLite; die Datei liegt zusammen mit den Fotos
  im Volume `data` (`/data/db.sqlite3`, `/data/media/`). Für Postgres die
  zweite Datei dazunehmen und `POSTGRES_PASSWORD` in der `.env` setzen:
  `docker compose -f compose.yaml -f compose.postgres.yaml up -d --build`
- **Start:** Der Container bringt die Datenbank bei jedem Start selbst auf
  Stand (`migrate`).
- **Update:** `git pull`, dann `docker compose up -d --build`.
- **Sicherung:** das Volume `data` sichern (bei Postgres zusätzlich `pgdata`
  bzw. ein `pg_dump`). Für eine Kopie der SQLite-Datei im laufenden Betrieb:
  `docker compose exec app python -c "import sqlite3; sqlite3.connect('/data/db.sqlite3').backup(sqlite3.connect('/data/backup.sqlite3'))"`
- **Upload-Grenze:** Der Proxy muss Uploads bis 30 MB durchlassen (nginx:
  `client_max_body_size 30m;`), sonst scheitern Handyfotos.
- **Ohne Proxy ausprobieren:** `DJANGO_SECURE_COOKIES=0` und `localhost` in
  `DJANGO_ALLOWED_HOSTS`, dann geht die Anmeldung auch über
  `http://localhost:27283`.

## Einstellungen (.env)

Alle Einstellungen kommen aus Umgebungsvariablen. Für die lokale Arbeit stehen
sie in der Datei `.env` im Projektordner; `.env.example` ist die kommentierte
Vorlage. Die `.env` wird nicht committet, weil sie Geheimnisse enthält
(`DJANGO_SECRET_KEY`, `OIDC_CLIENT_SECRET`).

- Echte Umgebungsvariablen haben Vorrang vor der Datei.
- Nach Änderungen an der `.env` den Server neu starten.

## Offene Punkte

Priorisierte Checkliste samt späteren Feature-Ideen: [TODO.md](TODO.md)
