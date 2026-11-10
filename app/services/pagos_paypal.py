"""
Servicio de lógica de negocio para pagos con PayPal (Sandbox / Live).
Coordina la validación de propiedad, estado del pedido, llamadas al cliente HTTP
de PayPal, reembolsos automáticos de seguridad y expiración de pedidos impagos.
"""

import logging
from decimal import Decimal, InvalidOperation

from config import Config
from app.models.pago import (
    ESTADO_PAGO_CANCELADO,
    ESTADO_PAGO_COMPLETADO,
    ESTADO_PAGO_FALLIDO,
    ESTADO_PAGO_PENDIENTE,
    ESTADO_PAGO_REEMBOLSADO,
    Pago,
)
from app.models.pedido import (
    ESTADO_CANCELADO,
    ESTADO_CONFIRMADO,
    ESTADO_PENDIENTE,
    Pedido,
)
from app.utils.db import get_connection
from app.utils import paypal_client
from app.utils.paypal_client import PayPalError

logger = logging.getLogger(__name__)


def _minutos_expiracion(minutos=None):
    if minutos is not None:
        try:
            val = int(minutos)
            if val > 0:
                return val
        except (TypeError, ValueError):
            pass
    try:
        cfg_val = int(getattr(Config, "PAGO_EXPIRA_MINUTOS", 30))
        return cfg_val if cfg_val > 0 else 30
    except (TypeError, ValueError):
        return 30


def _moneda_configurada():
    return (getattr(Config, "PAYPAL_CURRENCY", "USD") or "USD").strip().upper()


def _pago_ha_expirado_sql(id_pedido, minutos=None):
    """
    Calcula en MySQL si el pago pendiente ha superado el tiempo límite de expiración
    utilizando TIMESTAMPDIFF(MINUTE, fecha_creacion, NOW()).
    """
    min_exp = _minutos_expiracion(minutos)
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT TIMESTAMPDIFF(MINUTE, fecha_creacion, NOW()) AS minutos_transcurridos
            FROM pagos
            WHERE id_pedido = %s AND estado = %s
            ORDER BY id_pago DESC
            LIMIT 1
            """,
            (id_pedido, ESTADO_PAGO_PENDIENTE),
        )
        fila = cursor.fetchone()
        if fila and fila["minutos_transcurridos"] is not None:
            return fila["minutos_transcurridos"] >= min_exp
        return False
    finally:
        cursor.close()
        conn.close()


def _contar_intentos_pago(id_pedido):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN paypal_order_id IS NOT NULL THEN 1 ELSE 0 END) AS con_orden
            FROM pagos
            WHERE id_pedido = %s
            """,
            (id_pedido,),
        )
        fila = cursor.fetchone() or {}
        con_orden = int(fila.get("con_orden") or 0)
        return con_orden + 1
    finally:
        cursor.close()
        conn.close()


def iniciar_pago(id_usuario, id_pedido):
    """
    Inicia una orden de pago en PayPal para un pedido:
    - Verifica que el pedido exista y pertenezca a `id_usuario`.
    - Verifica que el pedido esté en estado pendiente y no haya expirado.
    - Verifica que el pedido tenga un pago en estado 'pendiente'.
    - Toma el monto únicamente de `pedidos.total` en la base de datos.
    - Llama a `crear_orden` con `request_id` estable ('crear-<id_pedido>-<n_intento>')
      y registra el `order_id` en la tabla `pagos`.
    """
    pedido = Pedido.obtener_por_id(id_pedido)
    if not pedido or int(pedido["id_usuario"]) != int(id_usuario):
        raise ValueError("El pedido no existe o no pertenece al usuario")

    if int(pedido["id_estado"]) != ESTADO_PENDIENTE:
        raise ValueError("El pedido no está pendiente de pago")

    pago = Pago.obtener_por_pedido(id_pedido)
    if not pago or pago["estado"] != ESTADO_PAGO_PENDIENTE:
        raise ValueError("El pedido no tiene un pago pendiente activo")

    if _pago_ha_expirado_sql(id_pedido):
        raise ValueError("El tiempo para pagar este pedido ha expirado")

    monto_bd = Decimal(str(pedido["total"]))
    moneda = _moneda_configurada()

    # Sincronizar monto y moneda en el pago pendiente con el total real de la BD
    Pago.crear_para_pedido(id_pedido, monto_bd, moneda)

    n_intento = _contar_intentos_pago(id_pedido)
    request_id = f"crear-{id_pedido}-{n_intento}"

    order_id = paypal_client.crear_orden(
        id_pedido=id_pedido,
        monto=monto_bd,
        moneda=moneda,
        request_id=request_id,
    )
    Pago.registrar_orden(id_pedido, order_id)
    logger.info("Orden de PayPal creada para el pedido %s (intento %s)", id_pedido, n_intento)
    return order_id


