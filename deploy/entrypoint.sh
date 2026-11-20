#!/bin/sh
# Start im Container: Datenbank auf Stand bringen, dann den App-Server starten.
set -e

# Postgres braucht nach dem Start ein paar Sekunden; solange neu versuchen.
tries=0
until python manage.py migrate --noinput; do
    tries=$((tries + 1))
    if [ "$tries" -ge 15 ]; then
        echo "Datenbank nicht erreichbar, gebe auf." >&2
        exit 1
    fi
    echo "Datenbank noch nicht bereit, neuer Versuch in 2 s ($tries/15) …" >&2
    sleep 2
done

exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-2}" \
    --timeout 60 \
    --access-logfile - \
    --forwarded-allow-ips '*'
