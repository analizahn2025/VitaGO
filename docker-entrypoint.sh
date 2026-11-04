#!/bin/sh
set -eu

if [ "$#" -eq 0 ] || [ "$1" = "servidor" ]; then
    set -- python -m gunicorn --config gunicorn.conf.py config.wsgi:application \
        --control-socket /tmp/vitago-gunicorn.ctl \
        --bind "0.0.0.0:${PORT:-8000}" \
        --workers "${TRABAJADORES_GUNICORN:-2}" \
        --timeout "${SEGUNDOS_ESPERA_GUNICORN:-60}" \
        --access-logfile - --error-logfile -
fi

python -m scripts.docker.arranque "$@"
exec "$@"
