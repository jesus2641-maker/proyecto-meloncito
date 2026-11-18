"""
Gestión de conexiones a la base de datos MySQL / TiDB Cloud para Beer House.

Provee un punto único de obtención de conexiones (`get_connection`) integrado con
el ciclo de vida de las peticiones HTTP de Flask (`flask.g` y `teardown_appcontext`),
además de soportar ejecución fuera de contexto web (scripts, tareas programadas).
"""

import logging
import mysql.connector
from flask import g, has_app_context
from config import Config

# Logger del módulo para registrar errores de conexión o advertencias de cierre
logger = logging.getLogger(__name__)


def get_connection():
    """
    Devuelve una conexión activa a la base de datos (TiDB Cloud / MySQL con TLS).

    Comportamiento según el contexto:
    - Dentro de un contexto de aplicación Flask (`has_app_context() == True`):
      reutiliza la conexión almacenada en `flask.g.db` si sigue abierta; de lo
      contrario abre una nueva, la guarda en `g.db` y la registra en
      `g._db_connections` para asegurar su cierre al finalizar la petición.
    - Fuera de un contexto Flask (por ejemplo, scripts CLI o cron jobs):
      abre y devuelve una conexión nueva directamente (el llamador debe cerrarla).

    No mantiene conexiones globales abiertas entre peticiones para evitar
    desconexiones por inactividad en TiDB Cloud.

    Returns:
        mysql.connector.MySQLConnection: Conexión activa lista para crear cursores.

    Raises:
        mysql.connector.Error: Si falla la conexión con el servidor de base de datos.
    """
    try:
        # Verificamos si estamos ejecutando dentro de un AppContext de Flask
        # NOTA: `flask.g` dura solo lo que dura una petición HTTP; así reutilizamos la misma
        # conexión en varios modelos durante una sola página y se cierra sola al terminar (close_db).
        if has_app_context():
            # Intentamos recuperar la conexión previamente cacheada en `g` para esta petición
            db_conn = g.get("db")
            # Si no existe aún o la conexión se cayó/cerró, abrimos una nueva
            if db_conn is None or not db_conn.is_connected():
                db_conn = mysql.connector.connect(**Config.get_db_config())
                g.db = db_conn
                # Mantenemos una lista de todas las conexiones creadas en este contexto
                # por si alguna se reemplazó tras una reconexión
                conns = g.get("_db_connections")
                if conns is None:
                    conns = []
                    g._db_connections = conns
                conns.append(db_conn)
            return db_conn

        # Fuera de Flask (sin AppContext), creamos una conexión independiente
        return mysql.connector.connect(**Config.get_db_config())
    except mysql.connector.Error:
        # Registramos el stacktrace completo para diagnóstico y propagamos el error
        logger.exception("Error al conectar a la base de datos")
        raise


def close_db(exception=None):
    """
    Cierra la conexión (o conexiones) de base de datos asociadas a la petición actual.

    Se ejecuta automáticamente al finalizar cada petición o contexto de aplicación
    gracias al hook `app.teardown_appcontext(close_db)`.

    Args:
        exception (Exception | None): Excepción no capturada durante la petición,
            recibida por convención de Flask `teardown_appcontext` (no se utiliza).
    """
    # Extraemos y eliminamos la referencia principal `g.db` si existía
    db_conn = g.pop("db", None)
    if db_conn is not None:
        try:
            # Solo cerramos si el socket sigue conectado para evitar errores innecesarios
            if db_conn.is_connected():
                db_conn.close()
        except Exception:
            # En teardown no debemos romper la respuesta si el cierre falla
            logger.debug("Error al cerrar g.db en teardown_appcontext", exc_info=True)

    # Recorremos cualquier otra conexión que haya quedado en `_db_connections`
    # (por ejemplo, si hubo reconexiones en la misma petición)
    conns = g.pop("_db_connections", None) or []
    for conn in conns:
        if conn is not db_conn:
            try:
                if conn.is_connected():
                    conn.close()
            except Exception:
                pass


def init_db_app(app):
    """
    Registra el cierre automático de conexión al finalizar el contexto de cada petición.

    Args:
        app (flask.Flask): Instancia de la aplicación Flask sobre la cual registrar
            la función `close_db` en `teardown_appcontext`.
    """
    app.teardown_appcontext(close_db)
