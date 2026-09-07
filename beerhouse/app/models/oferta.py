from app.utils.db import get_connection


class Oferta:
    @staticmethod
    def listar_todas():
        """Lista todas las ofertas (activas e inactivas)."""
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
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
        """Lista solo las ofertas activas."""
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
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
        """Obtiene una oferta por su ID."""
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
        """Crea una nueva oferta."""
        conn = get_connection()
        cursor = conn.cursor()
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
        """Actualiza una oferta existente."""
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
        """Activa/desactiva una oferta."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE ofertas SET activa = NOT activa WHERE id_oferta = %s", (id_oferta,))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def eliminar(id_oferta):
        """Elimina una oferta."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ofertas WHERE id_oferta = %s", (id_oferta,))
        conn.commit()
        cursor.close()
        conn.close()
