from app.utils.db import get_connection


class Producto:
    @staticmethod
    def listar_con_variantes(busqueda=None, categoria=None):
        """Devuelve productos activos junto con sus variantes (precio/stock) con filtros opcionales."""
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Primero obtener los IDs de productos que cumplen con los filtros
        product_query = """
            SELECT DISTINCT p.id_producto
            FROM productos p
            JOIN categorias c ON p.id_categoria = c.id_categoria
            JOIN variantes_producto v ON v.id_producto = p.id_producto
            WHERE p.activo = TRUE
        """
        params = []
        
        if busqueda:
            product_query += " AND (p.nombre_producto LIKE %s OR p.descripcion LIKE %s OR p.marca LIKE %s)"
            busqueda_param = f"%{busqueda}%"
            params.extend([busqueda_param, busqueda_param, busqueda_param])
        
        if categoria:
            product_query += " AND c.id_categoria = %s"
            params.append(categoria)
        
        cursor.execute(product_query, params)
        product_ids = [row['id_producto'] for row in cursor.fetchall()]
        
        if not product_ids:
            cursor.close()
            conn.close()
            return []
        
        # Ahora obtener todos los datos de esos productos con todas sus variantes
        placeholders = ','.join(['%s'] * len(product_ids))
        query = f"""
            SELECT p.id_producto, p.nombre_producto, p.descripcion, p.marca,
                   p.imagen_url, c.nombre_categoria, c.id_categoria,
                   v.id_variante, v.presentacion, v.precio, v.stock
            FROM productos p
            JOIN categorias c ON p.id_categoria = c.id_categoria
            JOIN variantes_producto v ON v.id_producto = p.id_producto
            WHERE p.id_producto IN ({placeholders})
            ORDER BY p.nombre_producto
        """
        
        cursor.execute(query, product_ids)
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
    def obtener_relacionados(id_producto, id_categoria, limite=4):
        """Obtiene productos activos de la misma categoría, excluyendo el producto actual."""
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT p.id_producto, p.nombre_producto, p.descripcion, p.marca, p.imagen_url,
                   c.nombre_categoria,
                   MIN(v.precio) AS precio_minimo
            FROM productos p
            LEFT JOIN categorias c ON p.id_categoria = c.id_categoria
            LEFT JOIN variantes_producto v ON p.id_producto = v.id_producto
            WHERE p.id_producto != %s 
              AND p.id_categoria = %s 
              AND p.activo = TRUE
            GROUP BY p.id_producto, p.nombre_producto, p.descripcion, p.marca, p.imagen_url, c.nombre_categoria
            ORDER BY RAND()
            LIMIT %s
        """, (id_producto, id_categoria, limite))
        productos = cursor.fetchall()
        cursor.close()
        conn.close()
        return productos

    @staticmethod
    def crear(id_categoria, nombre_producto, descripcion, marca, imagen_url=None, imagen_public_id=None):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO productos (id_categoria, nombre_producto, descripcion, marca, imagen_url, imagen_public_id)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (id_categoria, nombre_producto, descripcion, marca, imagen_url, imagen_public_id)
        )
        conn.commit()
        nuevo_id = cursor.lastrowid
        cursor.close()
        conn.close()
        return nuevo_id

    @staticmethod
    def actualizar(id_producto, id_categoria, nombre_producto, descripcion, marca, imagen_url=None, imagen_public_id=None, activo=1):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE productos
            SET id_categoria = %s, nombre_producto = %s, descripcion = %s,
                marca = %s, imagen_url = %s, imagen_public_id = %s, activo = %s
            WHERE id_producto = %s
        """, (id_categoria, nombre_producto, descripcion, marca, imagen_url, imagen_public_id, activo, id_producto))
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
        """
        Elimina un producto solo si no tiene pedidos activos.
        Permite eliminar si todos los pedidos están en estados finales (entregado o cancelado).
        También elimina la imagen de Cloudinary si existe.
        """
        from app.utils.cloudinary_utils import delete_image
        
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            # Verificar si el producto tiene pedidos activos
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
            
            # Obtener el public_id de la imagen antes de eliminar
            cursor.execute("SELECT imagen_public_id FROM productos WHERE id_producto = %s", (id_producto,))
            producto = cursor.fetchone()
            
            # Eliminar imagen de Cloudinary si existe
            if producto and producto.get('imagen_public_id'):
                delete_image(producto['imagen_public_id'])
            
            # Si no hay pedidos activos, proceder con la eliminación
            cursor.execute("DELETE FROM productos WHERE id_producto = %s", (id_producto,))
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
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
    def crear(id_producto, presentacion, precio, stock, sku=None, stock_minimo=5):
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
        """Descuenta una cantidad específica del stock de una variante."""
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
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM variantes_producto WHERE id_variante = %s", (id_variante,))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def obtener_inventario(filtro_bajo=None, busqueda=None, id_categoria=None, estado_stock=None):
        """
        Obtiene el inventario completo con alertas de stock bajo y filtros avanzados.

        Args:
            filtro_bajo: Si es True, solo retorna items con stock bajo
            busqueda: Texto para buscar en nombre, marca, presentacion o SKU
            id_categoria: Filtrar por categoría específica
            estado_stock: Filtrar por estado de stock ('agotado', 'bajo', 'normal')

        Returns:
            Lista de variantes con información de stock y alertas
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT v.id_variante, v.id_producto, v.presentacion, v.precio, v.stock, v.stock_minimo, v.sku,
                   p.nombre_producto, p.marca, c.nombre_categoria, c.id_categoria,
                   CASE
                       WHEN v.stock = 0 THEN 'agotado'
                       WHEN v.stock <= v.stock_minimo THEN 'bajo'
                       ELSE 'normal'
                   END AS estado_stock
            FROM variantes_producto v
            JOIN productos p ON v.id_producto = p.id_producto
            JOIN categorias c ON p.id_categoria = c.id_categoria
            WHERE p.activo = TRUE
        """
        params = []

        if filtro_bajo:
            query += " AND v.stock <= v.stock_minimo"

        if busqueda:
            query += " AND (p.nombre_producto LIKE %s OR p.marca LIKE %s OR v.presentacion LIKE %s OR v.sku LIKE %s)"
            busqueda_param = f"%{busqueda}%"
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

        query += " ORDER BY v.stock ASC, p.nombre_producto ASC"

        cursor.execute(query, params)
        inventario = cursor.fetchall()
        cursor.close()
        conn.close()
        return inventario

    @staticmethod
    def obtener_alertas_stock():
        """
        Obtiene items que requieren atención por stock bajo o agotado.
        
        Returns:
            Dict con 'agotados' y 'bajo' como listas
        """
        inventario = VarianteProducto.obtener_inventario(filtro_bajo=True)
        
        alertas = {
            'agotados': [item for item in inventario if item['stock'] == 0],
            'bajo': [item for item in inventario if item['stock'] > 0 and item['stock'] <= item['stock_minimo']]
        }
        
        return alertas
