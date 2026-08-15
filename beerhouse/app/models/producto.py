from app.utils.db import get_connection


class Producto:
    @staticmethod
    def listar_con_variantes():
        """Devuelve productos activos junto con sus variantes (precio/stock)."""
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT p.id_producto, p.nombre_producto, p.descripcion, p.marca,
                   p.imagen_url, c.nombre_categoria,
                   v.id_variante, v.presentacion, v.precio, v.stock
            FROM productos p
            JOIN categorias c ON p.id_categoria = c.id_categoria
            JOIN variantes_producto v ON v.id_producto = p.id_producto
            WHERE p.activo = TRUE
            ORDER BY p.nombre_producto
        """)
        filas = cursor.fetchall()
        cursor.close()
        conn.close()
        return filas

    @staticmethod
    def listar_admin():
        """Lista todos los productos (activos e inactivos) con información de variantes."""
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT p.id_producto, p.nombre_producto, p.descripcion, p.marca,
                   p.imagen_url, p.activo, p.fecha_creacion,
                   c.id_categoria, c.nombre_categoria,
                   COUNT(v.id_variante) AS total_variantes,
                   COALESCE(SUM(v.stock), 0) AS stock_total,
                   MIN(v.precio) AS precio_minimo,
                   MAX(v.precio) AS precio_maximo
            FROM productos p
            LEFT JOIN categorias c ON p.id_categoria = c.id_categoria
            LEFT JOIN variantes_producto v ON v.id_producto = p.id_producto
            GROUP BY p.id_producto, p.nombre_producto, p.descripcion, p.marca,
                     p.imagen_url, p.activo, p.fecha_creacion,
                     c.id_categoria, c.nombre_categoria
            ORDER BY p.id_producto DESC
        """)
        filas = cursor.fetchall()
        cursor.close()
        conn.close()
        return filas

    @staticmethod
    def obtener_por_id(id_producto):
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT p.*, c.nombre_categoria
            FROM productos p
            LEFT JOIN categorias c ON p.id_categoria = c.id_categoria
            WHERE p.id_producto = %s
        """, (id_producto,))
        producto = cursor.fetchone()
        cursor.close()
        conn.close()
        return producto

    @staticmethod
    def crear(id_categoria, nombre_producto, descripcion, marca, imagen_url=None):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO productos (id_categoria, nombre_producto, descripcion, marca, imagen_url)
               VALUES (%s, %s, %s, %s, %s)""",
            (id_categoria, nombre_producto, descripcion, marca, imagen_url)
        )
        conn.commit()
        nuevo_id = cursor.lastrowid
        cursor.close()
        conn.close()
        return nuevo_id

    @staticmethod
    def actualizar(id_producto, id_categoria, nombre_producto, descripcion, marca, imagen_url=None, activo=1):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE productos
            SET id_categoria = %s, nombre_producto = %s, descripcion = %s,
                marca = %s, imagen_url = %s, activo = %s
            WHERE id_producto = %s
        """, (id_categoria, nombre_producto, descripcion, marca, imagen_url, activo, id_producto))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def toggle_activo(id_producto):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE productos SET activo = NOT activo WHERE id_producto = %s", (id_producto,))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def eliminar(id_producto):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM productos WHERE id_producto = %s", (id_producto,))
        conn.commit()
        cursor.close()
        conn.close()


class VarianteProducto:
    @staticmethod
    def listar_por_producto(id_producto):
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM variantes_producto WHERE id_producto = %s ORDER BY id_variante ASC",
            (id_producto,)
        )
        variantes = cursor.fetchall()
        cursor.close()
        conn.close()
        return variantes

    @staticmethod
    def obtener_por_id(id_variante):
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM variantes_producto WHERE id_variante = %s", (id_variante,))
        variante = cursor.fetchone()
        cursor.close()
        conn.close()
        return variante

    @staticmethod
    def crear(id_producto, presentacion, precio, stock, sku=None):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO variantes_producto (id_producto, presentacion, precio, stock, sku)
               VALUES (%s, %s, %s, %s, %s)""",
            (id_producto, presentacion, precio, stock, sku)
        )
        conn.commit()
        nuevo_id = cursor.lastrowid
        cursor.close()
        conn.close()
        return nuevo_id

    @staticmethod
    def actualizar(id_variante, presentacion, precio, stock, sku=None):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE variantes_producto
            SET presentacion = %s, precio = %s, stock = %s, sku = %s
            WHERE id_variante = %s
        """, (presentacion, precio, stock, sku, id_variante))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def actualizar_stock(id_variante, nueva_cantidad):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE variantes_producto SET stock = %s WHERE id_variante = %s",
            (nueva_cantidad, id_variante)
        )
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def eliminar(id_variante):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM variantes_producto WHERE id_variante = %s", (id_variante,))
        conn.commit()
        cursor.close()
        conn.close()
