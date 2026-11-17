"""
Modelo de Pedidos - Gestión de pedidos y transacciones.

Este módulo maneja la lógica de pedidos (`pedidos` y `pedido_detalle`),
incluyendo creación con transacciones atómicas, control de stock atómico,
máquina de estados permitidos, devolución de inventario al cancelar y
métricas para el dashboard administrativo.
"""

# Módulo estándar para registrar errores inesperados en transacciones
import logging
# Función para obtener una conexión activa a MySQL
from app.utils.db import get_connection

# Logger específico del módulo de pedidos
logger = logging.getLogger(__name__)

# Constantes numéricas correspondientes a los IDs de `estados_pedido`
ESTADO_PENDIENTE = 1
ESTADO_CONFIRMADO = 2
ESTADO_EN_CAMINO = 3
ESTADO_ENTREGADO = 4
ESTADO_CANCELADO = 5

# Mapa legible de IDs de estado a su nombre descriptivo
NOMBRES_ESTADO = {
    ESTADO_PENDIENTE: "pendiente",
    ESTADO_CONFIRMADO: "confirmado",
    ESTADO_EN_CAMINO: "en camino",
    ESTADO_ENTREGADO: "entregado",
    ESTADO_CANCELADO: "cancelado",
}

# Grafo de transiciones válidas: evita saltos inválidos o revertir estados finales
TRANSICIONES_PERMITIDAS = {
    ESTADO_PENDIENTE: [ESTADO_CONFIRMADO, ESTADO_CANCELADO],
    ESTADO_CONFIRMADO: [ESTADO_EN_CAMINO, ESTADO_CANCELADO],
    ESTADO_EN_CAMINO: [ESTADO_ENTREGADO, ESTADO_CANCELADO],
    ESTADO_ENTREGADO: [],
    ESTADO_CANCELADO: [],
}


