import os
import sys
import mysql.connector
from dotenv import load_dotenv


def dividir_sentencias(sql_texto):
    """Elimina comentarios de línea (-- ...) y divide el SQL por ';'."""
    lineas_limpias = []
    for linea in sql_texto.splitlines():
        if linea.strip().startswith("--"):
            continue
        lineas_limpias.append(linea)

    contenido = "\n".join(lineas_limpias)
    return [s.strip() for s in contenido.split(";") if s.strip()]


def main():
    load_dotenv()

    db_host = os.getenv("DB_HOST")
    db_port = int(os.getenv("DB_PORT", "4000"))
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    db_name = os.getenv("DB_NAME")
    db_ssl_ca = (os.getenv("DB_SSL_CA") or "").strip()

    if not all([db_host, db_user, db_password, db_name]):
        print("Error: Faltan variables de entorno obligatorias (DB_HOST, DB_USER, DB_PASSWORD, DB_NAME).")
        sys.exit(1)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    schema_path = os.path.join(base_dir, "database", "schema.sql")

    if not os.path.isfile(schema_path):
        print(f"Error: No se encontró el archivo {schema_path}")
        sys.exit(1)

    with open(schema_path, "r", encoding="utf-8") as f:
        sql_texto = f.read()

    sentencias = dividir_sentencias(sql_texto)

    conn_cfg = {
        "host": db_host,
        "port": db_port,
        "user": db_user,
        "password": db_password,
        "database": db_name,
        "ssl_disabled": False,
        "connect_timeout": 10,
    }
    if db_ssl_ca:
        conn_cfg["ssl_ca"] = db_ssl_ca
        conn_cfg["ssl_verify_cert"] = True

    conn = None
    cursor = None
    try:
        print(f"Conectando a TiDB Cloud ({db_host}:{db_port}/{db_name}) con SSL...")
        conn = mysql.connector.connect(**conn_cfg)
        cursor = conn.cursor()

        for idx, sentencia in enumerate(sentencias, start=1):
            print(f"\n--- Ejecutando sentencia {idx}/{len(sentencias)} ---")
            print(sentencia)
            try:
                cursor.execute(sentencia)
            except mysql.connector.Error as err:
                print(f"\nERROR en la sentencia {idx}: {err}")
                conn.rollback()
                sys.exit(1)

        conn.commit()
        print("\nCommit realizado correctamente.")

        cursor.execute("SHOW TABLES")
        tablas = [fila[0] for fila in cursor.fetchall()]
        print(f"\nTablas en `{db_name}` ({len(tablas)}):")
        for tabla in tablas:
            print(f"  - {tabla}")

    except mysql.connector.Error as err:
        print(f"Error de conexión o ejecución en TiDB: {err}")
        sys.exit(1)
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None and conn.is_connected():
            conn.close()
            print("\nConexión cerrada.")


if __name__ == "__main__":
    main()
