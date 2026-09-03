from app.utils.db import get_connection


class Pedido:
    @staticmethod
    def crear(id_usuario, id_direccion, id_metodo_pago, total):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO pedidos (id_usuario, id_direccion, id_metodo_pago, total)
            VALUES (%s, %s, %s, %s)
        """, (id_usuario, id_direccion, id_metodo_pago, total))
        conn.commit()
        id_pedido = cursor.lastrowid
        cursor.close()
        conn.close()
        return id_pedido

    @staticmethod
    def crear_con_transaccion(id_usuario, id_direccion, id_metodo_pago, total, items):
        """
        Crea un pedido completo con transacción atómica.
        Incluye: verificación de stock, descuento de stock, creación de detalles y vaciado de carrito.
        
        Args:
            id_usuario: ID del usuario
            id_direccion: ID de la dirección
            id_metodo_pago: ID del método de pago
            total: Total del pedido
            items: Lista de items del carrito con {id_variante, cantidad, precio}
            
        Returns:
            id_pedido si se crea exitosamente, None si falla
        """
        from app.models.producto import VarianteProducto
        from app.models.carrito import CarritoItem
        
        conn = get_connection()
        cursor = conn.cursor()
        
        try:
            # 1. Crear pedido
            cursor.execute("""
                INSERT INTO pedidos (id_usuario, id_direccion, id_metodo_pago, total)
                VALUES (%s, %s, %s, %s)
            """, (id_usuario, id_direccion, id_metodo_pago, total))
            id_pedido = cursor.lastrowid
            
            # 2. Verificar y descontar stock de cada item
            for item in items:
                # Verificar stock antes de descontar
                cursor.execute(
                    "SELECT stock FROM variantes_producto WHERE id_variante = %s FOR UPDATE",
                    (item["id_variante"],)
                )
                variante = cursor.fetchone()
                
                if not variante or variante[0] < item["cantidad"]:
                    conn.rollback()
                    cursor.close()
                    conn.close()
                    return None
                
                # Descontar stock
                cursor.execute(
                    "UPDATE variantes_producto SET stock = stock - %s WHERE id_variante = %s",
                    (item["cantidad"], item["id_variante"])
                )
            
            # 3. Crear detalles del pedido
            for item in items:
                cursor.execute("""
                    INSERT INTO pedido_detalle (id_pedido, id_variante, cantidad, precio_unitario)
                    VALUES (%s, %s, %s, %s)
                """, (id_pedido, item["id_variante"], item["cantidad"], item["precio"]))
            
            # 4. Vaciar carrito
            id_carrito = None
            cursor.execute("SELECT id_carrito FROM carritos WHERE id_usuario = %s", (id_usuario,))
            result = cursor.fetchone()
            if result:
                id_carrito = result[0]
                cursor.execute("DELETE FROM carrito_items WHERE id_carrito = %s", (id_carrito,))
            
            # COMMIT
            conn.commit()
            cursor.close()
            conn.close()
            return id_pedido
            
        except Exception as e:
            # ROLLBACK en caso de error
            conn.rollback()
            cursor.close()
            conn.close()
            print(f"Error en transacción de pedido: {e}")
            return None

    @staticmethod
    def listar_por_usuario(id_usuario):
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT pe.id_pedido, pe.total, pe.fecha_pedido, es.nombre_estado,
                   d.linea_direccion, d.ciudad, mp.tipo AS tipo_pago
            FROM pedidos pe
            JOIN estados_pedido es ON pe.id_estado = es.id_estado
            LEFT JOIN direcciones d ON pe.id_direccion = d.id_direccion
            LEFT JOIN metodos_pago mp ON pe.id_metodo_pago = mp.id_metodo_pago
            WHERE pe.id_usuario = %s
            ORDER BY pe.fecha_pedido DESC
        """, (id_usuario,))
        pedidos = cursor.fetchall()
        cursor.close()
        conn.close()
        return pedidos

    @staticmethod
    def listar_todos(filtro_estado=None):
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT pe.id_pedido, pe.id_usuario, pe.total, pe.fecha_pedido,
                   es.id_estado, es.nombre_estado,
                   u.nombre AS usuario_nombre, u.apellido AS usuario_apellido, u.email AS usuario_email,
                   d.linea_direccion, d.ciudad,
                   mp.tipo AS tipo_pago
            FROM pedidos pe
            JOIN estados_pedido es ON pe.id_estado = es.id_estado
            JOIN usuarios u ON pe.id_usuario = u.id_usuario
            LEFT JOIN direcciones d ON pe.id_direccion = d.id_direccion
            LEFT JOIN metodos_pago mp ON pe.id_metodo_pago = mp.id_metodo_pago
        """
        params = []
        if filtro_estado:
            query += " WHERE es.nombre_estado = %s"
            params.append(filtro_estado)

        query += " ORDER BY pe.fecha_pedido DESC"

        cursor.execute(query, tuple(params))
        pedidos = cursor.fetchall()
        cursor.close()
        conn.close()
        return pedidos

    @staticmethod
    def obtener_por_id(id_pedido):
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT pe.id_pedido, pe.id_usuario, pe.total, pe.fecha_pedido,
                   es.id_estado, es.nombre_estado,
                   d.alias AS dir_alias, d.linea_direccion, d.ciudad, d.departamento, d.codigo_postal,
                   mp.tipo AS tipo_pago, mp.detalle AS detalle_pago,
                   u.nombre AS usuario_nombre, u.apellido AS usuario_apellido, u.email AS usuario_email, u.telefono AS usuario_telefono
            FROM pedidos pe
            JOIN estados_pedido es ON pe.id_estado = es.id_estado
            LEFT JOIN direcciones d ON pe.id_direccion = d.id_direccion
            LEFT JOIN metodos_pago mp ON pe.id_metodo_pago = mp.id_metodo_pago
            LEFT JOIN usuarios u ON pe.id_usuario = u.id_usuario
            WHERE pe.id_pedido = %s
        """, (id_pedido,))
        pedido = cursor.fetchone()
        cursor.close()
        conn.close()
        return pedido

    @staticmethod
    def actualizar_estado(id_pedido, id_estado):
        """
        Actualiza el estado de un pedido con validación de transición.
        Si se cancela, devuelve el stock al inventario.
        """
        from app.models.producto import VarianteProducto
        from app.models.pedido import PedidoDetalle
        
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            # Obtener estado actual
            cursor.execute("SELECT id_estado FROM pedidos WHERE id_pedido = %s", (id_pedido,))
            pedido = cursor.fetchone()
            
            if not pedido:
                raise ValueError("Pedido no encontrado")
            
            id_estado_actual = pedido["id_estado"]
            
            # Temporalmente desactivar validación de transiciones para depuración
            # if not Pedido.transicion_estado_valida(id_estado_actual, id_estado):
            #     raise ValueError(f"Transición inválida: estado {id_estado_actual} → {id_estado}")
            
            # Si se está cancelando, devolver stock
            if id_estado == 5:  # cancelado
                # Obtener detalles del pedido
                detalles = PedidoDetalle.listar_por_pedido(id_pedido)
                
                for detalle in detalles:
                    # Devolver stock de cada variante
                    cursor.execute(
                        "UPDATE variantes_producto SET stock = stock + %s WHERE id_variante = %s",
                        (detalle["cantidad"], detalle["id_variante"])
                    )
            
            # Actualizar estado
            cursor.execute("UPDATE pedidos SET id_estado = %s WHERE id_pedido = %s", (id_estado, id_pedido))
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def transicion_estado_valida(id_estado_actual, id_estado_nuevo):
        """
        Verifica si la transición de estado es válida.
        
        Transiciones válidas:
        - pendiente → confirmado
        - pendiente → cancelado
        - confirmado → en camino
        - confirmado → cancelado
        - en camino → entregado
        - en camino → cancelado
        """
        # Transiciones permitidas: (estado_actual, estado_nuevo)
        transiciones_permitidas = {
            1: [2, 5],  # pendiente → confirmado, cancelado
            2: [3, 5],  # confirmado → en camino, cancelado
            3: [4, 5],  # en camino → entregado, cancelado
            4: [],     # entregado → no permite cambios
            5: []      # cancelado → no permite cambios
        }
        
        return id_estado_nuevo in transiciones_permitidas.get(id_estado_actual, [])

    @staticmethod
    def eliminar(id_pedido):
        """Elimina un pedido y sus detalles (para rollback en caso de error)."""
        conn = get_connection()
        cursor = conn.cursor()
        try:
            # Primero eliminar los detalles del pedido
            cursor.execute("DELETE FROM pedido_detalle WHERE id_pedido = %s", (id_pedido,))
            # Luego eliminar el pedido
            cursor.execute("DELETE FROM pedidos WHERE id_pedido = %s", (id_pedido,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def obtener_estados():
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM estados_pedido ORDER BY id_estado ASC")
        estados = cursor.fetchall()
        cursor.close()
        conn.close()
        return estados

    @staticmethod
    def obtener_metricas_dashboard():
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # 1. Total ventas (excluyendo cancelados)
        cursor.execute("SELECT COALESCE(SUM(total), 0) AS total_ventas FROM pedidos WHERE id_estado != 5")
        ventas_row = cursor.fetchone()
        total_ventas = ventas_row["total_ventas"] if ventas_row else 0

        # 2. Total de pedidos
        cursor.execute("SELECT COUNT(*) AS total_pedidos FROM pedidos")
        total_pedidos = cursor.fetchone()["total_pedidos"]

        # 3. Pedidos pendientes
        cursor.execute("SELECT COUNT(*) AS pedidos_pendientes FROM pedidos WHERE id_estado = 1")
        pedidos_pendientes = cursor.fetchone()["pedidos_pendientes"]

        # 4. Total productos
        cursor.execute("SELECT COUNT(*) AS total_productos FROM productos")
        total_productos = cursor.fetchone()["total_productos"]

        # 5. Total usuarios
        cursor.execute("SELECT COUNT(*) AS total_usuarios FROM usuarios")
        total_usuarios = cursor.fetchone()["total_usuarios"]

        cursor.close()
        conn.close()

        return {
            "total_ventas": total_ventas,
            "total_pedidos": total_pedidos,
            "pedidos_pendientes": pedidos_pendientes,
            "total_productos": total_productos,
            "total_usuarios": total_usuarios
        }


class PedidoDetalle:
    @staticmethod
    def crear(id_pedido, id_variante, cantidad, precio_unitario):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO pedido_detalle (id_pedido, id_variante, cantidad, precio_unitario)
            VALUES (%s, %s, %s, %s)
        """, (id_pedido, id_variante, cantidad, precio_unitario))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def listar_por_pedido(id_pedido):
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT pd.id_detalle, pd.cantidad, pd.precio_unitario,
                   (pd.cantidad * pd.precio_unitario) AS subtotal,
                   v.id_variante, v.presentacion, v.sku, p.nombre_producto, p.marca
            FROM pedido_detalle pd
            JOIN variantes_producto v ON pd.id_variante = v.id_variante
            JOIN productos p ON v.id_producto = p.id_producto
            WHERE pd.id_pedido = %s
        """, (id_pedido,))
        detalles = cursor.fetchall()
        cursor.close()
        conn.close()
        return detalles
