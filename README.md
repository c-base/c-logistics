# c-logistics

Django-App zum Verwalten von c-base cargo crates mit NFC-Tags und gedruckten Labels.

## Konzept

- Die c-base cargo crates werden fortlaufend nummeriert; die ID ist die Nummer
  als vierstellige Hexzahl (`0001`, `0002`, … `000A` … `FFFF`).
- `0000` ist `/dev/null`, die Mülltonne. Sie wird bei der Einrichtung angelegt;
  neue Crates beginnen bei `0001`.
- NFC-Tag und QR-Code auf dem gedruckten Label zeigen beide auf dieselbe URL:
  `https://<host>/c/<ID>/` – die Crate-ID ist der letzte Teil der URL.
- Gescannt wird mit Android-Smartphones; die URL öffnet die Crate-Seite im Browser.
- Pro Crate gibt es Inhalt (Positionen mit Menge) und einen oder mehrere
  verantwortliche Member.
- Lagerorte sind optional, solange es noch keine beschrifteten Lagerflächen gibt.

## Labels

- Das Label ist so breit wie das 62-mm-Endlosband des Brother QL-700
  (Querformat) und je nach Schrift nur 17–25 mm lang.
- Links steht der QR-Code mit der Crate-URL, rechts daneben drei Zeilen, die
  jeweils die volle Breite füllen: klein „c-base cargo“, groß „crate“, groß
  die ID. Alles andere ändert sich zu oft; ein Label soll nie neu gedruckt
  werden müssen.
- Schrift: Der Schriftzug steht in Bai Jamjuree Bold, die ID in Orbitron
  Black, weil Orbitron die Null durchstreicht und sie so nicht mit einem O
  verwechselt wird. Über `LABEL_FONT` lässt sich alles auf `orbitron` oder
  `anybody` umstellen (Standard: `baijamjuree`); zum Vergleichen geht auch
  `?font=…` an der Label-URL. Alle drei Schriften liegen mit ihrer SIL Open
  Font License in `crates/fonts/`.
- Die App liefert das Label in Druckauflösung (300 dpi) als PNG unter
  `/c/<ID>/label.png` und als einseitiges PDF unter `/c/<ID>/label.pdf`. Von
  welchem Gerät gedruckt wird, ist bewusst offen.
- Abschneiden: kein eigener Befehl nötig, das regelt der Druckertreiber. In der
  CUPS-Warteschlange des QL-700 heißen die Optionen `BrCutLabel` (alle n
  Etiketten schneiden) und `BrCutAtEnd` (am Ende des Auftrags schneiden).
- `PUBLIC_BASE_URL` (Umgebungsvariable) legt die Adresse fest, die in QR-Code
  und NFC-Tag steht. Sie muss feststehen, bevor Labels gedruckt werden.
- `LABEL_WIDTH_PX` ist die Druckbreite der Rolle in Pixeln und damit die
  Breite des Labels (62 mm = 696, 29 mm = 306); der Inhalt skaliert mit.

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
  lokaler Branch `bootstrap5`, Commit `f45bfb0` – noch nicht bei c-base
  veröffentlicht.
- `crates/static/crates/app.css` ergänzt nur, was c-logistics eigen ist:
  Eingabefelder im Stil von `.terminal`, das abgedunkelte Stationsbild als
  Hintergrund, die Inhaltstabelle und Anpassungen für Smartphones.
- Formulare bekommen ihr Bootstrap-Markup über `BootstrapFormMixin` und das
  Template `crates/templates/forms/bootstrap.html`.
- Das Logo unter `crates/static/crates/logo.png` stammt von c-beam.

## Entwicklung

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

Tests: `.venv/bin/python manage.py test`

## Offene Punkte

Priorisierte Checkliste samt späteren Feature-Ideen: [TODO.md](TODO.md)
