"""
Modelo de Ofertas y Promociones.

Este módulo gestiona las ofertas comerciales aplicadas a productos o variantes
específicas en la tabla `ofertas`, incluyendo su creación, actualización,
activación/desactivación y consulta de promociones vigentes.
"""

# Función para obtener una conexión activa a MySQL
from app.utils.db import get_connection


class Oferta:
    """
    Modelo para administrar las ofertas y descuentos del catálogo.
    """

    @staticmethod
    def listar_todas():
        """
        Lista todas las ofertas registradas (tanto activas como inactivas) con
        información del producto, categorías asociadas y variante si aplica.

        Returns:
            list[dict]: Lista de diccionarios con todas las ofertas ordenadas
                desde la más reciente.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        # Se usa LEFT JOIN en categorías y variantes porque una oferta puede aplicar a todo un producto
        cursor.execute("""
            SELECT o.*, p.nombre_producto, p.marca, p.imagen_url,
                   GROUP_CONCAT(DISTINCT c.nombre_categoria) AS categorias,
                   v.presentacion, v.precio as precio_original
            FROM ofertas o
            JOIN productos p ON o.id_producto = p.id_producto
            LEFT JOIN productos_categorias pc ON p.id_producto = pc.id_producto
            LEFT JOIN categorias c ON pc.id_categoria = c.id_categoria
            LEFT JOIN variantes_producto v ON o.id_variante = v.id_variante
            GROUP BY o.id_oferta, p.nombre_producto, p.marca, p.imagen_url, v.presentacion, v.precio
            ORDER BY o.fecha_creacion DESC
        """)
        ofertas = cursor.fetchall()
        cursor.close()
        conn.close()
        return ofertas

    @staticmethod
    def listar_activas():
        """
        Lista únicamente las ofertas activas y no expiradas.

        Filtra por `o.activa = TRUE` y verifica que `fecha_fin` sea nula o
        posterior a la fecha y hora actual del servidor MySQL (`NOW()`).

        Returns:
            list[dict]: Lista de ofertas vigentes para mostrar en la tienda.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        # Consultar ofertas habilitadas cuya fecha de finalización aún no ha vencido
        cursor.execute("""
            SELECT o.*, p.nombre_producto, p.marca, p.imagen_url,
                   GROUP_CONCAT(DISTINCT c.nombre_categoria) AS categorias,
                   v.presentacion, v.precio as precio_original
            FROM ofertas o
            JOIN productos p ON o.id_producto = p.id_producto
            LEFT JOIN productos_categorias pc ON p.id_producto = pc.id_producto
            LEFT JOIN categorias c ON pc.id_categoria = c.id_categoria
            LEFT JOIN variantes_producto v ON o.id_variante = v.id_variante
            WHERE o.activa = TRUE
              AND (o.fecha_fin IS NULL OR o.fecha_fin > NOW())
            GROUP BY o.id_oferta, p.nombre_producto, p.marca, p.imagen_url, v.presentacion, v.precio
            ORDER BY o.fecha_creacion DESC
        """)
        ofertas = cursor.fetchall()
        cursor.close()
        conn.close()
        return ofertas

    @staticmethod
    def obtener_por_id(id_oferta):
        """
        Obtiene los datos detallados de una oferta por su ID.

        Args:
            id_oferta (int): Identificador único de la oferta.

        Returns:
            dict | None: Diccionario con los datos de la oferta o None si no existe.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT o.*, p.nombre_producto, p.marca, p.imagen_url,
                   v.presentacion, v.precio as precio_original
            FROM ofertas o
            JOIN productos p ON o.id_producto = p.id_producto
            LEFT JOIN variantes_producto v ON o.id_variante = v.id_variante
            WHERE o.id_oferta = %s
        """, (id_oferta,))
        oferta = cursor.fetchone()
        cursor.close()
        conn.close()
        return oferta

    @staticmethod
    def crear(id_producto, id_variante, descuento_porcentaje, precio_oferta, titulo, descripcion, fecha_inicio=None, fecha_fin=None):
        """
        Crea una nueva oferta en la base de datos.

        Args:
            id_producto (int): ID del producto al que aplica la oferta.
            id_variante (int | None): ID de la variante específica (o None si aplica a todo el producto).
            descuento_porcentaje (float | Decimal | None): Porcentaje de descuento.
            precio_oferta (float | Decimal | None): Precio promocional fijo.
            titulo (str): Título visible de la promoción.
            descripcion (str): Descripción de la oferta.
            fecha_inicio (datetime | str, optional): Fecha/hora de inicio de vigencia.
            fecha_fin (datetime | str, optional): Fecha/hora de fin de vigencia.

        Returns:
            int: ID autogenerado de la nueva oferta.
        """
        conn = get_connection()
        cursor = conn.cursor()
        # Insertar la oferta con parámetros preparados
        cursor.execute("""
            INSERT INTO ofertas (id_producto, id_variante, descuento_porcentaje, precio_oferta, titulo, descripcion, fecha_inicio, fecha_fin)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (id_producto, id_variante, descuento_porcentaje, precio_oferta, titulo, descripcion, fecha_inicio, fecha_fin))
        conn.commit()
        nuevo_id = cursor.lastrowid
        cursor.close()
        conn.close()
        return nuevo_id

    @staticmethod
    def actualizar(id_oferta, id_producto, id_variante, descuento_porcentaje, precio_oferta, titulo, descripcion, activa, fecha_inicio=None, fecha_fin=None):
        """
        Actualiza todos los campos de una oferta existente.

        Args:
            id_oferta (int): ID de la oferta a actualizar.
            id_producto (int): ID del producto asociado.
            id_variante (int | None): ID de la variante asociada.
            descuento_porcentaje (float | Decimal | None): Porcentaje de descuento.
            precio_oferta (float | Decimal | None): Precio promocional.
            titulo (str): Título de la oferta.
            descripcion (str): Descripción detallada.
            activa (bool | int): Estado de activación de la oferta.
            fecha_inicio (datetime | str, optional): Fecha de inicio.
            fecha_fin (datetime | str, optional): Fecha de finalización.
        """
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE ofertas
            SET id_producto = %s, id_variante = %s, descuento_porcentaje = %s, 
                precio_oferta = %s, titulo = %s, descripcion = %s, 
                activa = %s, fecha_inicio = %s, fecha_fin = %s
            WHERE id_oferta = %s
        """, (id_producto, id_variante, descuento_porcentaje, precio_oferta, titulo, descripcion, activa, fecha_inicio, fecha_fin, id_oferta))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def toggle_activa(id_oferta):
        """
        Alterna el estado booleano `activa` de una oferta (activa <-> inactiva).

        Args:
            id_oferta (int): ID de la oferta a conmutar.
        """
        conn = get_connection()
        cursor = conn.cursor()
        # `NOT activa` invierte el valor booleano actual directamente en SQL
        cursor.execute("UPDATE ofertas SET activa = NOT activa WHERE id_oferta = %s", (id_oferta,))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def eliminar(id_oferta):
        """
        Elimina permanentemente una oferta de la base de datos.

        Args:
            id_oferta (int): ID de la oferta a eliminar.
        """
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ofertas WHERE id_oferta = %s", (id_oferta,))
        conn.commit()
        cursor.close()
        conn.close()
