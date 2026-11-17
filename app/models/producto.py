"""
Modelo de Productos - Gestión de productos y sus variantes.

Este módulo maneja la lógica de negocio para productos (`productos`), su
asociación muchos-a-muchos con categorías (`productos_categorias`) y sus
variantes comerciales (`variantes_producto`) con diferentes precios,
presentaciones, SKU y control de inventario.
"""

# Utilidades matemáticas para detectar valores especiales (NaN, Inf) en precios
import math
# Expresiones regulares para validar estrictamente formatos de precio y enteros
import re
# Tipo Decimal para validar precios exactos sin pérdida de precisión
from decimal import Decimal
# Función para obtener una conexión activa a MySQL
from app.utils.db import get_connection

# Patrón que acepta enteros o decimales positivos con hasta 2 cifras decimales
REGEX_PRECIO = re.compile(r"^\d+(\.\d{1,2})?$")
# Patrón que acepta únicamente dígitos enteros no negativos
REGEX_ENTERO = re.compile(r"^\d+$")


class Producto:
    """
    Modelo principal para la gestión de productos del catálogo.
    """

    @staticmethod
    def listar_con_variantes(busqueda=None, categoria=None):
        """
        Devuelve productos activos junto con sus variantes (precio/stock) con filtros opcionales.

        Se ejecuta en dos consultas: primero obtiene los IDs de productos que cumplen
        los filtros y luego recupera todas sus variantes para no perder presentaciones
        hermanas cuando se filtra.

        Args:
            busqueda (str, optional): Texto para buscar en nombre, descripción o marca.
            categoria (int | str, optional): ID de categoría para filtrar productos.

        Returns:
            list[dict]: Lista de diccionarios con información de productos y sus variantes.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            # Primero obtener los IDs de productos activos que cumplen con los filtros
            product_query = """
                SELECT DISTINCT p.id_producto
                FROM productos p
                LEFT JOIN productos_categorias pc ON p.id_producto = pc.id_producto
                LEFT JOIN categorias c ON pc.id_categoria = c.id_categoria
                JOIN variantes_producto v ON v.id_producto = p.id_producto
                WHERE p.activo = TRUE
            """
            params = []

            # Normaliza el texto de búsqueda y escapa comodines LIKE (\, %, _)
            busqueda_limpia = busqueda.strip() if isinstance(busqueda, str) else ""
            if busqueda_limpia:
                busqueda_escapada = (
                    busqueda_limpia
                    .replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_")
                )
                # Búsqueda parcial insensible a mayúsculas en nombre, descripción, marca, categoría y presentación
                product_query += (
                    " AND (p.nombre_producto LIKE %s ESCAPE '\\\\'"
                    " OR p.descripcion LIKE %s ESCAPE '\\\\'"
                    " OR p.marca LIKE %s ESCAPE '\\\\'"
                    " OR c.nombre_categoria LIKE %s ESCAPE '\\\\'"
                    " OR v.presentacion LIKE %s ESCAPE '\\\\')"
                )
                busqueda_param = f"%{busqueda_escapada}%"
                params.extend([busqueda_param] * 5)

            if categoria:
                product_query += " AND c.id_categoria = %s"
                params.append(categoria)

            cursor.execute(product_query, params)
            product_ids = [row['id_producto'] for row in cursor.fetchall()]

            # Si ningún producto coincide, retornar lista vacía sin ejecutar la segunda consulta
            if not product_ids:
                return []

            # Ahora obtener todos los datos de esos productos con todas sus variantes
            placeholders = ','.join(['%s'] * len(product_ids))
            query = f"""
                SELECT p.id_producto, p.nombre_producto, p.descripcion, p.marca,
                       p.imagen_url, GROUP_CONCAT(DISTINCT c.nombre_categoria) AS categorias,
                       GROUP_CONCAT(DISTINCT c.id_categoria) AS categoria_ids,
                       v.id_variante, v.presentacion, v.precio, v.stock
                FROM productos p
                LEFT JOIN productos_categorias pc ON p.id_producto = pc.id_producto
                LEFT JOIN categorias c ON pc.id_categoria = c.id_categoria
                JOIN variantes_producto v ON v.id_producto = p.id_producto
                WHERE p.id_producto IN ({placeholders})
                GROUP BY p.id_producto, p.nombre_producto, p.descripcion, p.marca,
                         p.imagen_url, v.id_variante, v.presentacion, v.precio, v.stock
                ORDER BY p.nombre_producto
            """

            cursor.execute(query, product_ids)
            filas = cursor.fetchall()
            return filas
        finally:
            # Garantiza el cierre de cursor y conexión incluso si ocurre un error SQL
            cursor.close()
            conn.close()

    @staticmethod
    def listar_admin():
        """
        Lista todos los productos (activos e inactivos) para el panel de administración,
        incluyendo conteo de variantes, stock acumulado y rango de precios.

        Returns:
            list[dict]: Lista de productos ordenados del más reciente al más antiguo.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT p.id_producto, p.nombre_producto, p.descripcion, p.marca,
                   p.imagen_url, p.activo, p.fecha_creacion,
                   GROUP_CONCAT(DISTINCT c.nombre_categoria) AS categorias,
                   GROUP_CONCAT(DISTINCT c.id_categoria) AS categoria_ids,
                   COUNT(v.id_variante) AS total_variantes,
                   COALESCE(SUM(v.stock), 0) AS stock_total,
                   MIN(v.precio) AS precio_minimo,
                   MAX(v.precio) AS precio_maximo
            FROM productos p
            LEFT JOIN productos_categorias pc ON p.id_producto = pc.id_producto
            LEFT JOIN categorias c ON pc.id_categoria = c.id_categoria
            LEFT JOIN variantes_producto v ON v.id_producto = p.id_producto
            GROUP BY p.id_producto, p.nombre_producto, p.descripcion, p.marca,
                     p.imagen_url, p.activo, p.fecha_creacion
            ORDER BY p.id_producto DESC
        """)
        filas = cursor.fetchall()
        cursor.close()
        conn.close()
        return filas

    @staticmethod
    def obtener_por_id(id_producto):
        """
        Obtiene un producto por su ID junto con sus categorías concatenadas.

        Args:
            id_producto (int): ID del producto.

        Returns:
            dict | None: Diccionario con los datos del producto o None si no existe.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT p.*, GROUP_CONCAT(DISTINCT c.nombre_categoria) AS categorias,
                   GROUP_CONCAT(DISTINCT c.id_categoria) AS categoria_ids
            FROM productos p
            LEFT JOIN productos_categorias pc ON p.id_producto = pc.id_producto
            LEFT JOIN categorias c ON pc.id_categoria = c.id_categoria
            WHERE p.id_producto = %s
            GROUP BY p.id_producto
        """, (id_producto,))
        producto = cursor.fetchone()
        cursor.close()
        conn.close()
        return producto

    @staticmethod
    def obtener_categorias(id_producto):
        """
        Obtiene todas las categorías asociadas a un producto.

        Args:
            id_producto (int): ID del producto.

        Returns:
            list[dict]: Lista de categorías ordenadas alfabéticamente.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT c.id_categoria, c.nombre_categoria, c.descripcion, c.imagen_url
            FROM categorias c
            JOIN productos_categorias pc ON c.id_categoria = pc.id_categoria
            WHERE pc.id_producto = %s
            ORDER BY c.nombre_categoria
        """, (id_producto,))
        categorias = cursor.fetchall()
        cursor.close()
        conn.close()
        return categorias

    @staticmethod
    def agregar_categoria(id_producto, id_categoria):
        """
        Asocia una categoría a un producto en la tabla pivote `productos_categorias`.

        Args:
            id_producto (int): ID del producto.
            id_categoria (int): ID de la categoría a vincular.
        """
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO productos_categorias (id_producto, id_categoria) VALUES (%s, %s)",
                (id_producto, id_categoria)
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def eliminar_categoria(id_producto, id_categoria):
        """
        Desvincula una categoría de un producto.

        Args:
            id_producto (int): ID del producto.
            id_categoria (int): ID de la categoría a desvincular.
        """
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM productos_categorias WHERE id_producto = %s AND id_categoria = %s",
            (id_producto, id_categoria)
        )
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def actualizar_categorias(id_producto, lista_categorias):
        """
        Reemplaza completamente las categorías asociadas a un producto de forma atómica.

        Args:
            id_producto (int): ID del producto.
            lista_categorias (list[int]): Nueva lista de IDs de categoría.
        """
        conn = get_connection()
        cursor = conn.cursor()
        try:
            # Eliminar asociaciones previas antes de insertar las nuevas
            cursor.execute("DELETE FROM productos_categorias WHERE id_producto = %s", (id_producto,))

            for id_categoria in lista_categorias:
                cursor.execute(
                    "INSERT INTO productos_categorias (id_producto, id_categoria) VALUES (%s, %s)",
                    (id_producto, id_categoria)
                )

            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def obtener_relacionados(id_producto, id_categoria, limite=4):
        """
        Obtiene productos activos aleatorios de la misma categoría, excluyendo el producto actual.

        Args:
            id_producto (int): ID del producto actual (excluido del resultado).
            id_categoria (int): ID de la categoría compartida.
            limite (int, optional): Cantidad máxima de productos relacionados. Por defecto 4.

        Returns:
            list[dict]: Lista de productos relacionados con su precio mínimo.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT p.id_producto, p.nombre_producto, p.descripcion, p.marca, p.imagen_url,
                   GROUP_CONCAT(DISTINCT c.nombre_categoria) AS categorias,
                   MIN(v.precio) AS precio_minimo
            FROM productos p
            LEFT JOIN productos_categorias pc ON p.id_producto = pc.id_producto
            LEFT JOIN categorias c ON pc.id_categoria = c.id_categoria
            LEFT JOIN variantes_producto v ON p.id_producto = v.id_producto
            WHERE p.id_producto != %s
              AND pc.id_categoria = %s
              AND p.activo = TRUE
            GROUP BY p.id_producto, p.nombre_producto, p.descripcion, p.marca, p.imagen_url
            ORDER BY RAND()
            LIMIT %s
        """, (id_producto, id_categoria, limite))
        productos = cursor.fetchall()
        cursor.close()
        conn.close()
        return productos

    @staticmethod
    def crear(nombre_producto, descripcion, marca, imagen_url=None, lista_categorias=None, imagen_public_id=None):
        """
        Crea un nuevo producto en la base de datos con ID generado automáticamente.

        Args:
            nombre_producto (str): Nombre del producto.
            descripcion (str): Descripción detallada (máximo 100 caracteres; se trunca si excede).
            marca (str): Marca del producto.
            imagen_url (str, optional): URL de la imagen en Cloudinary.
            lista_categorias (list[int], optional): Lista de IDs de categorías.
            imagen_public_id (str, optional): ID público de Cloudinary para la imagen.

        Returns:
            int: ID del producto creado (generado automáticamente por AUTO_INCREMENT).

        Raises:
            ValueError: Si no se pudo generar un ID válido.
        """
        # Validar y truncar la descripción a un máximo de 100 caracteres
        if descripcion and len(descripcion) > 100:
            descripcion = descripcion[:100]
        
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """INSERT INTO productos (nombre_producto, descripcion, marca, imagen_url, imagen_public_id)
                   VALUES (%s, %s, %s, %s, %s)""",
                (nombre_producto, descripcion, marca, imagen_url, imagen_public_id)
            )
            nuevo_id = cursor.lastrowid

            # Verificar que el ID se generó correctamente
            if nuevo_id is None or nuevo_id <= 0:
                raise ValueError("No se pudo generar el ID del producto automaticamente")

            # Insertar categorías asociadas si se proporcionaron
            if lista_categorias:
                for id_categoria in lista_categorias:
                    cursor.execute(
                        "INSERT INTO productos_categorias (id_producto, id_categoria) VALUES (%s, %s)",
                        (nuevo_id, id_categoria)
                    )

            conn.commit()
            return nuevo_id
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def actualizar(id_producto, nombre_producto, descripcion, marca, imagen_url=None, activo=1, lista_categorias=None, imagen_public_id=None):
        """
        Actualiza los datos de un producto y, opcionalmente, reemplaza sus categorías.

        Args:
            id_producto (int): ID del producto a modificar.
            nombre_producto (str): Nuevo nombre.
            descripcion (str): Nueva descripción.
            marca (str): Nueva marca.
            imagen_url (str, optional): Nueva URL de imagen.
            activo (int | bool, optional): Estado de activación. Por defecto 1.
            lista_categorias (list[int], optional): Si no es None, reemplaza las categorías.
            imagen_public_id (str, optional): Nuevo public_id de Cloudinary.
        """
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE productos
                SET nombre_producto = %s, descripcion = %s,
                    marca = %s, imagen_url = %s, imagen_public_id = %s, activo = %s
                WHERE id_producto = %s
            """, (nombre_producto, descripcion, marca, imagen_url, imagen_public_id, activo, id_producto))

            # Solo actualizar categorías cuando se recibe explícitamente una lista (incluso vacía)
            if lista_categorias is not None:
                cursor.execute("DELETE FROM productos_categorias WHERE id_producto = %s", (id_producto,))
                for id_categoria in lista_categorias:
                    cursor.execute(
                        "INSERT INTO productos_categorias (id_producto, id_categoria) VALUES (%s, %s)",
                        (id_producto, id_categoria)
                    )

            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def toggle_activo(id_producto):
        """
        Alterna el estado `activo` de un producto (activo <-> inactivo).

        Args:
            id_producto (int): ID del producto a conmutar.
        """
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE productos SET activo = NOT activo WHERE id_producto = %s", (id_producto,))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def eliminar(id_producto):
        """
        Elimina un producto solo si no tiene pedidos activos (estados 1, 2 o 3).
        Permite eliminar si todos los pedidos están en estados finales (entregado o cancelado).
        También elimina la imagen de Cloudinary si existe.

        Args:
            id_producto (int): ID del producto a eliminar.

        Raises:
            ValueError: Si el producto tiene pedidos activos asociados.
        """
        from app.utils.cloudinary_utils import delete_image

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            # Verificar que ninguna variante del producto esté en pedidos en curso (1=pendiente, 2=confirmado, 3=en camino)
            cursor.execute("""
                SELECT COUNT(*) as total_pedidos
                FROM pedido_detalle pd
                JOIN pedidos p ON pd.id_pedido = p.id_pedido
                JOIN variantes_producto v ON pd.id_variante = v.id_variante
                WHERE v.id_producto = %s AND p.id_estado IN (1, 2, 3)
            """, (id_producto,))

            resultado = cursor.fetchone()
            pedidos_activos = resultado["total_pedidos"]

            if pedidos_activos > 0:
                raise ValueError(f"El producto tiene {pedidos_activos} pedido(s) activo(s) y no puede ser eliminado")

            # Recuperar el public_id de Cloudinary antes de borrar la fila
            cursor.execute("SELECT imagen_public_id FROM productos WHERE id_producto = %s", (id_producto,))
            producto = cursor.fetchone()

            if producto and producto.get('imagen_public_id'):
                delete_image(producto['imagen_public_id'])

            cursor.execute("DELETE FROM productos WHERE id_producto = %s", (id_producto,))
            conn.commit()

        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            conn.close()


