from app.utils.db import get_connection


class Direccion:
    @staticmethod
    def crear(id_usuario, linea_direccion, ciudad, departamento=None, codigo_postal=None, alias=None, es_principal=0):
        conn = get_connection()
        cursor = conn.cursor()

        # Si se marca como principal, desmarcar las demás
        if es_principal:
            cursor.execute(
                "UPDATE direcciones SET es_principal = 0 WHERE id_usuario = %s",
                (id_usuario,)
            )

        cursor.execute("""
            INSERT INTO direcciones (id_usuario, alias, linea_direccion, ciudad, departamento, codigo_postal, es_principal)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (id_usuario, alias, linea_direccion, ciudad, departamento, codigo_postal, 1 if es_principal else 0))
        conn.commit()
        id_direccion = cursor.lastrowid
        cursor.close()
        conn.close()
        return id_direccion

    @staticmethod
    def listar_por_usuario(id_usuario):
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM direcciones
            WHERE id_usuario = %s
            ORDER BY es_principal DESC, id_direccion DESC
        """, (id_usuario,))
        direcciones = cursor.fetchall()
        cursor.close()
        conn.close()
        return direcciones

    @staticmethod
    def obtener_por_id(id_direccion):
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM direcciones WHERE id_direccion = %s", (id_direccion,))
        direccion = cursor.fetchone()
        cursor.close()
        conn.close()
        return direccion

    @staticmethod
    def eliminar(id_direccion, id_usuario):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM direcciones WHERE id_direccion = %s AND id_usuario = %s",
            (id_direccion, id_usuario)
        )
        conn.commit()
        eliminado = cursor.rowcount > 0
        cursor.close()
        conn.close()
        return eliminado
