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
            LEFT JOIN productos_categorias pc ON p.id_producto = pc.id_producto
            LEFT JOIN categorias c ON pc.id_categoria = c.id_categoria
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
        """Obtiene todas las categorías de un producto."""
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
        """Agrega una categoría a un producto."""
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
        """Elimina una categoría de un producto."""
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
        """Actualiza las categorías de un producto (reemplaza todas)."""
        conn = get_connection()
        cursor = conn.cursor()
        try:
            # Eliminar todas las categorías actuales
            cursor.execute("DELETE FROM productos_categorias WHERE id_producto = %s", (id_producto,))
            
            # Agregar las nuevas categorías
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
        """Obtiene productos activos de la misma categoría, excluyendo el producto actual."""
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
    def crear(nombre_producto, descripcion, marca, imagen_url=None, lista_categorias=None):
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """INSERT INTO productos (nombre_producto, descripcion, marca, imagen_url)
                   VALUES (%s, %s, %s, %s)""",
                (nombre_producto, descripcion, marca, imagen_url)
            )
            nuevo_id = cursor.lastrowid
            
            # Si se proporcionan categorías, agregarlas
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
    def actualizar(id_producto, nombre_producto, descripcion, marca, imagen_url=None, activo=1, lista_categorias=None):
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE productos
                SET nombre_producto = %s, descripcion = %s,
                    marca = %s, imagen_url = %s, activo = %s
                WHERE id_producto = %s
            """, (nombre_producto, descripcion, marca, imagen_url, activo, id_producto))
            
            # Si se proporcionan categorías, actualizarlas
            if lista_categorias is not None:
                # Eliminar todas las categorías actuales
                cursor.execute("DELETE FROM productos_categorias WHERE id_producto = %s", (id_producto,))
                
                # Agregar las nuevas categorías
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
        """
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
    def obtener_inventario(filtro_bajo=None):
        """
        Obtiene el inventario completo con alertas de stock bajo.
        
        Args:
            filtro_bajo: Si es True, solo retorna items con stock bajo
            
        Returns:
            Lista de variantes con información de stock y alertas
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        
        query = """
            SELECT v.id_variante, v.id_producto, v.presentacion, v.precio, v.stock, v.stock_minimo, v.sku,
                   p.nombre_producto, p.marca, GROUP_CONCAT(DISTINCT c.nombre_categoria) AS categorias,
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
            GROUP BY v.id_variante, v.id_producto, v.presentacion, v.precio, v.stock, v.stock_minimo, v.sku,
                     p.nombre_producto, p.marca
        """
        
        if filtro_bajo:
            query += " AND v.stock <= v.stock_minimo"
        
        query += " ORDER BY v.stock ASC, p.nombre_producto ASC"
        
        cursor.execute(query)
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
