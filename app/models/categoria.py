"""
Modelo de Categorías.

Este módulo gestiona las operaciones CRUD sobre la tabla `categorias` y la
limpieza de imágenes asociadas en Cloudinary cuando se elimina una categoría.
"""

# Función para obtener una conexión activa a MySQL
from app.utils.db import get_connection


class Categoria:
    """
    Modelo para administrar las categorías de productos del catálogo.
    """

    @staticmethod
    def listar():
        """
        Obtiene todas las categorías ordenadas alfabéticamente por nombre.

        Returns:
            list[dict]: Lista de diccionarios con todas las columnas de `categorias`.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        # Consultar todas las categorías ordenadas ascendentemente
        cursor.execute("SELECT * FROM categorias ORDER BY nombre_categoria ASC")
        categorias = cursor.fetchall()
        cursor.close()
        conn.close()
        return categorias

    @staticmethod
    def listar_con_conteo():
        """
        Lista todas las categorías junto con la cantidad de productos asociados.

        Returns:
            list[dict]: Lista de categorías con el campo adicional `total_productos`.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        # LEFT JOIN con la tabla pivote para incluir categorías sin productos (conteo 0)
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
        """
        Busca una categoría específica por su identificador único.

        Args:
            id_categoria (int): ID de la categoría.

        Returns:
            dict | None: Diccionario con los datos de la categoría o None si no existe.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM categorias WHERE id_categoria = %s", (id_categoria,))
        categoria = cursor.fetchone()
        cursor.close()
        conn.close()
        return categoria

    @staticmethod
    def crear(nombre_categoria, descripcion=None, imagen_url=None, imagen_public_id=None):
        """
        Crea una nueva categoría en la base de datos.

        Args:
            nombre_categoria (str): Nombre de la categoría.
            descripcion (str, optional): Descripción breve.
            imagen_url (str, optional): URL pública de la imagen en Cloudinary.
            imagen_public_id (str, optional): Identificador público en Cloudinary.

        Returns:
            int: ID autogenerado de la categoría recién creada.
        """
        conn = get_connection()
        cursor = conn.cursor()
        # Insertar registro de categoría con parámetros seguros (evita inyección SQL)
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
        """
        Actualiza los datos e imagen de una categoría existente.

        Args:
            id_categoria (int): ID de la categoría a modificar.
            nombre_categoria (str): Nuevo nombre de la categoría.
            descripcion (str, optional): Nueva descripción.
            imagen_url (str, optional): Nueva URL de imagen.
            imagen_public_id (str, optional): Nuevo public_id de Cloudinary.
        """
        conn = get_connection()
        cursor = conn.cursor()
        # Actualizar todos los campos editables de la categoría
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

        Args:
            id_categoria (int): ID de la categoría a eliminar.

        Raises:
            Exception: Propaga cualquier error ocurrido durante la eliminación
                tras revertir la transacción.
        """
        # Importación local para evitar dependencias circulares al cargar módulos
        from app.utils.cloudinary_utils import delete_image
        
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            # Obtener el public_id de la imagen antes de eliminar el registro
            cursor.execute("SELECT imagen_public_id FROM categorias WHERE id_categoria = %s", (id_categoria,))
            categoria = cursor.fetchone()
            
            # Eliminar imagen de Cloudinary si existe un public_id asociado
            if categoria and categoria.get('imagen_public_id'):
                delete_image(categoria['imagen_public_id'])
            
            # Eliminar la categoría de la base de datos
            cursor.execute("DELETE FROM categorias WHERE id_categoria = %s", (id_categoria,))
            conn.commit()
            
        except Exception as e:
            # Revertir cambios en BD ante cualquier fallo
            conn.rollback()
            raise e
        finally:
            # Garantizar el cierre de cursor y conexión incluso si ocurre una excepción
            cursor.close()
            conn.close()
