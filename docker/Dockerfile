# ── Imagen base ──────────────────────────────────────────────────────────────
FROM python:3.13-slim

# ── Variables de entorno del contenedor ──────────────────────────────────────
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FLASK_APP=run.py

WORKDIR /app

# ── Dependencias Python ───────────────────────────────────────────────────────
# mysql-connector-python trae un wheel puro, así que no hacen falta gcc ni
# libmysqlclient: la imagen queda mucho más liviana y compila más rápido.
COPY requirements.txt .
RUN pip install -r requirements.txt

# ── Código del proyecto ───────────────────────────────────────────────────────
COPY . .

# ── Usuario sin privilegios ───────────────────────────────────────────────────
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

# Railway inyecta PORT; en local se usa 5000.
EXPOSE 5000

CMD ["sh", "scripts/start.sh"]
