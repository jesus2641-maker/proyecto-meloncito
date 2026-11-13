"""
Blueprint de pagos con PayPal Orders v2
Maneja las rutas:
- GET  /paypal/checkout      : Renderiza checkout.html con el SDK de PayPal
- POST /paypal/create-order  : Crea la orden en PayPal con total calculado desde la BD
- POST /paypal/capture-order : Captura el pago, ejecuta la transacción SQL y vacía el carrito
"""

import os
import logging
from decimal import Decimal
from flask import Blueprint, render_template, session, jsonify, request, redirect, url_for, flash

from app.services import paypal_service
from app.models.carrito import Carrito
from app.utils.decoradores import requiere_login
from app.utils.db import get_connection

logger = logging.getLogger(__name__)

paypal_bp = Blueprint("paypal_v2", __name__, url_prefix="/paypal")


def _obtener_carrito_y_total_bd(id_usuario):
    """
    Obtiene el carrito, los items y calcula el total directamente desde la base de datos.
    Nunca confía en datos enviados desde el cliente.

    Returns:
        tuple: (carrito, items, total_decimal)
    """
    carrito = Carrito.obtener_o_crear(id_usuario)
    items = Carrito.obtener_items(carrito["id_carrito"])

    total = Decimal("0.00")
    for item in items:
        precio_unitario = Decimal(str(item["precio_oferta"] if item.get("precio_oferta") else item["precio"]))
        total += precio_unitario * int(item["cantidad"])

    return carrito, items, total.quantize(Decimal("0.01"))


def _obtener_direccion_principal(id_usuario):
    """
    Obtiene la dirección principal del usuario (es_principal = 1).
    Si no tiene marcada una como principal, toma la primera registrada.
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT * FROM direcciones
           WHERE id_usuario = %s
           ORDER BY es_principal DESC, id_direccion ASC
           LIMIT 1""",
        (id_usuario,)
    )
    direccion = cursor.fetchone()
    cursor.close()
    conn.close()
    return direccion


@paypal_bp.route("/checkout", methods=["GET"])
@requiere_login(mensaje="Inicia sesión para completar tu compra con PayPal")
def checkout():
    """
    Renderiza la vista de checkout con el botón oficial del SDK de PayPal.
    Valida que el carrito tenga productos y que el usuario tenga una dirección registrada.
    """
    id_usuario = session["id_usuario"]
    carrito, items, total = _obtener_carrito_y_total_bd(id_usuario)

    if not items:
        flash("Tu carrito está vacío. Agrega productos antes de continuar.", "warning")
        return redirect(url_for("carrito.ver_carrito"))

    direccion = _obtener_direccion_principal(id_usuario)
    if not direccion:
        flash("Debes registrar una dirección de entrega antes de pagar.", "warning")
        return redirect(url_for("cuenta.nueva_direccion"))

    client_id = os.getenv("PAYPAL_CLIENT_ID", "").strip()
    currency = (os.getenv("PAYPAL_CURRENCY", "USD") or "USD").strip().upper()

    return render_template(
        "checkout.html",
        paypal_client_id=client_id,
        currency=currency,
        items=items,
        total=total,
        direccion=direccion,
    )