class VarianteProducto:
    """
    Modelo para las variantes/presentaciones comerciales de un producto
    (tabla `variantes_producto`), incluyendo validaciones numéricas y consultas
    de inventario.
    """

    @staticmethod
    def listar_por_producto(id_producto):
        """
        Lista todas las variantes de un producto ordenadas por su ID.

        Args:
            id_producto (int): ID del producto padre.

        Returns:
            list[dict]: Lista de variantes asociadas.
        """
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
        """
        Obtiene una variante específica por su ID.

        Args:
            id_variante (int): ID de la variante.

        Returns:
            dict | None: Diccionario con los datos de la variante o None si no existe.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM variantes_producto WHERE id_variante = %s", (id_variante,))
        variante = cursor.fetchone()
        cursor.close()
        conn.close()
        return variante

    @staticmethod
    def _validar_precio(precio):
        """
        Valida que el precio sea un número positivo finito con máximo 2 decimales.

        Args:
            precio (int | float | Decimal | str): Precio a validar.

        Returns:
            float: Precio validado convertido a float.

        Raises:
            ValueError: Si el precio es nulo, booleano, NaN, infinito, <= 0 o formato inválido.
        """
        # Rechazar None y booleanos (en Python `isinstance(True, int)` es True)
        if precio is None or isinstance(precio, bool):
            raise ValueError("El precio debe ser mayor a cero")
        if isinstance(precio, float):
            if math.isnan(precio) or math.isinf(precio) or precio <= 0:
                raise ValueError("El precio debe ser mayor a cero")
            texto = str(int(precio)) if precio.is_integer() else str(precio)
        elif isinstance(precio, Decimal):
            if precio.is_nan() or precio.is_infinite() or precio <= 0:
                raise ValueError("El precio debe ser mayor a cero")
            texto = format(precio, "f")
        else:
            texto = str(precio).strip()

        # Verificar formato estricto de dígitos con máximo 2 decimales
        if not REGEX_PRECIO.match(texto):
            raise ValueError("El precio debe ser mayor a cero")

        valor = float(texto)
        if valor <= 0:
            raise ValueError("El precio debe ser mayor a cero")
        return valor

    @staticmethod
    def _validar_entero_no_negativo(valor, mensaje_error):
        """
        Valida que un valor represente un número entero >= 0.

        Args:
            valor (int | str): Valor a validar.
            mensaje_error (str): Mensaje de error si la validación falla.

        Returns:
            int: Entero no negativo validado.

        Raises:
            ValueError: Si el valor es inválido o negativo.
        """
        if valor is None or isinstance(valor, bool):
            raise ValueError(mensaje_error)
        texto = valor.strip() if isinstance(valor, str) else str(valor)
        if not REGEX_ENTERO.match(texto):
            raise ValueError(mensaje_error)
        return int(texto)

    @staticmethod
    def crear(id_producto, presentacion, precio, stock, sku=None, stock_minimo=5):
        """
        Crea una nueva variante de producto con validaciones de formato numérico y valores positivos.

        Args:
            id_producto (int): ID del producto padre.
            presentacion (str): Descripción de la presentación (ej. "330 ml", "Six-Pack").
            precio (float | Decimal | str): Precio de venta (> 0).
            stock (int | str): Cantidad inicial en inventario (>= 0).
            sku (str, optional): Código SKU único.
            stock_minimo (int | str, optional): Umbral de alerta de stock bajo. Por defecto 5.

        Returns:
            int: ID autogenerado de la nueva variante.
        """
        stock = VarianteProducto._validar_entero_no_negativo(stock, "El stock no puede ser negativo")
        stock_minimo = VarianteProducto._validar_entero_no_negativo(stock_minimo, "El stock minimo no puede ser negativo")
        precio = VarianteProducto._validar_precio(precio)
        
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO variantes_producto (id_producto, presentacion, precio, stock, sku, stock_minimo)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (id_producto, presentacion, precio, stock, sku, stock_minimo)
        )
        conn.commit()
        nuevo_id = cursor.lastrowid
        cursor.close()
        conn.close()
        return nuevo_id

    @staticmethod
    def actualizar(id_variante, presentacion, precio, stock, sku=None, stock_minimo=5):
        """
        Actualiza una variante existente aplicando las mismas validaciones que `crear()`.

        Args:
            id_variante (int): ID de la variante a modificar.
            presentacion (str): Nueva presentación.
            precio (float | Decimal | str): Nuevo precio (> 0).
            stock (int | str): Nuevo stock (>= 0).
            sku (str, optional): Nuevo código SKU.
            stock_minimo (int | str, optional): Nuevo umbral de stock mínimo.
        """
        stock = VarianteProducto._validar_entero_no_negativo(stock, "El stock no puede ser negativo")
        stock_minimo = VarianteProducto._validar_entero_no_negativo(stock_minimo, "El stock minimo no puede ser negativo")
        precio = VarianteProducto._validar_precio(precio)

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE variantes_producto
            SET presentacion = %s, precio = %s, stock = %s, sku = %s, stock_minimo = %s
            WHERE id_variante = %s
        """, (presentacion, precio, stock, sku, stock_minimo, id_variante))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def actualizar_stock(id_variante, nueva_cantidad):
        """
        Establece un nuevo valor absoluto de stock para una variante.

        Args:
            id_variante (int): ID de la variante.
            nueva_cantidad (int | str): Nueva cantidad en inventario (>= 0).
        """
        nueva_cantidad = VarianteProducto._validar_entero_no_negativo(
            nueva_cantidad, "El stock no puede ser negativo"
        )
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
    def descontar_stock(id_variante, cantidad):
        """
        Descuenta de forma atómica una cantidad específica del stock de una variante,
        solo si existe inventario suficiente (`stock >= cantidad`).

        Args:
            id_variante (int): ID de la variante.
            cantidad (int): Unidades a descontar.

        Returns:
            bool: True si se descontó el stock, False si no había suficiente stock.
        """
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE variantes_producto SET stock = stock - %s WHERE id_variante = %s AND stock >= %s",
            (cantidad, id_variante, cantidad)
        )
        conn.commit()
        affected_rows = cursor.rowcount
        cursor.close()
        conn.close()
        return affected_rows > 0

    @staticmethod
    def eliminar(id_variante):
        """
        Elimina una variante de producto por su ID.

        Args:
            id_variante (int): ID de la variante a eliminar.
        """
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM variantes_producto WHERE id_variante = %s", (id_variante,))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def obtener_inventario(filtro_bajo=None, busqueda=None, id_categoria=None, estado_stock=None, ordenar_por=None):
        """
        Obtiene el inventario completo de productos activos con alertas de stock bajo
        y soporte para múltiples filtros y criterios de ordenamiento.

        Args:
            filtro_bajo (bool, optional): Si es True, solo retorna ítems con stock <= stock_minimo.
            busqueda (str, optional): Texto para buscar en nombre, marca, presentación o SKU.
            id_categoria (int, optional): Filtrar por categoría específica.
            estado_stock (str, optional): Filtrar por estado (`'agotado'`, `'bajo'`, `'normal'`).
            ordenar_por (str, optional): Criterio (`'nombre_asc'`, `'nombre_desc'`, `'reciente'`,
                `'antiguo'`, `'stock_asc'`, `'stock_desc'`).

        Returns:
            list[dict]: Lista de variantes con información de stock y columna `estado_stock`.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # Calcular estado_stock en SQL mediante CASE para clasificar agotado/bajo/normal
        query = """
            SELECT v.id_variante, v.id_producto, v.presentacion, v.precio, v.stock, v.stock_minimo, v.sku,
                   p.nombre_producto, p.marca, GROUP_CONCAT(DISTINCT c.nombre_categoria) AS categorias, p.fecha_creacion,
                   CASE
                       WHEN v.stock = 0 THEN 'agotado'
                       WHEN v.stock <= v.stock_minimo THEN 'bajo'
                       ELSE 'normal'
                   END AS estado_stock
            FROM variantes_producto v
            JOIN productos p ON v.id_producto = p.id_producto
            LEFT JOIN productos_categorias pc ON p.id_producto = pc.id_producto
            LEFT JOIN categorias c ON pc.id_categoria = c.id_categoria
            WHERE p.activo = TRUE
        """
        params = []

        if filtro_bajo:
            query += " AND v.stock <= v.stock_minimo"

        if busqueda:
            # Cada palabra debe coincidir en al menos uno de los campos buscados
            palabras = busqueda.split()
            for palabra in palabras:
                query += " AND (p.nombre_producto LIKE %s OR p.marca LIKE %s OR v.presentacion LIKE %s OR v.sku LIKE %s)"
                busqueda_param = f"%{palabra}%"
                params.extend([busqueda_param, busqueda_param, busqueda_param, busqueda_param])

        if id_categoria:
            query += " AND c.id_categoria = %s"
            params.append(id_categoria)

        if estado_stock:
            if estado_stock == 'agotado':
                query += " AND v.stock = 0"
            elif estado_stock == 'bajo':
                query += " AND v.stock > 0 AND v.stock <= v.stock_minimo"
            elif estado_stock == 'normal':
                query += " AND v.stock > v.stock_minimo"

        query += """
            GROUP BY v.id_variante, v.id_producto, v.presentacion, v.precio, v.stock, v.stock_minimo, v.sku,
                     p.nombre_producto, p.marca, p.fecha_creacion
        """

        # Aplicar ordenamiento seguro mediante mapeo explícito (sin interpolar entrada del usuario)
        if ordenar_por == 'nombre_asc':
            query += " ORDER BY p.nombre_producto ASC"
        elif ordenar_por == 'nombre_desc':
            query += " ORDER BY p.nombre_producto DESC"
        elif ordenar_por == 'reciente':
            query += " ORDER BY p.fecha_creacion DESC"
        elif ordenar_por == 'antiguo':
            query += " ORDER BY p.fecha_creacion ASC"
        elif ordenar_por == 'stock_asc':
            query += " ORDER BY v.stock ASC"
        elif ordenar_por == 'stock_desc':
            query += " ORDER BY v.stock DESC"
        else:
            query += " ORDER BY v.stock ASC, p.nombre_producto ASC"

        cursor.execute(query, params)
        inventario = cursor.fetchall()
        cursor.close()
        conn.close()
        return inventario

    @staticmethod
    def obtener_alertas_stock():
        """
        Obtiene ítems que requieren atención por stock bajo o agotado,
        clasificados en dos listas separadas.

        Returns:
            dict: Diccionario con claves `'agotados'` (stock == 0) y `'bajo'` (0 < stock <= stock_minimo).
        """
        inventario = VarianteProducto.obtener_inventario(filtro_bajo=True)

        alertas = {
            'agotados': [item for item in inventario if item['stock'] == 0],
            'bajo': [item for item in inventario if item['stock'] > 0 and item['stock'] <= item['stock_minimo']]
        }

        return alertas
