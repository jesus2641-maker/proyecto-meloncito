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
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE pedidos SET id_estado = %s WHERE id_pedido = %s", (id_estado, id_pedido))
        conn.commit()
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