def _reembolsar_automaticamente(id_pedido, capture_id, motivo):
    """
    Reembolsa automáticamente una captura cuando la validación posterior o la
    confirmación del pedido falla, marca el pago como 'reembolsado' y registra con logger.error.
    Si el pedido sigue en estado pendiente, lo cancela con Pedido.actualizar_estado(id_pedido, ESTADO_CANCELADO)
    devolviendo el stock una sola vez. Si ya no está pendiente, no hace nada más.
    """
    logger.error(
        "Iniciando reembolso automático para pedido=%s capture_id=%s por motivo: %s",
        id_pedido,
        capture_id,
        motivo,
    )
    try:
        paypal_client.reembolsar_captura(capture_id, request_id=f"reembolso-auto-{id_pedido}-{capture_id}")
        Pago.marcar(id_pedido, ESTADO_PAGO_REEMBOLSADO, capture_id=capture_id)
    except Exception:
        logger.exception(
            "Fallo crítico al intentar reembolsar automáticamente capture_id=%s del pedido=%s",
            capture_id,
            id_pedido,
        )
        raise

    # Si el pedido sigue en estado pendiente, cancelarlo para devolver el stock una sola vez
    try:
        pedido_actual = Pedido.obtener_por_id(id_pedido)
        if pedido_actual and int(pedido_actual["id_estado"]) == ESTADO_PENDIENTE:
            Pedido.actualizar_estado(id_pedido, ESTADO_CANCELADO)
            logger.info("Pedido %s cancelado y stock devuelto tras reembolso automático", id_pedido)
    except Exception:
        logger.exception(
            "Error al cancelar el pedido %s tras el reembolso automático",
            id_pedido,
        )


