# c-logistics als Container. Läuft mit Docker und Podman.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# libfribidi0: Pillow braucht es für die OpenType-Merkmale der Label-Schriften
# (durchgestrichene Null bei LABEL_FONT=anybody).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libfribidi0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Statische Dateien stecken im Image; whitenoise liefert sie aus.
RUN DJANGO_DEBUG=0 DJANGO_SECRET_KEY=nur-fuer-den-build python manage.py collectstatic --noinput

# Datenbank (SQLite) und Fotos liegen unter /data – dort gehört ein Volume hin.
# Der Ordner gehört schon im Image dem Nutzer `app`, damit ein neues Volume
# dessen Rechte übernimmt (auch bei Podman ohne root).
RUN useradd --system --uid 1000 --home-dir /app app \
    && mkdir -p /data/media \
    && chown -R app:app /data
USER app

ENV DJANGO_DEBUG=0 \
    DJANGO_SQLITE_PATH=/data/db.sqlite3 \
    DJANGO_MEDIA_ROOT=/data/media \
    GUNICORN_WORKERS=2

VOLUME /data
EXPOSE 8000
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
