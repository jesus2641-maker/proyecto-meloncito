"""
Modelo de Métodos de Pago del usuario.

Este módulo gestiona los métodos de pago guardados por los clientes en la
tabla `metodos_pago`, aplicando sanitización de datos sensibles de tarjetas
para no almacenar números completos de tarjeta en la base de datos.
"""

# Función para obtener una conexión activa a MySQL
from app.utils.db import get_connection
# Módulo de expresiones regulares para extraer dígitos y detectar números de tarjeta
import re


class MetodoPago:
    """
    Modelo para administrar los métodos de pago registrados por cada usuario.
    """

    @staticmethod
    def sanitizar_detalle_tarjeta(detalle):
        """
        Sanitiza los datos de una tarjeta para guardar solo información segura.

        Si el texto contiene 13 o más dígitos (patrón típico de un PAN de tarjeta),
        enmascara todos los dígitos excepto los últimos 4.

        Args:
            detalle (str | None): Cadena que puede contener información de tarjeta.

        Returns:
            str | None: Cadena enmascarada con solo los últimos 4 dígitos,
                el detalle original si no parece un número de tarjeta, o None si está vacío.
        """
        if not detalle:
            return None
            
        # Extraer solo dígitos eliminando espacios, guiones u otros caracteres
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
        Crea un método de pago seguro para un usuario.

        Para tarjetas de crédito o débito, el detalle se sanitiza para conservar
        únicamente información segura (últimos 4 dígitos, sin almacenar números completos).

        Args:
            id_usuario (int): ID del usuario propietario.
            tipo (str): Tipo de método de pago (ej. "Tarjeta de crédito", "PayPal", "Efectivo").
            detalle (str, optional): Información adicional o referencia del método.
            es_predeterminado (int | bool, optional): Indica si será el método por defecto.

        Returns:
            int: ID autogenerado del método de pago creado.
        """
        conn = get_connection()
        cursor = conn.cursor()

        # Sanitizar detalle si el tipo corresponde a una tarjeta bancaria
        if detalle and tipo.lower() in ['tarjeta de crédito', 'tarjeta de debito', 'tarjeta']:
            detalle = MetodoPago.sanitizar_detalle_tarjeta(detalle)

        # Si se marca como predeterminado, desmarcar los demás métodos del usuario
        if es_predeterminado:
            cursor.execute(
                "UPDATE metodos_pago SET es_predeterminado = 0 WHERE id_usuario = %s",
                (id_usuario,)
            )

        # Insertar el nuevo método de pago en la base de datos
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
        """
        Lista todos los métodos de pago de un usuario, mostrando primero el predeterminado.

        Args:
            id_usuario (int): ID del usuario.

        Returns:
            list[dict]: Lista de diccionarios con los métodos de pago del usuario.
        """
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
        """
        Obtiene un método de pago específico por su ID.

        Args:
            id_metodo_pago (int): ID del método de pago.

        Returns:
            dict | None: Diccionario con los datos del método o None si no existe.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM metodos_pago WHERE id_metodo_pago = %s", (id_metodo_pago,))
        metodo = cursor.fetchone()
        cursor.close()
        conn.close()
        return metodo

    @staticmethod
    def eliminar(id_metodo_pago, id_usuario):
        """
        Elimina un método de pago verificando que pertenezca al usuario indicado.

        Args:
            id_metodo_pago (int): ID del método de pago a eliminar.
            id_usuario (int): ID del usuario propietario.

        Returns:
            bool: True si se eliminó el registro, False en caso contrario.
        """
        conn = get_connection()
        cursor = conn.cursor()
        # Filtrar también por id_usuario para evitar borrados no autorizados
        cursor.execute(
            "DELETE FROM metodos_pago WHERE id_metodo_pago = %s AND id_usuario = %s",
            (id_metodo_pago, id_usuario)
        )
        conn.commit()
        eliminado = cursor.rowcount > 0
        cursor.close()
        conn.close()
        return eliminado
