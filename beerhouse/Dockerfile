# ── Imagen base ──────────────────────────────────────────────────────────────
FROM python:3.13-slim

# ── Variables de entorno del contenedor ──────────────────────────────────────
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=run.py \
    FLASK_ENV=production

# ── Directorio de trabajo ─────────────────────────────────────────────────────
WORKDIR /app

# ── Dependencias del sistema (mysql-connector las necesita) ───────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# ── Dependencias Python ───────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Código del proyecto ───────────────────────────────────────────────────────
COPY . .

# ── Puerto expuesto ───────────────────────────────────────────────────────────
EXPOSE 5000

# ── Comando de inicio ─────────────────────────────────────────────────────────
CMD ["python", "run.py"]