@paypal_bp.route("/create-order", methods=["POST"])
@requiere_login()
def create_order():
    """
    Crea la orden en PayPal Orders v2.
    - Obtiene el total exclusivamente desde la base de datos.
    - Valida stock disponible de cada variante antes de proceder.
    - Guarda el order_id en la sesión para posterior validación en la captura.
    """
    id_usuario = session.get("id_usuario")
    if not id_usuario:
        return jsonify({"error": "Sesión inválida o expirada"}), 401

    carrito, items, total = _obtener_carrito_y_total_bd(id_usuario)

    if not items or total <= Decimal("0.00"):
        return jsonify({"error": "El carrito está vacío o no contiene productos válidos."}), 400

    # Validar stock disponible para cada ítem antes de crear la orden
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        for item in items:
            cursor.execute(
                "SELECT stock, presentacion FROM variantes_producto WHERE id_variante = %s",
                (item["id_variante"],)
            )
            v = cursor.fetchone()
            stock_actual = int(v["stock"]) if v else 0
            if stock_actual < int(item["cantidad"]):
                return jsonify({
                    "error": (
                        f"Stock insuficiente para '{item['nombre_producto']}' ({item.get('presentacion', '')}). "
                        f"Disponible: {stock_actual}, solicitado: {item['cantidad']}."
                    )
                }), 400
    finally:
        cursor.close()
        conn.close()

    currency = (os.getenv("PAYPAL_CURRENCY", "USD") or "USD").strip().upper()

    try:
        orden = paypal_service.create_order(
            total=total,
            currency=currency,
            reference_id=str(carrito["id_carrito"]),
        )
        order_id = orden.get("id")
        if not order_id:
            logger.error("PayPal no devolvió un ID de orden: %s", orden)
            return jsonify({"error": "Respuesta inesperada al crear la orden de PayPal."}), 502

        # Guardar en sesión para asegurar que la captura corresponda a esta orden
        session["paypal_order_id"] = order_id
        return jsonify({"orderID": order_id})

    except Exception as exc:
        logger.exception("Error al crear la orden en PayPal: %s", exc)
        return jsonify({"error": "No fue posible comunicarse con la pasarela de PayPal. Intenta más tarde."}), 502


