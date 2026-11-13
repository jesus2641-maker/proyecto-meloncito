#!/bin/sh
# Arranque del contenedor (Railway o docker compose).
set -e

# Crea tablas y carga datos iniciales si la BD está vacía (idempotente).
# Desactívalo con RUN_DB_INIT=0 si gestionas la BD por fuera.
if [ "${RUN_DB_INIT:-1}" = "1" ]; then
  python -m scripts.init_db
fi

exec gunicorn run:app \
  --bind "0.0.0.0:${PORT:-5000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --threads "${GUNICORN_THREADS:-4}" \
  --timeout "${GUNICORN_TIMEOUT:-60}" \
  --access-logfile - --error-logfile -
