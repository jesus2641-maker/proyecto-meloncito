from app.utils.db import get_connection


class MetodoPago:
    @staticmethod
    def crear(id_usuario, tipo, detalle=None, es_predeterminado=0):
        conn = get_connection()
        cursor = conn.cursor()

        # Si se marca como predeterminado, desmarcar los demás
        if es_predeterminado:
            cursor.execute(
                "UPDATE metodos_pago SET es_predeterminado = 0 WHERE id_usuario = %s",
                (id_usuario,)
            )

        cursor.execute("""
            INSERT INTO metodos_pago (id_usuario, tipo, detalle, es_predeterminado)
            VALUES (%s, %s, %s, %s)
        """, (id_usuario, tipo, detalle, 1 if es_predeterminado else 0))
        conn.commit()
        id_metodo = cursor.lastrowid
        cursor.close()
        conn.close()
        return id_metodo

    @staticmethod
    def listar_por_usuario(id_usuario):
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM metodos_pago
            WHERE id_usuario = %s
            ORDER BY es_predeterminado DESC, id_metodo_pago DESC
        """, (id_usuario,))
        metodos = cursor.fetchall()
        cursor.close()
        conn.close()
        return metodos

    @staticmethod
    def obtener_por_id(id_metodo_pago):
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM metodos_pago WHERE id_metodo_pago = %s", (id_metodo_pago,))
        metodo = cursor.fetchone()
        cursor.close()
        conn.close()
        return metodo

    @staticmethod
    def eliminar(id_metodo_pago, id_usuario):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM metodos_pago WHERE id_metodo_pago = %s AND id_usuario = %s",
            (id_metodo_pago, id_usuario)
        )
        conn.commit()
        eliminado = cursor.rowcount > 0
        cursor.close()
        conn.close()
        return eliminado
