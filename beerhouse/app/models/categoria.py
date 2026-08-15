from app.utils.db import get_connection


class Categoria:
    @staticmethod
    def listar():
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM categorias ORDER BY nombre_categoria ASC")
        categorias = cursor.fetchall()
        cursor.close()
        conn.close()
        return categorias

    @staticmethod
    def listar_con_conteo():
        """Lista categorías junto con la cantidad de productos asociados."""
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT c.id_categoria, c.nombre_categoria, c.descripcion,
                   COUNT(p.id_producto) AS total_productos
            FROM categorias c
            LEFT JOIN productos p ON c.id_categoria = p.id_categoria
            GROUP BY c.id_categoria, c.nombre_categoria, c.descripcion
            ORDER BY c.nombre_categoria ASC
        """)
        categorias = cursor.fetchall()
        cursor.close()
        conn.close()
        return categorias

    @staticmethod
    def obtener_por_id(id_categoria):
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM categorias WHERE id_categoria = %s", (id_categoria,))
        categoria = cursor.fetchone()
        cursor.close()
        conn.close()
        return categoria

    @staticmethod
    def crear(nombre_categoria, descripcion=None):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO categorias (nombre_categoria, descripcion) VALUES (%s, %s)",
            (nombre_categoria, descripcion)
        )
        conn.commit()
        nuevo_id = cursor.lastrowid
        cursor.close()
        conn.close()
        return nuevo_id

    @staticmethod
    def actualizar(id_categoria, nombre_categoria, descripcion=None):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE categorias
            SET nombre_categoria = %s, descripcion = %s
            WHERE id_categoria = %s
        """, (nombre_categoria, descripcion, id_categoria))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def eliminar(id_categoria):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM categorias WHERE id_categoria = %s", (id_categoria,))
        conn.commit()
        cursor.close()
        conn.close()
