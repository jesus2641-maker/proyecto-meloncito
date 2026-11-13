"""
Inicializa la base de datos en cualquier MySQL (local, docker, Railway...).

Ejecuta database/schema.sql y, si la tabla `categorias` está vacía,
database/seed_data.sql. Es idempotente: se puede correr en cada despliegue.

Ignora las líneas `CREATE DATABASE` / `USE ...` de los .sql para trabajar
siempre sobre la base configurada (en Railway se llama `railway`, no
`beerhouse_db`).

Uso:
    python -m scripts.init_db            # schema + seed si está vacía
    python -m scripts.init_db --no-seed  # solo schema
"""

import re
import sys
from pathlib import Path

import mysql.connector

from config import Config

RAIZ = Path(__file__).resolve().parent.parent
SCHEMA = RAIZ / "database" / "schema.sql"
SEED = RAIZ / "database" / "seed_data.sql"

_IGNORAR = re.compile(r"^\s*(CREATE\s+DATABASE|USE)\b", re.IGNORECASE)


def leer_sentencias(ruta: Path):
    """Devuelve las sentencias del archivo sin comentarios ni CREATE DATABASE/USE."""
    lineas = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if linea.strip().startswith("--") or _IGNORAR.match(linea):
            continue
        lineas.append(linea)
    # Los .sql del proyecto no tienen ';' dentro de cadenas ni DELIMITER,
    # así que separar por ';' es seguro.
    return [s.strip() for s in "\n".join(lineas).split(";") if s.strip()]


def ejecutar_archivo(cursor, ruta: Path):
    sentencias = leer_sentencias(ruta)
    for sql in sentencias:
        cursor.execute(sql)
    print(f"  ✔ {ruta.name}: {len(sentencias)} sentencias")


def main():
    cfg = Config.get_db_config()
    print(f"Conectando a {cfg['host']}:{cfg['port']}/{cfg['database']} ...")
    conn = mysql.connector.connect(**cfg)
    try:
        cur = conn.cursor()
        ejecutar_archivo(cur, SCHEMA)
        conn.commit()

        if "--no-seed" not in sys.argv:
            cur.execute("SELECT COUNT(*) FROM categorias")
            if cur.fetchone()[0] == 0:
                ejecutar_archivo(cur, SEED)
                conn.commit()
            else:
                print("  • Ya hay datos, se omite el seed")
        cur.close()
    finally:
        conn.close()
    print("Base de datos lista.")


if __name__ == "__main__":
    main()
