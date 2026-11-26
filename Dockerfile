# c-logistics as a container. Runs with Docker and Podman.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# libfribidi0: Pillow needs it for the OpenType features of the label fonts
# (slashed zero with LABEL_FONT=anybody).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libfribidi0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Static files are baked into the image; whitenoise serves them.
RUN DJANGO_DEBUG=0 DJANGO_SECRET_KEY=nur-fuer-den-build python manage.py collectstatic --noinput

# Database (SQLite) and photos live under /data – a volume belongs there.
# The folder already belongs to the user `app` in the image, so that a new volume
# takes over its permissions (also with rootless Podman).
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
