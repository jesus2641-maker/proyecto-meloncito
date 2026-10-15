from app.utils.db import get_connection
import re


class MetodoPago:
    @staticmethod
    def sanitizar_detalle_tarjeta(detalle):
        """
        Sanitiza los datos de una tarjeta para guardar solo información segura.
        
        Args:
            detalle: String que puede contener información de tarjeta
            
        Returns:
            String con solo los últimos 4 dígitos y tipo de tarjeta
        """
        if not detalle:
            return None
            
        # Extraer solo dígitos
        digits_only = re.sub(r'\D', '', detalle)
        
        # Si hay 13+ dígitos (puede ser un número de tarjeta), guardar solo los últimos 4
        if len(digits_only) >= 13:
            ultimos_4 = digits_only[-4:]
            return f"**** **** **** {ultimos_4}"
        
        # Si no parece ser un número de tarjeta completo, devolver tal cual
        return detalle

    @staticmethod
    def crear(id_usuario, tipo, detalle=None, es_predeterminado=0):
        """
        Crea un método de pago seguro.
        
        Para tarjetas de crédito, el detalle debe contener solo información segura:
        - Últimos 4 dígitos de la tarjeta
        - Mes y año de expiración
        - Tipo de tarjeta (Visa, Mastercard, etc.)
        
        NO guardar números completos de tarjetas.
        """
        conn = get_connection()
        cursor = conn.cursor()

        # Sanitizar detalle si es una tarjeta
        if detalle and tipo.lower() in ['tarjeta de crédito', 'tarjeta de debito', 'tarjeta']:
            detalle = MetodoPago.sanitizar_detalle_tarjeta(detalle)

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
