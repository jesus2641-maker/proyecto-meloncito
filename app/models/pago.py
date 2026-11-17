"""
Modelo de Pagos - Gestión de transacciones de pago con PayPal.

Este módulo administra el ciclo de vida de los pagos en la tabla `pagos`
con operaciones transaccionales e idempotentes, utilizando bloqueos de fila
(`SELECT ... FOR UPDATE`) para evitar capturas duplicadas o estados inconsistentes.
"""

# Módulo de logging para trazabilidad de pagos
import logging
# Tipo Decimal para manejar montos y tasas de cambio sin pérdida de precisión
from decimal import Decimal
# Función para obtener una conexión activa a MySQL
from app.utils.db import get_connection

# Logger específico del módulo de pagos
logger = logging.getLogger(__name__)

# Constantes de estados posibles de una transacción de pago
ESTADO_PAGO_PENDIENTE = "pendiente"
ESTADO_PAGO_COMPLETADO = "completado"
ESTADO_PAGO_FALLIDO = "fallido"
ESTADO_PAGO_CANCELADO = "cancelado"
ESTADO_PAGO_REEMBOLSADO = "reembolsado"

# Subconjunto de estados terminales o negativos permitidos en el método `marcar()`
ESTADOS_PAGO_MARCABLES = (
    ESTADO_PAGO_FALLIDO,
    ESTADO_PAGO_CANCELADO,
    ESTADO_PAGO_REEMBOLSADO,
)