class Pedido:
    """
    Modelo principal para la gestión de pedidos de clientes (tabla `pedidos`).
    """

    # Exposición de constantes y reglas de transición como atributos de clase
    ESTADO_PENDIENTE = ESTADO_PENDIENTE
    ESTADO_CONFIRMADO = ESTADO_CONFIRMADO
    ESTADO_EN_CAMINO = ESTADO_EN_CAMINO
    ESTADO_ENTREGADO = ESTADO_ENTREGADO
    ESTADO_CANCELADO = ESTADO_CANCELADO
    NOMBRES_ESTADO = NOMBRES_ESTADO
    TRANSICIONES_PERMITIDAS = TRANSICIONES_PERMITIDAS

    @staticmethod
    def crear(id_usuario, id_direccion, id_metodo_pago, total):
        """
        Inserta un registro básico en `pedidos` sin gestionar detalles ni stock.

        Args:
            id_usuario (int): ID del cliente.
            id_direccion (int): ID de la dirección de entrega.
            id_metodo_pago (int): ID del método de pago.
            total (Decimal | float): Monto total del pedido.

        Returns:
            int: ID autogenerado del pedido creado.
        """
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
        - Descuento de stock en una sola operación (`UPDATE ... WHERE stock >= cantidad`)
        - Creación de detalles del pedido
        - Vaciado del carrito del usuario
        - Rollback automático si falla cualquier paso

        Args:
            id_usuario (int): ID del usuario que realiza el pedido.
            id_direccion (int): ID de la dirección de entrega.
            id_metodo_pago (int): ID del método de pago seleccionado.
            total (Decimal | float): Total del pedido (con descuentos aplicados).
            items (list[dict]): Lista de ítems del carrito con `id_variante`, `cantidad`,
                `precio` y opcionalmente `precio_oferta`.

        Returns:
            int | dict | None: `id_pedido` si se crea exitosamente, diccionario con
                `'error': 'stock_insuficiente'` si falta inventario, o `None` si ocurre
                una excepción inesperada.
        """
        conn = get_connection()
        cursor = conn.cursor()

        try:
            # Iniciar transacción explícita (BEGIN TRANSACTION)
            conn.start_transaction()

            # 1. Crear cabecera del pedido
            cursor.execute("""
                INSERT INTO pedidos (id_usuario, id_direccion, id_metodo_pago, total)
                VALUES (%s, %s, %s, %s)
            """, (id_usuario, id_direccion, id_metodo_pago, total))
            id_pedido = cursor.lastrowid

            # 2. Verificar y descontar stock de cada ítem en una sola operación atómica
            for item in items:
                cursor.execute(
                    "UPDATE variantes_producto SET stock = stock - %s WHERE id_variante = %s AND stock >= %s",
                    (item["cantidad"], item["id_variante"], item["cantidad"])
                )

                # Si rowcount es 0, la variante no existe o no tiene stock suficiente
                if cursor.rowcount == 0:
                    cursor.execute(
                        "SELECT stock FROM variantes_producto WHERE id_variante = %s",
                        (item["id_variante"],)
                    )
                    variante = cursor.fetchone()

                    # Revertir todo lo insertado hasta ahora y liberar conexión
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

            # 3. Crear detalles del pedido congelando el precio vigente al momento de compra
            for item in items:
                precio_final = item["precio_oferta"] if item.get("precio_oferta") is not None else item["precio"]
                cursor.execute("""
                    INSERT INTO pedido_detalle (id_pedido, id_variante, cantidad, precio_unitario)
                    VALUES (%s, %s, %s, %s)
                """, (id_pedido, item["id_variante"], item["cantidad"], precio_final))

            # 4. Vaciar carrito del usuario dentro de la misma transacción
            cursor.execute("SELECT id_carrito FROM carritos WHERE id_usuario = %s", (id_usuario,))
            result = cursor.fetchone()
            if result:
                id_carrito = result[0]
                cursor.execute("DELETE FROM carrito_items WHERE id_carrito = %s", (id_carrito,))

            # Confirmar toda la operación (COMMIT)
            conn.commit()
            cursor.close()
            conn.close()
            return id_pedido

        except Exception:
            # Ante cualquier error inesperado, revertir y registrar la traza completa
            conn.rollback()
            cursor.close()
            conn.close()
            logger.exception("Error en transacción de pedido")
            return None

    @staticmethod
    def listar_por_usuario(id_usuario):
        """
        Lista los pedidos realizados por un usuario específico, del más reciente al más antiguo.

        Args:
            id_usuario (int): ID del usuario.

        Returns:
            list[dict]: Lista de pedidos con estado, dirección y tipo de pago.
        """
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
        """
        Lista todos los pedidos del sistema para el panel administrativo, con filtro
        opcional por nombre de estado.

        Args:
            filtro_estado (str, optional): Nombre exacto del estado (ej. `'pendiente'`).

        Returns:
            list[dict]: Lista de pedidos con datos del cliente, dirección y método de pago.
        """
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
        # Agregar cláusula WHERE solo si se especificó un estado de filtro
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
        """
        Obtiene toda la información de cabecera de un pedido por su ID, incluyendo
        datos completos de dirección, método de pago y usuario.

        Args:
            id_pedido (int): Identificador único del pedido.

        Returns:
            dict | None: Diccionario con los datos del pedido o None si no existe.
        """
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
    def actualizar_estado(id_pedido, id_estado, cursor=None):
        """
        Actualiza el estado de un pedido con bloqueo `FOR UPDATE` y validación de transición.
        Si pasa a cancelado desde un estado válido, devuelve el stock al inventario una sola vez.
        Si se provee `cursor`, opera dentro de la transacción existente sin hacer commit/rollback/close.

        Args:
            id_pedido (int): ID del pedido a actualizar.
            id_estado (int): Nuevo ID de estado destino.
            cursor (mysql.connector.cursor, optional): Cursor externo para participar
                en una transacción ya abierta por el llamador.

        Raises:
            ValueError: Si el pedido no existe, ya está en ese estado o la transición no es válida.
        """
        # Determinar si este método debe gestionar su propia conexión y transacción
        own_conn = cursor is None
        conn = get_connection() if own_conn else None
        active_cursor = conn.cursor(dictionary=True) if own_conn else cursor

        try:
            if own_conn:
                conn.start_transaction()

            # Bloquear la fila del pedido para evitar cancelaciones o cambios simultáneos
            active_cursor.execute(
                "SELECT id_estado FROM pedidos WHERE id_pedido = %s FOR UPDATE",
                (id_pedido,)
            )
            pedido = active_cursor.fetchone()

            if not pedido:
                raise ValueError("Pedido no encontrado")

            id_estado_actual = pedido["id_estado"]

            if id_estado == id_estado_actual:
                raise ValueError("El pedido ya está en ese estado")

            # Validar la transición según la máquina de estados definida
            if not Pedido.transicion_estado_valida(id_estado_actual, id_estado):
                nombre_actual = NOMBRES_ESTADO.get(id_estado_actual, str(id_estado_actual))
                nombre_nuevo = NOMBRES_ESTADO.get(id_estado, str(id_estado))
                raise ValueError(f"No se puede cambiar un pedido de {nombre_actual} a {nombre_nuevo}")

            # Si se está cancelando, devolver stock al inventario dentro de la misma transacción
            if id_estado == ESTADO_CANCELADO:
                active_cursor.execute(
                    "SELECT id_variante, cantidad FROM pedido_detalle WHERE id_pedido = %s",
                    (id_pedido,)
                )
                detalles = active_cursor.fetchall()

                for detalle in detalles:
                    active_cursor.execute(
                        "UPDATE variantes_producto SET stock = stock + %s WHERE id_variante = %s",
                        (detalle["cantidad"], detalle["id_variante"])
                    )

            # Actualizar estado del pedido
            active_cursor.execute(
                "UPDATE pedidos SET id_estado = %s WHERE id_pedido = %s",
                (id_estado, id_pedido)
            )
            if own_conn:
                conn.commit()

        except Exception as e:
            if own_conn and conn is not None:
                conn.rollback()
            raise e
        finally:
            # Solo cerrar recursos si fueron creados por esta función
            if own_conn:
                if active_cursor is not None:
                    active_cursor.close()
                if conn is not None:
                    conn.close()

    @staticmethod
    def transicion_estado_valida(id_estado_actual, id_estado_nuevo):
        """
        Verifica si la transición de estado es válida según el flujo del negocio:
        - pendiente (1) -> confirmado (2), cancelado (5)
        - confirmado (2) -> en camino (3), cancelado (5)
        - en camino (3) -> entregado (4), cancelado (5)
        - entregado (4) -> ninguno
        - cancelado (5) -> ninguno

        Args:
            id_estado_actual (int): Estado actual del pedido.
            id_estado_nuevo (int): Estado destino propuesto.

        Returns:
            bool: True si la transición está permitida, False en caso contrario.
        """
        return id_estado_nuevo in TRANSICIONES_PERMITIDAS.get(id_estado_actual, [])

    @staticmethod
    def ids_estados_permitidos_select(id_estado_actual, permitir_cancelar=True):
        """
        Devuelve la lista de `id_estado` que debe mostrar el `<select>` en la UI
        para un pedido: el estado actual más los estados siguientes válidos.

        Args:
            id_estado_actual (int): Estado actual del pedido.
            permitir_cancelar (bool, optional): Si es False, omite la opción de cancelar.

        Returns:
            list[int]: Lista de IDs de estado seleccionables.
        """
        siguientes = TRANSICIONES_PERMITIDAS.get(id_estado_actual, [])
        if not permitir_cancelar:
            siguientes = [s for s in siguientes if s != ESTADO_CANCELADO]
        return [id_estado_actual] + siguientes

    @staticmethod
    def eliminar(id_pedido):
        """
        Elimina un pedido y sus detalles (útil para rollback manual en caso de error).

        Args:
            id_pedido (int): ID del pedido a eliminar.
        """
        conn = get_connection()
        cursor = conn.cursor()
        try:
            # Eliminar primero los hijos en `pedido_detalle` por integridad referencial
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
        """
        Obtiene el catálogo de estados de pedido ordenados por ID.

        Returns:
            list[dict]: Lista de filas de la tabla `estados_pedido`.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM estados_pedido ORDER BY id_estado ASC")
        estados = cursor.fetchall()
        cursor.close()
        conn.close()
        return estados

    @staticmethod
    def obtener_metricas_dashboard():
        """
        Obtiene métricas globales para las tarjetas del panel administrativo:
        total de ventas, total de pedidos válidos, pedidos pendientes, total de
        productos y total de usuarios.

        Returns:
            dict: Diccionario con los cinco indicadores del dashboard.
        """
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

        # 3. Pedidos pendientes por gestionar
        cursor.execute(
            "SELECT COUNT(*) AS pedidos_pendientes FROM pedidos WHERE id_estado = %s",
            (ESTADO_PENDIENTE,)
        )
        pedidos_pendientes = cursor.fetchone()["pedidos_pendientes"]

        # 4. Total de productos registrados en el catálogo
        cursor.execute("SELECT COUNT(*) AS total_productos FROM productos")
        total_productos = cursor.fetchone()["total_productos"]

        # 5. Total de usuarios registrados
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
    """
    Modelo para las líneas de detalle de cada pedido (tabla `pedido_detalle`).
    """

    @staticmethod
    def crear(id_pedido, id_variante, cantidad, precio_unitario):
        """
        Inserta una línea de detalle asociada a un pedido.

        Args:
            id_pedido (int): ID del pedido padre.
            id_variante (int): ID de la variante vendida.
            cantidad (int): Cantidad de unidades.
            precio_unitario (Decimal | float): Precio unitario aplicado.
        """
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
        """
        Lista todos los ítems de un pedido con su subtotal calculado y datos del producto.

        Args:
            id_pedido (int): ID del pedido a consultar.

        Returns:
            list[dict]: Lista de líneas de detalle del pedido.
        """
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