@paypal_bp.route("/capture-order", methods=["POST"])
@requiere_login()
def capture_order():
    """
    Captura la orden autorizada en PayPal.
    - Valida que el order_id coincida con el guardado en la sesión.
    - Captura el pago con la API de PayPal.
    - Si el status es 'COMPLETED':
      a) Inserta el pedido en 'pedidos' con id_estado = 2 ('confirmado')
      b) Descuenta stock atómicamente en 'variantes_producto'
      c) Inserta detalles en 'pedido_detalle'
      d) Guarda el transaction_id en 'pagos' (paypal_capture_id)
      e) Vacía el carrito del usuario
      f) Todo dentro de una transacción SQL atómica (commit o rollback)
    - Si la transacción SQL falla después de capturar, reembolsa automáticamente.
    """
    id_usuario = session.get("id_usuario")
    if not id_usuario:
        return jsonify({"error": "Sesión inválida"}), 401

    data = request.get_json(silent=True) or {}
    order_id = (data.get("orderID") or data.get("order_id") or "").strip()
    session_order_id = session.get("paypal_order_id")

    if not order_id or not session_order_id or order_id != session_order_id:
        logger.warning(
            "Intento de captura inválido: order_id recibido=%s, en sesión=%s",
            order_id, session_order_id
        )
        return jsonify({"error": "El ID de la orden no coincide con la sesión actual."}), 400

    carrito, items, total = _obtener_carrito_y_total_bd(id_usuario)
    if not items:
        return jsonify({"error": "El carrito está vacío."}), 400

    currency = (os.getenv("PAYPAL_CURRENCY", "USD") or "USD").strip().upper()

    # 1. Capturar orden contra la API de PayPal
    try:
        datos_captura = paypal_service.capture_order(order_id)
    except Exception as exc:
        logger.exception("Error al capturar orden %s en PayPal: %s", order_id, exc)
        return jsonify({"error": "Error al capturar el pago en PayPal. Revisa el estado de tu cuenta."}), 502

    status = datos_captura.get("status")
    if status != "COMPLETED":
        logger.error("La orden %s no quedó COMPLETED. Estado devuelto: %s", order_id, status)
        return jsonify({"error": f"El pago no pudo completarse. Estado: {status}"}), 400

    # Extraer el ID de captura (transaction_id)
    capture_id = None
    try:
        units = datos_captura.get("purchase_units", [])
        if units:
            captures = units[0].get("payments", {}).get("captures", [])
            if captures:
                capture_id = captures[0].get("id")
    except Exception:
        pass
    if not capture_id:
        capture_id = datos_captura.get("id")

    # 2. Transacción SQL atómica para persistir pedido y descontar inventario
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        conn.start_transaction()

        # a) Obtener dirección principal
        cursor.execute(
            """SELECT id_direccion FROM direcciones
               WHERE id_usuario = %s
               ORDER BY es_principal DESC, id_direccion ASC
               LIMIT 1""",
            (id_usuario,)
        )
        dir_fila = cursor.fetchone()
        if not dir_fila:
            raise RuntimeError("No se encontró una dirección válida para asociar al pedido.")
        id_direccion = dir_fila["id_direccion"]

        # b) Obtener o crear método de pago 'PayPal'
        cursor.execute(
            "SELECT id_metodo_pago FROM metodos_pago WHERE id_usuario = %s AND tipo = 'PayPal' LIMIT 1",
            (id_usuario,)
        )
        mp_fila = cursor.fetchone()
        if mp_fila:
            id_metodo_pago = mp_fila["id_metodo_pago"]
        else:
            cursor.execute(
                """INSERT INTO metodos_pago (id_usuario, tipo, detalle, es_predeterminado)
                   VALUES (%s, 'PayPal', 'Pago en línea con PayPal', 0)""",
                (id_usuario,)
            )
            id_metodo_pago = cursor.lastrowid

        # c) Descontar stock atómicamente con control de concurrencia
        for item in items:
            cursor.execute(
                """UPDATE variantes_producto
                   SET stock = stock - %s
                   WHERE id_variante = %s AND stock >= %s""",
                (item["cantidad"], item["id_variante"], item["cantidad"])
            )
            if cursor.rowcount == 0:
                raise RuntimeError(
                    f"Stock insuficiente al confirmar la variante {item['id_variante']} ({item.get('presentacion', '')})"
                )

        # d) Insertar pedido con id_estado = 2 ('confirmado')
        cursor.execute(
            """INSERT INTO pedidos (id_usuario, id_direccion, id_metodo_pago, id_estado, total)
               VALUES (%s, %s, %s, 2, %s)""",
            (id_usuario, id_direccion, id_metodo_pago, total)
        )
        id_pedido = cursor.lastrowid

        # e) Insertar detalle del pedido
        for item in items:
            precio_unit = Decimal(str(item["precio_oferta"] if item.get("precio_oferta") else item["precio"]))
            cursor.execute(
                """INSERT INTO pedido_detalle (id_pedido, id_variante, cantidad, precio_unitario)
                   VALUES (%s, %s, %s, %s)""",
                (id_pedido, item["id_variante"], item["cantidad"], precio_unit)
            )

        # f) Guardar transaction_id en tabla pagos (paypal_capture_id)
        cursor.execute(
            """INSERT INTO pagos (id_pedido, proveedor, paypal_order_id, paypal_capture_id, monto, moneda, estado)
               VALUES (%s, 'paypal', %s, %s, %s, %s, 'completado')""",
            (id_pedido, order_id, capture_id, total, currency)
        )

        # g) Vaciar carrito
        cursor.execute("DELETE FROM carrito_items WHERE id_carrito = %s", (carrito["id_carrito"],))

        # COMMIT
        conn.commit()
        session.pop("paypal_order_id", None)
        logger.info("Pedido #%s creado exitosamente con pago PayPal %s", id_pedido, capture_id)

    except Exception as exc:
        conn.rollback()
        logger.exception(
            "ERROR CRÍTICO: Falló la transacción SQL para orden %s tras captura %s: %s. Iniciando reembolso...",
            order_id, capture_id, exc
        )
        if capture_id:
            try:
                paypal_service.refund_capture(
                    capture_id,
                    note="Reembolso automático: fallo interno al guardar el pedido en Beer House."
                )
                logger.info("Reembolso automático de la captura %s completado con éxito.", capture_id)
            except Exception as refund_err:
                logger.critical(
                    "ALERTA MÁXIMA: Falló el reembolso automático de la captura %s: %s",
                    capture_id, refund_err
                )
        return jsonify({
            "error": "Ocurrió un error al registrar el pedido en el sistema. El cobro fue reembolsado automáticamente a tu cuenta."
        }), 500

    finally:
        cursor.close()
        conn.close()

    return jsonify({
        "status": "COMPLETED",
        "id_pedido": id_pedido,
        "redirect_url": url_for("carrito.confirmacion", id_pedido=id_pedido),
    })
