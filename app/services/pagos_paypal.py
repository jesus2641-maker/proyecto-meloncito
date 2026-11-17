"""
Servicio de lógica de negocio para pagos con PayPal (Sandbox / Live).

Coordina:
- La validación de propiedad y estado del pedido antes de cobrar.
- La conversión autoritativa del total en COP (desde BD) a USD.
- Las llamadas idempotentes al cliente HTTP de PayPal (`paypal_client`).
- Bloqueo pesimista (`FOR UPDATE`) durante la captura para evitar doble cobro o
  condiciones de carrera.
- Reembolsos automáticos de seguridad si la captura no coincide con lo esperado o
  si falla la confirmación del pedido.
- Expiración y cancelación automática de pedidos impagos vencidos.
"""

import logging
from decimal import Decimal, InvalidOperation

from config import Config
from app.models.pago import (
    ESTADO_PAGO_CANCELADO,
    ESTADO_PAGO_COMPLETADO,
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
from app.utils.moneda import cop_a_usd, obtener_tasa_cop_usd

# Logger del módulo para trazabilidad de órdenes, capturas y reembolsos
logger = logging.getLogger(__name__)


def _minutos_expiracion(minutos=None):
    """
    Resuelve el tiempo límite (en minutos) para pagar un pedido pendiente.

    Prioriza el argumento `minutos` si es un entero positivo válido; de lo contrario
    lee `Config.PAGO_EXPIRA_MINUTOS` (con respaldo de 30 minutos).

    Args:
        minutos (int | str | None): Sobrescritura opcional del tiempo de expiración.

    Returns:
        int: Cantidad positiva de minutos antes de considerar el pago expirado.
    """
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
    """
    Obtiene el código de moneda configurado para PayPal (por defecto `'USD'`).

    Returns:
        str: Código ISO de moneda en mayúsculas sin espacios.
    """
    return (getattr(Config, "PAYPAL_CURRENCY", "USD") or "USD").strip().upper()


def _pago_ha_expirado_sql(id_pedido, minutos=None):
    """
    Calcula directamente en MySQL si el pago pendiente superó el tiempo límite de expiración
    utilizando `TIMESTAMPDIFF(MINUTE, fecha_creacion, NOW())`.

    Evaluarlo en SQL evita discrepancias de zona horaria entre Python y la base de datos.

    Args:
        id_pedido (int): Identificador del pedido a verificar.
        minutos (int | None): Tiempo límite opcional en minutos.

    Returns:
        bool: `True` si los minutos transcurridos son `>= min_exp`, `False` en caso contrario.
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
    """
    Calcula el número del próximo intento de creación de orden PayPal para un pedido.

    Se usa para construir un `PayPal-Request-ID` único por intento
    (`crear-<id_pedido>-<n_intento>`), permitiendo reintentar si un intento previo falló.

    Args:
        id_pedido (int): Identificador del pedido.

    Returns:
        int: Número ordinal del siguiente intento (1 en el primer intento).
    """
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
    Inicia una orden de pago en PayPal para un pedido existente:
    - Verifica que el pedido exista y pertenezca a `id_usuario`.
    - Verifica que el pedido esté en estado pendiente y no haya expirado.
    - Verifica que el pedido tenga un pago en estado `'pendiente'`.
    - Toma el monto únicamente de `pedidos.total` en la base de datos (nunca del cliente).
    - Convierte el total de COP a USD y lo sincroniza en la tabla `pagos`.
    - Llama a `crear_orden` con `request_id` estable (`'crear-<id_pedido>-<n_intento>'`)
      y registra el `order_id` resultante en la tabla `pagos`.

    Args:
        id_usuario (int): ID del usuario autenticado que solicita iniciar el pago.
        id_pedido (int): ID del pedido a pagar.

    Returns:
        str: `order_id` generado por PayPal para aprobar en el frontend.

    Raises:
        ValueError: Si el pedido no existe, no pertenece al usuario, no está pendiente o expiró.
        PayPalError: Si falla la comunicación con la API de PayPal.
    """
    # 1. Validamos existencia y propiedad del pedido
    pedido = Pedido.obtener_por_id(id_pedido)
    if not pedido or int(pedido["id_usuario"]) != int(id_usuario):
        raise ValueError("El pedido no existe o no pertenece al usuario")

    # 2. Solo se pueden pagar pedidos en estado pendiente
    if int(pedido["id_estado"]) != ESTADO_PENDIENTE:
        raise ValueError("El pedido no está pendiente de pago")

    # 3. Verificamos que exista un registro de pago pendiente asociado
    pago = Pago.obtener_por_pedido(id_pedido)
    if not pago or pago["estado"] != ESTADO_PAGO_PENDIENTE:
        raise ValueError("El pedido no tiene un pago pendiente activo")

    # 4. Rechazamos el inicio si la ventana de pago ya expiró
    if _pago_ha_expirado_sql(id_pedido):
        raise ValueError("El tiempo para pagar este pedido ha expirado")

    # 5. Calculamos el monto en USD a partir del total autoritativo guardado en BD
    monto_bd = Decimal(str(pedido["total"]))
    moneda = _moneda_configurada()  # PAYPAL_CURRENCY (USD)
    tasa_cop_usd = obtener_tasa_cop_usd()
    monto_usd = cop_a_usd(monto_bd, tasa_cop_usd)

    # Sincronizar monto en COP, moneda PayPal, tasa y monto en USD en el pago pendiente
    Pago.crear_para_pedido(
        id_pedido=id_pedido,
        monto=monto_bd,
        moneda=moneda,
        tasa_cop_usd=tasa_cop_usd,
        monto_usd=monto_usd
    )

    # 6. Generamos `request_id` determinístico por intento y creamos la orden en PayPal
    n_intento = _contar_intentos_pago(id_pedido)
    request_id = f"crear-{id_pedido}-{n_intento}"

    order_id = paypal_client.crear_orden(
        id_pedido=id_pedido,
        monto=monto_usd,
        moneda=moneda,
        request_id=request_id,
    )
    # 7. Persistimos el `order_id` en la tabla `pagos` para validarlo luego al capturar
    Pago.registrar_orden(id_pedido, order_id)
    logger.info("Orden de PayPal creada para el pedido %s (intento %s)", id_pedido, n_intento)
    return order_id


def _reembolsar_automaticamente(id_pedido, capture_id, motivo, id_pago=None, cursor=None):
    """
    Reembolsa automáticamente una captura cuando la validación posterior o la
    confirmación del pedido falla, marca el pago como `'reembolsado'` y registra con `logger.error`.

    Si el pedido sigue en estado pendiente, lo cancela con `Pedido.actualizar_estado`
    devolviendo el stock una sola vez. Si se provee `cursor`, opera dentro de la misma
    transacción bloqueada; de lo contrario actualiza mediante los métodos de los modelos.

    Args:
        id_pedido (int): ID del pedido afectado.
        capture_id (str): ID de la captura ya cobrada en PayPal que debe revertirse.
        motivo (str): Razón técnica del reembolso automático (para auditoría en logs).
        id_pago (int | None): ID específico del registro en `pagos` (opcional).
        cursor (MySQLCursor | None): Cursor transaccional activo si se ejecuta en transacción.
    """
    logger.error(
        "Iniciando reembolso automático para pedido=%s capture_id=%s por motivo: %s",
        id_pedido,
        capture_id,
        motivo,
    )
    # Ejecutamos primero el reembolso en PayPal; si falla, propagamos la excepción para alertar
    try:
        paypal_client.reembolsar_captura(capture_id, request_id=f"reembolso-auto-{id_pedido}-{capture_id}")
    except Exception:
        logger.exception(
            "Fallo crítico al intentar reembolsar automáticamente capture_id=%s del pedido=%s",
            capture_id,
            id_pedido,
        )
        raise

    # Si estamos dentro de una transacción con cursor bloqueado, actualizamos usando el mismo cursor
    if cursor is not None:
        if id_pago is not None:
            cursor.execute(
                "UPDATE pagos SET estado = %s, paypal_capture_id = COALESCE(paypal_capture_id, %s) WHERE id_pago = %s",
                (ESTADO_PAGO_REEMBOLSADO, str(capture_id).strip(), id_pago),
            )
        else:
            cursor.execute(
                "UPDATE pagos SET estado = %s, paypal_capture_id = COALESCE(paypal_capture_id, %s) WHERE id_pedido = %s ORDER BY id_pago DESC LIMIT 1",
                (ESTADO_PAGO_REEMBOLSADO, str(capture_id).strip(), id_pedido),
            )
        # Bloqueamos la fila del pedido para verificar si aún está pendiente y cancelarlo devolviendo stock
        cursor.execute("SELECT id_estado FROM pedidos WHERE id_pedido = %s FOR UPDATE", (id_pedido,))
        pedido_actual = cursor.fetchone()
        if pedido_actual and int(pedido_actual["id_estado"]) == ESTADO_PENDIENTE:
            Pedido.actualizar_estado(id_pedido, ESTADO_CANCELADO, cursor=cursor)
            logger.info("Pedido %s cancelado y stock devuelto tras reembolso automático", id_pedido)
        return

    # Ruta sin cursor externo: marcamos el pago y cancelamos el pedido usando los modelos
    Pago.marcar(id_pedido, ESTADO_PAGO_REEMBOLSADO, capture_id=capture_id)

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
    Captura y confirma el pago de un pedido en PayPal de forma transaccional e idempotente:
    - Verifica propiedad del pedido y coincidencia del `order_id` guardado.
    - Bloquea la fila del pago (`SELECT ... FOR UPDATE`) para evitar capturas concurrentes.
    - Si el pago ya está `'completado'`, devuelve éxito de forma idempotente sin volver a llamar a PayPal.
    - Verifica que el pedido siga en estado pendiente ANTES de capturar.
    - Si PayPal rechaza con `INSTRUMENT_DECLINED`, no marca nada definitivo y devuelve
      un estado de reintento (`reintentar: True`) para el navegador.
    - Exige estado `COMPLETED`, `monto == monto_usd` del pago, `moneda == PAYPAL_CURRENCY`
      y `custom_id == str(id_pedido)`.
    - Si alguna verificación posterior a la captura falla o el pedido no puede pasar a confirmado,
      reembolsa automáticamente la captura, marca el pago `'reembolsado'`, registra con `logger.error`
      incluyendo `capture_id` y lanza `ValueError`.

    Args:
        id_usuario (int): ID del usuario autenticado.
        id_pedido (int): ID del pedido a cobrar.
        order_id (str): ID de la orden aprobada por el usuario en PayPal.

    Returns:
        dict: Resultado de la operación (`exito`, `reintentar`, `estado`, `id_pedido`,
            `capture_id`, `ya_completado` o `codigo`/`mensaje` si fue declinado).

    Raises:
        ValueError: Si los datos son inválidos, el pedido no corresponde o la captura no pasó validación.
        PayPalError: Si ocurre un error de comunicación con PayPal distinto a `INSTRUMENT_DECLINED`.
    """
    if not order_id or not str(order_id).strip():
        raise ValueError("El identificador de la orden de PayPal es obligatorio")
    order_id_str = str(order_id).strip()

    # Validamos existencia y propiedad del pedido antes de abrir transacción
    pedido = Pedido.obtener_por_id(id_pedido)
    if not pedido or int(pedido["id_usuario"]) != int(id_usuario):
        raise ValueError("El pedido no existe o no pertenece al usuario")

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Iniciamos transacción y bloqueamos el registro de pago con `FOR UPDATE`
        conn.start_transaction()
        cursor.execute(
            """
            SELECT id_pago, id_pedido, proveedor, paypal_order_id, paypal_capture_id,
                   monto, moneda, estado, tasa_cop_usd, monto_usd
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
            conn.rollback()
            raise ValueError("No se encontró un registro de pago para este pedido")

        # Verificamos que el `order_id` recibido coincida con el registrado al iniciar el pago
        if pago.get("paypal_order_id") != order_id_str:
            conn.rollback()
            raise ValueError("El identificador de la orden no coincide con el registrado para este pedido")

        # Idempotencia: si el pago ya fue completado previamente, devolver éxito sin llamar a PayPal
        if pago["estado"] == ESTADO_PAGO_COMPLETADO:
            conn.commit()
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
            conn.rollback()
            raise ValueError("El pedido ya no está en estado pendiente y no puede ser cobrado")

        if pago["estado"] != ESTADO_PAGO_PENDIENTE:
            conn.rollback()
            raise ValueError(f"El pago no está en estado pendiente (estado actual: {pago['estado']})")

        # Ejecutamos la captura en PayPal con `request_id` determinístico por orden
        request_id = f"capturar-{id_pedido}-{order_id_str}"
        try:
            resultado = paypal_client.capturar_orden(order_id_str, request_id=request_id)
        except PayPalError as exc:
            conn.rollback()
            # Si la tarjeta/saldo fue rechazado, permitimos al usuario elegir otro medio en el checkout
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

        # Normalizamos los campos devueltos por la captura de PayPal
        estado_cap = (resultado.get("estado") or "").strip().upper()
        capture_id = (resultado.get("capture_id") or "").strip()
        monto_cap_raw = resultado.get("monto")
        moneda_cap = (resultado.get("moneda") or "").strip().upper()
        custom_id_cap = str(resultado.get("custom_id") or "").strip()

        # Obtener monto esperado en USD guardado en pagos y moneda configurada
        monto_usd_guardado = pago.get("monto_usd")
        if monto_usd_guardado is None:
            conn.rollback()
            raise ValueError("El registro de pago no tiene monto_usd para validar la captura")

        try:
            monto_esperado = Decimal(str(monto_usd_guardado)).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError) as exc:
            conn.rollback()
            raise ValueError(f"El monto_usd registrado en el pago es inválido: {monto_usd_guardado}") from exc

        moneda_esperada = _moneda_configurada()

        # Si la captura no quedó en COMPLETED o falta `capture_id`, registramos detalles y abortamos
        if estado_cap != "COMPLETED" or not capture_id:
            status_details = resultado.get("status_details")
            processor_response = resultado.get("processor_response")
            campos_principales = list(resultado.keys())

            logger.warning(
                "La captura de PayPal no se completó para el pedido=%s (orden=%s). "
                "Estado: %s, capture_id: %s, status_details: %s, processor_response: %s, "
                "campos_respuesta: %s, monto_esperado: %s %s (PAYPAL_CURRENCY), monto_recibido: %s %s",
                id_pedido,
                order_id_str,
                estado_cap or "desconocido",
                capture_id or "ninguno",
                status_details,
                processor_response,
                campos_principales,
                monto_esperado,
                moneda_esperada,
                monto_cap_raw,
                moneda_cap,
            )
            conn.rollback()
            raise ValueError(f"La captura de PayPal no se completó (estado: {estado_cap or 'desconocido'})")

        try:
            monto_capturado = Decimal(str(monto_cap_raw)).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError):
            monto_capturado = Decimal("-1.00")

        # Validar integridad de monto (en USD), moneda y custom_id tras la captura
        motivo_invalido = None
        if monto_capturado != monto_esperado:
            motivo_invalido = f"El monto capturado ({monto_capturado} USD) no coincide con el total esperado en USD ({monto_esperado} USD)"
        elif moneda_cap != moneda_esperada:
            motivo_invalido = f"La moneda capturada ({moneda_cap}) no coincide con la moneda configurada ({moneda_esperada})"
        elif custom_id_cap != str(id_pedido):
            motivo_invalido = f"El custom_id capturado ({custom_id_cap}) no coincide con el pedido ({id_pedido})"

        # Si hubo discrepancia en monto, moneda o pedido, reembolsamos de inmediato
        if motivo_invalido:
            try:
                _reembolsar_automaticamente(
                    id_pedido,
                    capture_id,
                    motivo_invalido,
                    id_pago=pago["id_pago"],
                    cursor=cursor,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            raise ValueError(motivo_invalido)

        # Confirmar captura en `pagos` y confirmar `pedidos` dentro de la misma transacción bloqueada
        try:
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
                    order_id_str,
                    capture_id,
                    Decimal(str(pago["monto"])),
                    moneda_cap,
                    monto_capturado,
                    pago["id_pago"],
                ),
            )
            Pedido.actualizar_estado(id_pedido, ESTADO_CONFIRMADO, cursor=cursor)
            conn.commit()
        except Exception as exc:
            # Si falla la confirmación en BD después de cobrar en PayPal, reembolsamos automáticamente
            try:
                _reembolsar_automaticamente(
                    id_pedido,
                    capture_id,
                    f"No se pudo confirmar el pedido tras capturar el pago: {exc}",
                    id_pago=pago["id_pago"],
                    cursor=cursor,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            raise ValueError(f"No se pudo confirmar el pedido tras el cobro; se realizó el reembolso automático: {exc}") from exc
    finally:
        cursor.close()
        conn.close()

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
    Cancela un pedido gestionando el reembolso en PayPal si corresponde:
    - Si el pedido tiene un pago `'completado'`, primero reembolsa en PayPal y marca el pago `'reembolsado'`.
    - Si el reembolso falla, NO cancela el pedido y propaga el error.
    - Si el pago estaba `'pendiente'`, lo marca `'cancelado'`.
    - Finalmente llama a `Pedido.actualizar_estado(id_pedido, ESTADO_CANCELADO)` que devuelve el stock una sola vez.

    Args:
        id_pedido (int): Identificador del pedido a cancelar.

    Returns:
        bool: `True` si la cancelación (y el reembolso, si aplicaba) finalizó correctamente.

    Raises:
        ValueError: Si el pedido no existe, ya está cancelado, la transición no es válida
            o un pago completado carece de `paypal_capture_id`.
        PayPalError: Si falla la llamada de reembolso en PayPal.
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
        # Si ya se había cobrado, debemos reembolsar en PayPal antes de cancelar el pedido
        if pago["estado"] == ESTADO_PAGO_COMPLETADO:
            capture_id = pago.get("paypal_capture_id")
            if not capture_id:
                raise ValueError("El pago figura como completado pero no tiene capture_id para reembolsar")
            request_id = f"reembolso-cancelacion-{id_pedido}-{capture_id}"
            paypal_client.reembolsar_captura(capture_id, request_id=request_id)
            Pago.marcar(id_pedido, ESTADO_PAGO_REEMBOLSADO, capture_id=capture_id)
            logger.info("Reembolso completado para pedido=%s capture_id=%s", id_pedido, capture_id)
        # Si el pago nunca se completó, simplemente lo marcamos como cancelado
        elif pago["estado"] == ESTADO_PAGO_PENDIENTE:
            Pago.marcar(id_pedido, ESTADO_PAGO_CANCELADO)

    # Cancelamos el pedido y devolvemos el stock al inventario
    Pedido.actualizar_estado(id_pedido, ESTADO_CANCELADO)
    return True


def cancelar_impagos_vencidos(minutos=None):
    """
    Cancela (con `Pedido.actualizar_estado`, que devuelve el stock una sola vez)
    los pedidos en estado pendiente cuyo pago PayPal siga en `'pendiente'` y tenga
    más de `PAGO_EXPIRA_MINUTOS` minutos, marcando el pago como `'cancelado'`.

    Es idempotente ante llamadas repetidas y revalida el estado actual de cada
    pedido antes de cancelarlo.

    Args:
        minutos (int | None): Tiempo de expiración opcional en minutos; si es `None`,
            usa `Config.PAGO_EXPIRA_MINUTOS` (30 por defecto).

    Returns:
        int: Cantidad total de pedidos vencidos que fueron cancelados.
    """
    min_exp = _minutos_expiracion(minutos)
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Buscamos pedidos pendientes con pago PayPal pendiente cuya antigüedad supere `min_exp`
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

    # Eliminamos posibles IDs duplicados preservando el orden ascendente
    pedidos_vencidos = list(dict.fromkeys(f["id_pedido"] for f in filas))
    cancelados = 0

    for id_pedido in pedidos_vencidos:
        try:
            # Revalidamos estado actual justo antes de cancelar (evita condiciones de carrera)
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
