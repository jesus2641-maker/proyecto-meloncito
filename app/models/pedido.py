"""
Modelo de Pedidos - Gestión de pedidos y transacciones
Este módulo maneja la lógica de pedidos, incluyendo creación con transacciones,
gestión de estados y detalles de pedidos. Integra control de stock atómico.
"""

import logging
from app.utils.db import get_connection

logger = logging.getLogger(__name__)

ESTADO_PENDIENTE = 1
ESTADO_CONFIRMADO = 2
ESTADO_EN_CAMINO = 3
ESTADO_ENTREGADO = 4
ESTADO_CANCELADO = 5

NOMBRES_ESTADO = {
    ESTADO_PENDIENTE: "pendiente",
    ESTADO_CONFIRMADO: "confirmado",
    ESTADO_EN_CAMINO: "en camino",
    ESTADO_ENTREGADO: "entregado",
    ESTADO_CANCELADO: "cancelado",
}

TRANSICIONES_PERMITIDAS = {
    ESTADO_PENDIENTE: [ESTADO_CONFIRMADO, ESTADO_CANCELADO],
    ESTADO_CONFIRMADO: [ESTADO_EN_CAMINO, ESTADO_CANCELADO],
    ESTADO_EN_CAMINO: [ESTADO_ENTREGADO, ESTADO_CANCELADO],
    ESTADO_ENTREGADO: [],
    ESTADO_CANCELADO: [],
}


