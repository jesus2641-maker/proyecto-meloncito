import mysql.connector
from config import Config

def get_connection():
    """
    Devuelve una nueva conexión a la base de datos.
    Usa siempre esta función en lugar de escribir credenciales
    o el nombre de la BD directamente en otros archivos.
    """
    try:
        conn = mysql.connector.connect(**Config.get_db_config())
        return conn
    except mysql.connector.Error as err:
        print(f"Error al conectar a la base de datos: {err}")
        raise
