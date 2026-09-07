from app.utils.db import get_connection


class Carrito:
    @staticmethod
    def obtener_o_crear(id_usuario):
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM carritos WHERE id_usuario = %s", (id_usuario,))
        carrito = cursor.fetchone()

        if not carrito:
            cursor.execute("INSERT INTO carritos (id_usuario) VALUES (%s)", (id_usuario,))
            conn.commit()
            id_carrito = cursor.lastrowid
            carrito = {"id_carrito": id_carrito, "id_usuario": id_usuario}

        cursor.close()
        conn.close()
        return carrito

    @staticmethod
    def obtener_items(id_carrito):
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT ci.id_item, ci.cantidad, v.id_variante, v.presentacion,
                   v.precio, p.nombre_producto
            FROM carrito_items ci
            JOIN variantes_producto v ON ci.id_variante = v.id_variante
            JOIN productos p ON v.id_producto = p.id_producto
            WHERE ci.id_carrito = %s
        """, (id_carrito,))
        items = cursor.fetchall()
        cursor.close()
        conn.close()
        return items

    @staticmethod
    def vaciar(id_carrito):
        """Elimina todos los items del carrito tras confirmar un pedido."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM carrito_items WHERE id_carrito = %s", (id_carrito,))
        conn.commit()
        cursor.close()
        conn.close()


class CarritoItem:
    @staticmethod
    def obtener_cantidad(id_carrito, id_variante):
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT COALESCE(SUM(cantidad), 0) AS total
               FROM carrito_items
               WHERE id_carrito = %s AND id_variante = %s""",
            (id_carrito, id_variante),
        )
        fila = cursor.fetchone()
        cursor.close()
        conn.close()
        return int(fila["total"]) if fila else 0

    @staticmethod
    def agregar(id_carrito, id_variante, cantidad=1):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO carrito_items (id_carrito, id_variante, cantidad)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE cantidad = cantidad + %s
        """, (id_carrito, id_variante, cantidad, cantidad))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def eliminar(id_item):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM carrito_items WHERE id_item = %s", (id_item,))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def obtener_por_id(id_item):
        """Obtiene un item específico del carrito."""
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT ci.id_item, ci.id_carrito, ci.id_variante, ci.cantidad,
                   v.presentacion, v.precio, v.stock,
                   p.nombre_producto, p.activo
            FROM carrito_items ci
            JOIN variantes_producto v ON ci.id_variante = v.id_variante
            JOIN productos p ON v.id_producto = p.id_producto
            WHERE ci.id_item = %s
        """, (id_item,))
        item = cursor.fetchone()
        cursor.close()
        conn.close()
        return item

    @staticmethod
    def actualizar_cantidad(id_item, nueva_cantidad):
        """Actualiza la cantidad de un item en el carrito."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE carrito_items SET cantidad = %s WHERE id_item = %s",
            (nueva_cantidad, id_item)
        )
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def vaciar_por_carrito(id_carrito):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM carrito_items WHERE id_carrito = %s", (id_carrito,))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def contar_items(id_usuario):
        """Cuenta el total de items en el carrito de un usuario."""
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT COALESCE(SUM(ci.cantidad), 0) AS total
            FROM carrito_items ci
            JOIN carritos c ON ci.id_carrito = c.id_carrito
            WHERE c.id_usuario = %s
        """, (id_usuario,))
        fila = cursor.fetchone()
        cursor.close()
        conn.close()
        return int(fila["total"]) if fila else 0

