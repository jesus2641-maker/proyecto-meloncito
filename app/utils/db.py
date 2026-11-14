import logging
import mysql.connector
from flask import g, has_app_context
from config import Config

logger = logging.getLogger(__name__)


def get_connection():
    """
    Devuelve una conexión activa a la base de datos (TiDB Cloud / MySQL con TLS).
    Si existe un contexto de aplicación Flask, gestiona la conexión en `flask.g`
    para reutilizarla si sigue abierta y garantizar su cierre automático al final
    de la petición mediante `teardown_appcontext` (close_db).
    No mantiene conexiones globales abiertas para evitar desconexiones por inactividad en TiDB.
    """
    try:
        if has_app_context():
            db_conn = g.get("db")
            if db_conn is None or not db_conn.is_connected():
                db_conn = mysql.connector.connect(**Config.get_db_config())
                g.db = db_conn
                conns = g.get("_db_connections")
                if conns is None:
                    conns = []
                    g._db_connections = conns
                conns.append(db_conn)
            return db_conn

        return mysql.connector.connect(**Config.get_db_config())
    except mysql.connector.Error:
        logger.exception("Error al conectar a la base de datos")
        raise


def close_db(exception=None):
    """
    Cierra la conexión (o conexiones) de base de datos asociadas a la petición actual.
    Se ejecuta automáticamente al finalizar cada petición mediante teardown_appcontext.
    """
    db_conn = g.pop("db", None)
    if db_conn is not None:
        try:
            if db_conn.is_connected():
                db_conn.close()
        except Exception:
            logger.debug("Error al cerrar g.db en teardown_appcontext", exc_info=True)

    conns = g.pop("_db_connections", None) or []
    for conn in conns:
        if conn is not db_conn:
            try:
                if conn.is_connected():
                    conn.close()
            except Exception:
                pass


def init_db_app(app):
    """Registra el cierre automático de conexión al finalizar el contexto de cada petición."""
    app.teardown_appcontext(close_db)