def capturar_pago(id_usuario, id_pedido, order_id):
    """
    Captura y confirma el pago de un pedido en PayPal:
    - Verifica propiedad del pedido y coincidencia del `order_id` guardado.
    - Si el pago ya está 'completado', devuelve éxito de forma idempotente sin volver a llamar a PayPal.
    - Verifica que el pedido siga en estado pendiente ANTES de capturar.
    - Si PayPal rechaza con INSTRUMENT_DECLINED, no marca nada definitivo y devuelve
      un estado de reintento para el navegador.
    - Exige estado COMPLETED, monto == pedidos.total, moneda == PAYPAL_CURRENCY y custom_id == str(id_pedido).
    - Si alguna verificación posterior a la captura falla o el pedido no puede pasar a confirmado,
      reembolsa automáticamente la captura, marca el pago 'reembolsado', registra con logger.error
      incluyendo `capture_id` y lanza ValueError.
    """
    if not order_id or not str(order_id).strip():
        raise ValueError("El identificador de la orden de PayPal es obligatorio")
    order_id_str = str(order_id).strip()

    pedido = Pedido.obtener_por_id(id_pedido)
    if not pedido or int(pedido["id_usuario"]) != int(id_usuario):
        raise ValueError("El pedido no existe o no pertenece al usuario")

    pago = Pago.obtener_por_pedido(id_pedido)
    if not pago:
        raise ValueError("No se encontró un registro de pago para este pedido")

    if pago.get("paypal_order_id") != order_id_str:
        raise ValueError("El identificador de la orden no coincide con el registrado para este pedido")

    # Idempotencia: si el pago ya fue completado previamente, devolver éxito sin llamar a PayPal
    if pago["estado"] == ESTADO_PAGO_COMPLETADO:
        return {
            "exito": True,
            "reintentar": False,
            "estado": "COMPLETED",
            "id_pedido": id_pedido,
            "capture_id": pago.get("paypal_capture_id"),
            "ya_completado": True,
        }

    # Verificar que el pedido siga en estado pendiente ANTES de capturar
    if int(pedido["id_estado"]) != ESTADO_PENDIENTE:
        raise ValueError("El pedido ya no está en estado pendiente y no puede ser cobrado")

    if pago["estado"] != ESTADO_PAGO_PENDIENTE:
        raise ValueError(f"El pago no está en estado pendiente (estado actual: {pago['estado']})")

    request_id = f"capturar-{id_pedido}-{order_id_str}"
    try:
        resultado = paypal_client.capturar_orden(order_id_str, request_id=request_id)
    except PayPalError as exc:
        if exc.codigo == "INSTRUMENT_DECLINED":
            logger.warning("Medio de pago rechazado (INSTRUMENT_DECLINED) en pedido %s; se permite reintentar", id_pedido)
            return {
                "exito": False,
                "reintentar": True,
                "codigo": "INSTRUMENT_DECLINED",
                "mensaje": exc.mensaje,
                "id_pedido": id_pedido,
            }
        raise

    estado_cap = (resultado.get("estado") or "").strip().upper()
    capture_id = (resultado.get("capture_id") or "").strip()
    monto_cap_raw = resultado.get("monto")
    moneda_cap = (resultado.get("moneda") or "").strip().upper()
    custom_id_cap = str(resultado.get("custom_id") or "").strip()

    if estado_cap != "COMPLETED" or not capture_id:
        raise ValueError(f"La captura de PayPal no se completó (estado: {estado_cap or 'desconocido'})")

    monto_esperado = Decimal(str(pedido["total"])).quantize(Decimal("0.01"))
    moneda_esperada = _moneda_configurada()

    try:
        monto_capturado = Decimal(str(monto_cap_raw)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        monto_capturado = Decimal("-1.00")

    # Validar integridad de monto, moneda y custom_id tras la captura
    motivo_invalido = None
    if monto_capturado != monto_esperado:
        motivo_invalido = f"El monto capturado ({monto_capturado}) no coincide con el total del pedido ({monto_esperado})"
    elif moneda_cap != moneda_esperada:
        motivo_invalido = f"La moneda capturada ({moneda_cap}) no coincide con la moneda configurada ({moneda_esperada})"
    elif custom_id_cap != str(id_pedido):
        motivo_invalido = f"El custom_id capturado ({custom_id_cap}) no coincide con el pedido ({id_pedido})"

    if motivo_invalido:
        _reembolsar_automaticamente(id_pedido, capture_id, motivo_invalido)
        raise ValueError(motivo_invalido)

    # Confirmar captura en pagos y pasar el pedido a ESTADO_CONFIRMADO;
    # si falla la confirmación del pedido, reembolsar automáticamente.
    try:
        transicion_pago = Pago.confirmar_captura(
            id_pedido=id_pedido,
            order_id=order_id_str,
            capture_id=capture_id,
            monto=monto_capturado,
            moneda=moneda_cap,
        )
        if transicion_pago:
            Pedido.actualizar_estado(id_pedido, ESTADO_CONFIRMADO)
    except Exception as exc:
        _reembolsar_automaticamente(
            id_pedido,
            capture_id,
            f"No se pudo confirmar el pedido tras capturar el pago: {exc}",
        )
        raise ValueError(f"No se pudo confirmar el pedido tras el cobro; se realizó el reembolso automático: {exc}") from exc

    logger.info("Pago confirmado exitosamente para pedido=%s capture_id=%s", id_pedido, capture_id)
    return {
        "exito": True,
        "reintentar": False,
        "estado": "COMPLETED",
        "id_pedido": id_pedido,
        "capture_id": capture_id,
        "ya_completado": False,
    }


def cancelar_pedido_con_reembolso(id_pedido):
    """
    Cancela un pedido gestionando el reembolso si corresponde:
    - Si el pedido tiene un pago 'completado', primero reembolsa en PayPal y marca el pago 'reembolsado'.
    - Si el reembolso falla, NO cancela el pedido y propaga el error.
    - Si el pago estaba 'pendiente', lo marca 'cancelado'.
    - Finalmente llama a `Pedido.actualizar_estado(id_pedido, ESTADO_CANCELADO)` que devuelve el stock una sola vez.
    """
    pedido = Pedido.obtener_por_id(id_pedido)
    if not pedido:
        raise ValueError("Pedido no encontrado")

    if int(pedido["id_estado"]) == ESTADO_CANCELADO:
        raise ValueError("El pedido ya está en ese estado")

    if not Pedido.transicion_estado_valida(int(pedido["id_estado"]), ESTADO_CANCELADO):
        raise ValueError("No se puede cancelar un pedido en su estado actual")

    pago = Pago.obtener_por_pedido(id_pedido)
    if pago:
        if pago["estado"] == ESTADO_PAGO_COMPLETADO:
            capture_id = pago.get("paypal_capture_id")
            if not capture_id:
                raise ValueError("El pago figura como completado pero no tiene capture_id para reembolsar")
            request_id = f"reembolso-cancelacion-{id_pedido}-{capture_id}"
            paypal_client.reembolsar_captura(capture_id, request_id=request_id)
            Pago.marcar(id_pedido, ESTADO_PAGO_REEMBOLSADO, capture_id=capture_id)
            logger.info("Reembolso completado para pedido=%s capture_id=%s", id_pedido, capture_id)
        elif pago["estado"] == ESTADO_PAGO_PENDIENTE:
            Pago.marcar(id_pedido, ESTADO_PAGO_CANCELADO)

    Pedido.actualizar_estado(id_pedido, ESTADO_CANCELADO)
    return True


def cancelar_impagos_vencidos(minutos=None):
    """
    Cancela (con `Pedido.actualizar_estado`, que devuelve el stock una sola vez)
    los pedidos en estado pendiente cuyo pago PayPal siga en 'pendiente' y tenga
    más de `PAGO_EXPIRA_MINUTOS` minutos, marcando el pago como 'cancelado'.
    Devuelve cuántos pedidos canceló. Es idempotente ante llamadas repetidas.
    """
    min_exp = _minutos_expiracion(minutos)
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT pg.id_pedido
            FROM pagos pg
            JOIN pedidos pe ON pg.id_pedido = pe.id_pedido
            WHERE pe.id_estado = %s
              AND pg.proveedor = 'paypal'
              AND pg.estado = %s
              AND pg.fecha_creacion <= DATE_SUB(NOW(), INTERVAL %s MINUTE)
            ORDER BY pg.id_pedido ASC
            """,
            (ESTADO_PENDIENTE, ESTADO_PAGO_PENDIENTE, min_exp),
        )
        filas = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    pedidos_vencidos = list(dict.fromkeys(f["id_pedido"] for f in filas))
    cancelados = 0

    for id_pedido in pedidos_vencidos:
        try:
            pago_actual = Pago.obtener_por_pedido(id_pedido)
            pedido_actual = Pedido.obtener_por_id(id_pedido)
            if (
                not pago_actual
                or pago_actual["estado"] != ESTADO_PAGO_PENDIENTE
                or not pedido_actual
                or int(pedido_actual["id_estado"]) != ESTADO_PENDIENTE
            ):
                continue

            Pedido.actualizar_estado(id_pedido, ESTADO_CANCELADO)
            Pago.marcar(id_pedido, ESTADO_PAGO_CANCELADO)
            cancelados += 1
            logger.info("Pedido impago vencido %s cancelado automáticamente", id_pedido)
        except ValueError as exc:
            logger.warning("No se canceló el pedido vencido %s: %s", id_pedido, exc)

    return cancelados
