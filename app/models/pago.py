"""
Modelo de Pagos - Gestión de transacciones de pago con PayPal
Este módulo administra el ciclo de vida de los pagos en la tabla `pagos`
con operaciones transaccionales e idempotentes.
"""

import logging
from decimal import Decimal
from app.utils.db import get_connection

logger = logging.getLogger(__name__)

ESTADO_PAGO_PENDIENTE = "pendiente"
ESTADO_PAGO_COMPLETADO = "completado"
ESTADO_PAGO_FALLIDO = "fallido"
ESTADO_PAGO_CANCELADO = "cancelado"
ESTADO_PAGO_REEMBOLSADO = "reembolsado"

ESTADOS_PAGO_MARCABLES = (
    ESTADO_PAGO_FALLIDO,
    ESTADO_PAGO_CANCELADO,
    ESTADO_PAGO_REEMBOLSADO,
)


class Pago:
    ESTADO_PENDIENTE = ESTADO_PAGO_PENDIENTE
    ESTADO_COMPLETADO = ESTADO_PAGO_COMPLETADO
    ESTADO_FALLIDO = ESTADO_PAGO_FALLIDO
    ESTADO_CANCELADO = ESTADO_PAGO_CANCELADO
    ESTADO_REEMBOLSADO = ESTADO_PAGO_REEMBOLSADO

    @staticmethod
    def crear_para_pedido(id_pedido, monto, moneda, proveedor="paypal", tasa_cop_usd=None, monto_usd=None):
        """
        Inserta un pago en estado 'pendiente' y devuelve su id_pago.
        Si el pedido ya tiene un pago en estado 'pendiente', lo reutiliza y actualiza
        sus importes y tasa si cambiaron.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
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
            monto_dec = Decimal(str(monto))
            moneda_norm = (moneda or "USD").strip().upper()
            tasa_dec = Decimal(str(tasa_cop_usd)) if tasa_cop_usd is not None else None
            monto_usd_dec = Decimal(str(monto_usd)) if monto_usd is not None else None

            if existente:
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
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def obtener_por_pedido(id_pedido):
        """Obtiene el pago más reciente asociado a un pedido."""
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
        """Asocia el paypal_order_id al pago pendiente del pedido."""
        if not paypal_order_id or not str(paypal_order_id).strip():
            raise ValueError("paypal_order_id no puede estar vacío")

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            conn.start_transaction()
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
        En una transacción con SELECT ... FOR UPDATE sobre el pago, marca 'completado'
        (idempotente: si ya estaba 'completado' devuelve False sin hacer nada más)
        y guarda el capture_id. Devuelve True si realizó la transición a 'completado'.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            conn.start_transaction()
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

            if pago["estado"] == ESTADO_PAGO_COMPLETADO:
                conn.commit()
                return False

            if pago["estado"] != ESTADO_PAGO_PENDIENTE:
                raise ValueError(f"El pago no está en estado pendiente (estado actual: {pago['estado']})")

            if pago["paypal_order_id"] and order_id and pago["paypal_order_id"] != str(order_id).strip():
                raise ValueError("El order_id no coincide con el registrado para este pedido")

            monto_usd_final = Decimal(str(monto_usd)) if monto_usd is not None else pago.get("monto_usd")

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
        Marca el pago de un pedido como 'fallido', 'cancelado' o 'reembolsado'.
        Opcionalmente guarda el capture_id si se provee (por ejemplo, al reembolsar).
        """
        if estado not in ESTADOS_PAGO_MARCABLES:
            raise ValueError(f"Estado de pago no permitido en marcar(): {estado}")

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            conn.start_transaction()
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
