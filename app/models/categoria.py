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
            SELECT c.id_categoria, c.nombre_categoria, c.descripcion, c.imagen_url,
                   COUNT(DISTINCT pc.id_producto) AS total_productos
            FROM categorias c
            LEFT JOIN productos_categorias pc ON c.id_categoria = pc.id_categoria
            GROUP BY c.id_categoria, c.nombre_categoria, c.descripcion, c.imagen_url
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
    def crear(nombre_categoria, descripcion=None, imagen_url=None, imagen_public_id=None):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO categorias (nombre_categoria, descripcion, imagen_url, imagen_public_id) VALUES (%s, %s, %s, %s)",
            (nombre_categoria, descripcion, imagen_url, imagen_public_id)
        )
        conn.commit()
        nuevo_id = cursor.lastrowid
        cursor.close()
        conn.close()
        return nuevo_id

    @staticmethod
    def actualizar(id_categoria, nombre_categoria, descripcion=None, imagen_url=None, imagen_public_id=None):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE categorias
            SET nombre_categoria = %s, descripcion = %s, imagen_url = %s, imagen_public_id = %s
            WHERE id_categoria = %s
        """, (nombre_categoria, descripcion, imagen_url, imagen_public_id, id_categoria))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def eliminar(id_categoria):
        """
        Elimina una categoría y su imagen de Cloudinary si existe.
        """
        from app.utils.cloudinary_utils import delete_image
        
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            # Obtener el public_id de la imagen antes de eliminar
            cursor.execute("SELECT imagen_public_id FROM categorias WHERE id_categoria = %s", (id_categoria,))
            categoria = cursor.fetchone()
            
            # Eliminar imagen de Cloudinary si existe
            if categoria and categoria.get('imagen_public_id'):
                delete_image(categoria['imagen_public_id'])
            
            # Eliminar la categoría
            cursor.execute("DELETE FROM categorias WHERE id_categoria = %s", (id_categoria,))
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            conn.close()