class Pago:
    """
    Modelo para administrar las transacciones de pago asociadas a los pedidos.
    """

    # Exposición de constantes de estado como atributos de clase para conveniencia
    ESTADO_PENDIENTE = ESTADO_PAGO_PENDIENTE
    ESTADO_COMPLETADO = ESTADO_PAGO_COMPLETADO
    ESTADO_FALLIDO = ESTADO_PAGO_FALLIDO
    ESTADO_CANCELADO = ESTADO_PAGO_CANCELADO
    ESTADO_REEMBOLSADO = ESTADO_PAGO_REEMBOLSADO

    @staticmethod
    def crear_para_pedido(id_pedido, monto, moneda, proveedor="paypal", tasa_cop_usd=None, monto_usd=None):
        """
        Inserta un pago en estado 'pendiente' y devuelve su `id_pago`.
        Si el pedido ya tiene un pago en estado 'pendiente', lo reutiliza y actualiza
        sus importes y tasa de cambio si cambiaron.

        Args:
            id_pedido (int): ID del pedido asociado.
            monto (Decimal | float | str): Monto en la moneda principal del pedido.
            moneda (str): Código de moneda ISO (ej. "COP", "USD").
            proveedor (str, optional): Pasarela de pago. Por defecto `"paypal"`.
            tasa_cop_usd (Decimal | float | str, optional): Tasa de conversión COP->USD aplicada.
            monto_usd (Decimal | float | str, optional): Equivalente convertido a USD.

        Returns:
            int: ID del registro de pago creado o reutilizado.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            # Iniciar transacción explícita para bloquear el último pago pendiente si existe
            conn.start_transaction()

            cursor.execute(
                """
                SELECT id_pago, monto, moneda, tasa_cop_usd, monto_usd
                FROM pagos
                WHERE id_pedido = %s AND estado = %s
                ORDER BY id_pago DESC
                LIMIT 1
                FOR UPDATE
                """,
                (id_pedido, ESTADO_PAGO_PENDIENTE),
            )
            existente = cursor.fetchone()
            # Normalizar valores numéricos y código de moneda
            monto_dec = Decimal(str(monto))
            moneda_norm = (moneda or "USD").strip().upper()
            tasa_dec = Decimal(str(tasa_cop_usd)) if tasa_cop_usd is not None else None
            monto_usd_dec = Decimal(str(monto_usd)) if monto_usd is not None else None

            if existente:
                # Reutilizar el pago pendiente existente actualizando montos y tasa
                cursor.execute(
                    """
                    UPDATE pagos 
                    SET monto = %s, moneda = %s, tasa_cop_usd = %s, monto_usd = %s 
                    WHERE id_pago = %s
                    """,
                    (monto_dec, moneda_norm, tasa_dec, monto_usd_dec, existente["id_pago"]),
                )
                conn.commit()
                return existente["id_pago"]

            # Crear un nuevo registro de pago en estado 'pendiente'
            cursor.execute(
                """
                INSERT INTO pagos (id_pedido, proveedor, monto, moneda, estado, tasa_cop_usd, monto_usd)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (id_pedido, proveedor, monto_dec, moneda_norm, ESTADO_PAGO_PENDIENTE, tasa_dec, monto_usd_dec),
            )
            id_pago = cursor.lastrowid
            conn.commit()
            return id_pago
        except Exception:
            # Revertir cualquier cambio parcial si ocurre un error
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def obtener_por_pedido(id_pedido):
        """
        Obtiene el pago más reciente asociado a un pedido.

        Args:
            id_pedido (int): ID del pedido.

        Returns:
            dict | None: Diccionario con los datos del pago o None si no existe.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT id_pago, id_pedido, proveedor, paypal_order_id, paypal_capture_id,
                       monto, moneda, estado, tasa_cop_usd, monto_usd, fecha_creacion, fecha_actualizacion
                FROM pagos
                WHERE id_pedido = %s
                ORDER BY id_pago DESC
                LIMIT 1
                """,
                (id_pedido,),
            )
            return cursor.fetchone()
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def registrar_orden(id_pedido, paypal_order_id):
        """
        Asocia el `paypal_order_id` retornado por PayPal al pago pendiente del pedido.

        Args:
            id_pedido (int): ID del pedido.
            paypal_order_id (str): Identificador de orden generado por la API de PayPal.

        Returns:
            int: ID del pago actualizado.

        Raises:
            ValueError: Si `paypal_order_id` está vacío, no existe pago o no está pendiente.
        """
        if not paypal_order_id or not str(paypal_order_id).strip():
            raise ValueError("paypal_order_id no puede estar vacío")

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            conn.start_transaction()
            # Bloquear el pago más reciente del pedido para verificar su estado
            cursor.execute(
                """
                SELECT id_pago, estado
                FROM pagos
                WHERE id_pedido = %s
                ORDER BY id_pago DESC
                LIMIT 1
                FOR UPDATE
                """,
                (id_pedido,),
            )
            pago = cursor.fetchone()
            if not pago:
                raise ValueError("No existe un registro de pago para este pedido")
            if pago["estado"] != ESTADO_PAGO_PENDIENTE:
                raise ValueError(f"No se puede registrar una orden sobre un pago en estado {pago['estado']}")

            # Guardar el identificador de orden de PayPal
            cursor.execute(
                "UPDATE pagos SET paypal_order_id = %s WHERE id_pago = %s",
                (str(paypal_order_id).strip(), pago["id_pago"]),
            )
            conn.commit()
            return pago["id_pago"]
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def confirmar_captura(id_pedido, order_id, capture_id, monto, moneda, monto_usd=None):
        """
        En una transacción con `SELECT ... FOR UPDATE` sobre el pago, marca el estado
        como `'completado'` de forma idempotente y guarda el `capture_id`.

        Si el pago ya estaba `'completado'`, devuelve `False` sin modificar datos
        para evitar procesar dos veces el mismo webhook o callback.

        Args:
            id_pedido (int): ID del pedido.
            order_id (str | None): ID de la orden de PayPal.
            capture_id (str | None): ID de la captura confirmada por PayPal.
            monto (Decimal | float | str): Monto capturado.
            moneda (str | None): Moneda de la captura.
            monto_usd (Decimal | float | str, optional): Monto equivalente en USD.

        Returns:
            bool: `True` si realizó la transición a `'completado'`, `False` si ya lo estaba.

        Raises:
            ValueError: Si el pago no existe, su estado no es `'pendiente'` o el `order_id` no coincide.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            conn.start_transaction()
            # Bloquear fila de pago para garantizar idempotencia ante peticiones concurrentes
            cursor.execute(
                """
                SELECT id_pago, paypal_order_id, paypal_capture_id, monto, moneda, estado, tasa_cop_usd, monto_usd
                FROM pagos
                WHERE id_pedido = %s
                ORDER BY id_pago DESC
                LIMIT 1
                FOR UPDATE
                """,
                (id_pedido,),
            )
            pago = cursor.fetchone()
            if not pago:
                raise ValueError("Pago no encontrado para el pedido")

            # Idempotencia: si ya estaba completado, confirmar lectura y salir con False
            if pago["estado"] == ESTADO_PAGO_COMPLETADO:
                conn.commit()
                return False

            if pago["estado"] != ESTADO_PAGO_PENDIENTE:
                raise ValueError(f"El pago no está en estado pendiente (estado actual: {pago['estado']})")

            # Verificar coherencia entre el order_id registrado y el recibido en la captura
            if pago["paypal_order_id"] and order_id and pago["paypal_order_id"] != str(order_id).strip():
                raise ValueError("El order_id no coincide con el registrado para este pedido")

            monto_usd_final = Decimal(str(monto_usd)) if monto_usd is not None else pago.get("monto_usd")

            # Actualizar estado a completado y registrar identificadores y montos finales
            cursor.execute(
                """
                UPDATE pagos
                SET estado = %s,
                    paypal_order_id = COALESCE(paypal_order_id, %s),
                    paypal_capture_id = %s,
                    monto = %s,
                    moneda = %s,
                    monto_usd = COALESCE(%s, monto_usd)
                WHERE id_pago = %s
                """,
                (
                    ESTADO_PAGO_COMPLETADO,
                    str(order_id).strip() if order_id else None,
                    str(capture_id).strip() if capture_id else None,
                    Decimal(str(monto)),
                    (moneda or pago["moneda"]).strip().upper(),
                    monto_usd_final,
                    pago["id_pago"],
                ),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def marcar(id_pedido, estado, capture_id=None):
        """
        Marca el pago de un pedido como `'fallido'`, `'cancelado'` o `'reembolsado'`.
        Opcionalmente guarda el `capture_id` si se provee (por ejemplo, al reembolsar).

        Args:
            id_pedido (int): ID del pedido asociado.
            estado (str): Nuevo estado permitido en `ESTADOS_PAGO_MARCABLES`.
            capture_id (str, optional): ID de captura de PayPal si aplica.

        Returns:
            int: ID del pago actualizado.

        Raises:
            ValueError: Si el estado no está permitido o no existe pago para el pedido.
        """
        if estado not in ESTADOS_PAGO_MARCABLES:
            raise ValueError(f"Estado de pago no permitido en marcar(): {estado}")

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            conn.start_transaction()
            # Bloquear el pago más reciente del pedido antes de actualizar su estado
            cursor.execute(
                """
                SELECT id_pago, estado
                FROM pagos
                WHERE id_pedido = %s
                ORDER BY id_pago DESC
                LIMIT 1
                FOR UPDATE
                """,
                (id_pedido,),
            )
            pago = cursor.fetchone()
            if not pago:
                raise ValueError("Pago no encontrado para el pedido")

            if capture_id:
                # Conservar capture_id previo si ya existía usando COALESCE
                cursor.execute(
                    "UPDATE pagos SET estado = %s, paypal_capture_id = COALESCE(paypal_capture_id, %s) WHERE id_pago = %s",
                    (estado, str(capture_id).strip(), pago["id_pago"]),
                )
            else:
                cursor.execute(
                    "UPDATE pagos SET estado = %s WHERE id_pago = %s",
                    (estado, pago["id_pago"]),
                )
            conn.commit()
            return pago["id_pago"]
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()
