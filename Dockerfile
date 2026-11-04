# syntax=docker/dockerfile:1
ARG IMAGEN_PYTHON=python:3.11-slim-bookworm
FROM ${IMAGEN_PYTHON} AS dependencias
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /construccion
COPY requirements/ ./requirements/
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --only-binary=:all: -r requirements/render.txt

FROM ${IMAGEN_PYTHON} AS aplicacion
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.contenedor \
    PORT=8000 \
    RAIZ_ARCHIVOS=/app/media \
    RAIZ_ESTATICOS=/app/staticfiles
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 vitago \
    && useradd --uid 10001 --gid vitago --no-create-home --home-dir /app vitago
WORKDIR /app
COPY --from=dependencias /opt/venv /opt/venv
COPY apps/ ./apps/
COPY config/ ./config/
COPY scripts/docker/ ./scripts/docker/
COPY manage.py gunicorn.conf.py docker-entrypoint.sh ./
RUN sed -i 's/\r$//' /app/docker-entrypoint.sh \
    && chmod 0555 /app/docker-entrypoint.sh \
    && mkdir -p /app/media /app/staticfiles \
    && chown vitago:vitago /app/media /app/staticfiles
USER vitago
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD ["python", "-m", "scripts.docker.comprobar_salud"]
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["servidor"]