class Pedido:
    ESTADO_PENDIENTE = ESTADO_PENDIENTE
    ESTADO_CONFIRMADO = ESTADO_CONFIRMADO
    ESTADO_EN_CAMINO = ESTADO_EN_CAMINO
    ESTADO_ENTREGADO = ESTADO_ENTREGADO
    ESTADO_CANCELADO = ESTADO_CANCELADO
    NOMBRES_ESTADO = NOMBRES_ESTADO
    TRANSICIONES_PERMITIDAS = TRANSICIONES_PERMITIDAS

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
        Crea un pedido completo con transacción atómica para garantizar integridad de datos.

        Este método implementa:
        - Verificación atómica de stock (previene condiciones de carrera)
        - Descuento de stock en una sola operación
        - Creación de detalles del pedido
        - Vaciado del carrito
        - Rollback automático si falla cualquier paso

        Args:
            id_usuario: ID del usuario que realiza el pedido
            id_direccion: ID de la dirección de entrega
            id_metodo_pago: ID del método de pago seleccionado
            total: Total del pedido (con descuentos aplicados)
            items: Lista de items del carrito con {id_variante, cantidad, precio, precio_oferta}

        Returns:
            id_pedido si se crea exitosamente, None o dict de error si falla
        """
        conn = get_connection()
        cursor = conn.cursor()

        try:
            # BEGIN TRANSACTION
            conn.start_transaction()

            # 1. Crear pedido
            cursor.execute("""
                INSERT INTO pedidos (id_usuario, id_direccion, id_metodo_pago, total)
                VALUES (%s, %s, %s, %s)
            """, (id_usuario, id_direccion, id_metodo_pago, total))
            id_pedido = cursor.lastrowid

            # 2. Verificar y descontar stock de cada item en una sola operación atómica
            for item in items:
                cursor.execute(
                    "UPDATE variantes_producto SET stock = stock - %s WHERE id_variante = %s AND stock >= %s",
                    (item["cantidad"], item["id_variante"], item["cantidad"])
                )

                # Verificar si se actualizó alguna fila
                if cursor.rowcount == 0:
                    cursor.execute(
                        "SELECT stock FROM variantes_producto WHERE id_variante = %s",
                        (item["id_variante"],)
                    )
                    variante = cursor.fetchone()

                    conn.rollback()
                    cursor.close()
                    conn.close()

                    error_info = {
                        'error': 'stock_insuficiente',
                        'id_variante': item.get("id_variante"),
                        'cantidad_solicitada': item.get("cantidad"),
                        'stock_disponible': variante[0] if variante else 0,
                        'nombre_producto': item.get("nombre_producto", "Producto"),
                        'presentacion': item.get("presentacion", "")
                    }
                    return error_info

            # 3. Crear detalles del pedido
            for item in items:
                precio_final = item.get("precio_oferta") if item.get("precio_oferta") else item["precio"]
                cursor.execute("""
                    INSERT INTO pedido_detalle (id_pedido, id_variante, cantidad, precio_unitario)
                    VALUES (%s, %s, %s, %s)
                """, (id_pedido, item["id_variante"], item["cantidad"], precio_final))

            # 4. Vaciar carrito
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

        except Exception:
            conn.rollback()
            cursor.close()
            conn.close()
            logger.exception("Error en transacción de pedido")
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
        Actualiza el estado de un pedido con bloqueo FOR UPDATE y validación de transición.
        Si pasa a cancelado desde un estado válido, devuelve el stock al inventario una sola vez.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            conn.start_transaction()

            # Bloquear la fila del pedido para evitar cancelaciones simultáneas
            cursor.execute(
                "SELECT id_estado FROM pedidos WHERE id_pedido = %s FOR UPDATE",
                (id_pedido,)
            )
            pedido = cursor.fetchone()

            if not pedido:
                raise ValueError("Pedido no encontrado")

            id_estado_actual = pedido["id_estado"]

            if id_estado == id_estado_actual:
                raise ValueError("El pedido ya está en ese estado")

            if not Pedido.transicion_estado_valida(id_estado_actual, id_estado):
                nombre_actual = NOMBRES_ESTADO.get(id_estado_actual, str(id_estado_actual))
                nombre_nuevo = NOMBRES_ESTADO.get(id_estado, str(id_estado))
                raise ValueError(f"No se puede cambiar un pedido de {nombre_actual} a {nombre_nuevo}")

            # Si se está cancelando, devolver stock dentro de la misma transacción
            if id_estado == ESTADO_CANCELADO:
                cursor.execute(
                    "SELECT id_variante, cantidad FROM pedido_detalle WHERE id_pedido = %s",
                    (id_pedido,)
                )
                detalles = cursor.fetchall()

                for detalle in detalles:
                    cursor.execute(
                        "UPDATE variantes_producto SET stock = stock + %s WHERE id_variante = %s",
                        (detalle["cantidad"], detalle["id_variante"])
                    )

            # Actualizar estado
            cursor.execute(
                "UPDATE pedidos SET id_estado = %s WHERE id_pedido = %s",
                (id_estado, id_pedido)
            )
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
        Verifica si la transición de estado es válida:
        - pendiente (1) → confirmado (2), cancelado (5)
        - confirmado (2) → en camino (3), cancelado (5)
        - en camino (3) → entregado (4), cancelado (5)
        - entregado (4) → ninguno
        - cancelado (5) → ninguno
        """
        return id_estado_nuevo in TRANSICIONES_PERMITIDAS.get(id_estado_actual, [])

    @staticmethod
    def ids_estados_permitidos_select(id_estado_actual, permitir_cancelar=True):
        """
        Devuelve la lista de id_estado que debe mostrar el <select> para un pedido:
        el estado actual más los estados siguientes válidos.
        """
        siguientes = TRANSICIONES_PERMITIDAS.get(id_estado_actual, [])
        if not permitir_cancelar:
            siguientes = [s for s in siguientes if s != ESTADO_CANCELADO]
        return [id_estado_actual] + siguientes

    @staticmethod
    def eliminar(id_pedido):
        """Elimina un pedido y sus detalles (para rollback en caso de error)."""
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM pedido_detalle WHERE id_pedido = %s", (id_pedido,))
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

        # 1. Total ventas y total de pedidos (excluyendo cancelados y pagos incompletos/reembolsados)
        cursor.execute(
            """
            SELECT COALESCE(SUM(pe.total), 0) AS total_ventas,
                   COUNT(pe.id_pedido) AS total_pedidos
            FROM pedidos pe
            WHERE pe.id_estado != %s
              AND (
                NOT EXISTS (SELECT 1 FROM pagos pg WHERE pg.id_pedido = pe.id_pedido)
                OR EXISTS (SELECT 1 FROM pagos pg WHERE pg.id_pedido = pe.id_pedido AND pg.estado = 'completado')
              )
            """,
            (ESTADO_CANCELADO,)
        )
        ventas_row = cursor.fetchone()
        total_ventas = ventas_row["total_ventas"] if ventas_row else 0
        total_pedidos = ventas_row["total_pedidos"] if ventas_row else 0

        # 3. Pedidos pendientes
        cursor.execute(
            "SELECT COUNT(*) AS pedidos_pendientes FROM pedidos WHERE id_estado = %s",
            (ESTADO_PENDIENTE,)
        )
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
