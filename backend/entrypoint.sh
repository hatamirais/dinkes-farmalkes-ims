#!/bin/sh
set -eu

if [ "${DB_HOST:-}" ] && [ "${DB_PORT:-}" ]; then
  echo "Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT}"
  python - <<'PY'
import os
import time

import psycopg2

host = os.environ.get("DB_HOST")
port = os.environ.get("DB_PORT")
name = os.environ.get("DB_NAME")
user = os.environ.get("DB_USER")
password = os.environ.get("DB_PASSWORD")

deadline = time.time() + int(os.environ.get("DB_WAIT_TIMEOUT", "60"))

while True:
    try:
        connection = psycopg2.connect(
            host=host,
            port=port,
            dbname=name,
            user=user,
            password=password,
        )
        connection.close()
        break
    except psycopg2.OperationalError:
        if time.time() >= deadline:
            raise
        time.sleep(2)
PY
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@" \
  --workers "${GUNICORN_WORKERS:-3}" \
  --timeout "${GUNICORN_TIMEOUT:-120}"
