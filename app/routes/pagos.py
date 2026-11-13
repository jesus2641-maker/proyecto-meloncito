"""
Rutas de Pagos con PayPal - Integración Sandbox / Live
Maneja la vista de pago, creación de orden en PayPal y captura de la transacción.
"""

import logging
from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from config import Config
from app.models.pago import (
    ESTADO_PAGO_CANCELADO,
    ESTADO_PAGO_COMPLETADO,
    ESTADO_PAGO_REEMBOLSADO,
    Pago,
)
from app.models.pedido import (
    ESTADO_CANCELADO,
    ESTADO_CONFIRMADO,
    Pedido,
    PedidoDetalle,
)
from app.services.pagos_paypal import (
    cancelar_impagos_vencidos,
    capturar_pago,
    iniciar_pago,
)
from app.utils.decoradores import requiere_login
from app.utils.email_service import enviar_confirmacion_pedido_por_id
from app.utils.paypal_client import PayPalError, paypal_configurado

logger = logging.getLogger(__name__)

pagos_bp = Blueprint("pagos", __name__, url_prefix="/pagos")


@pagos_bp.route("/paypal/<int:id_pedido>", methods=["GET"])
@requiere_login(mensaje="Inicia sesión para realizar el pago")
def paypal_checkout(id_pedido):
    """
    Vista de pago con PayPal:
    - Cancela pedidos impagos vencidos.
    - Valida que el pedido exista y pertenezca al usuario en sesión (404 si no).
    - Si ya está pagado/confirmado, redirige a confirmación.
    - Si está cancelado o expiró, muestra flash de aviso y redirige al catálogo.
    - Renderiza pagos/paypal.html con datos del pedido y el botón de PayPal.
    """
    cancelar_impagos_vencidos()

    id_usuario = session.get("id_usuario")
    pedido = Pedido.obtener_por_id(id_pedido)

    if not pedido or int(pedido["id_usuario"]) != int(id_usuario):
        abort(404)

    pago = Pago.obtener_por_pedido(id_pedido)

    # Si ya está confirmado o completado el pago -> confirmación
    if int(pedido["id_estado"]) == ESTADO_CONFIRMADO or (
        pago and pago.get("estado") == ESTADO_PAGO_COMPLETADO
    ):
        return redirect(url_for("carrito.confirmacion", id_pedido=id_pedido))

    # Si está cancelado o el pago está cancelado/reembolsado
    if int(pedido["id_estado"]) == ESTADO_CANCELADO or (
        pago and pago.get("estado") in (ESTADO_PAGO_CANCELADO, ESTADO_PAGO_REEMBOLSADO)
    ):
        flash(
            "Este pedido fue cancelado o el tiempo para realizar el pago ha expirado.",
            "warning",
        )
        return redirect(url_for("productos.catalogo"))

    detalles = PedidoDetalle.listar_por_pedido(id_pedido)
    paypal_activo = paypal_configurado()

    from app.utils.moneda import cop_a_usd, obtener_tasa_cop_usd
    try:
        tasa_actual = obtener_tasa_cop_usd()
    except ValueError:
        tasa_actual = None

    tasa_usada = (pago.get("tasa_cop_usd") if pago and pago.get("tasa_cop_usd") else tasa_actual)
    monto_usd = None
    if tasa_usada:
        try:
            monto_usd = cop_a_usd(pedido["total"], tasa_usada)
        except Exception:
            monto_usd = None

    return render_template(
        "pagos/paypal.html",
        pedido=pedido,
        detalles=detalles,
        pago=pago,
        paypal_client_id=Config.PAYPAL_CLIENT_ID,
        paypal_currency=Config.PAYPAL_CURRENCY,
        paypal_activo=paypal_activo,
        tasa_cop_usd=tasa_usada,
        monto_usd=monto_usd,
    )


@pagos_bp.route("/paypal/<int:id_pedido>/crear", methods=["POST"])
@requiere_login()
def crear_orden(id_pedido):
    """
    Inicia la orden en PayPal Orders v2 y responde el id de orden a PayPal JS SDK.
    """
    id_usuario = session.get("id_usuario")
    try:
        order_id = iniciar_pago(id_usuario, id_pedido)
        return jsonify({"id": order_id}), 200
    except ValueError as e:
        logger.warning("Error de validación al crear orden para pedido %s: %s", id_pedido, e)
        return jsonify({"error": str(e)}), 400
    except PayPalError as e:
        logger.exception("Error de PayPal al crear orden para pedido %s: %s", id_pedido, e)
        status_code = 400 if e.status_code and 400 <= e.status_code < 500 else 502
        return jsonify({"error": e.mensaje or "Error de comunicación con PayPal"}), status_code
    except Exception:
        logger.exception("Error no controlado al iniciar pago para pedido %s", id_pedido)
        return jsonify({"error": "No se pudo iniciar el pago con PayPal"}), 500


@pagos_bp.route("/paypal/<int:id_pedido>/capturar", methods=["POST"])
@requiere_login()
def capturar_orden(id_pedido):
    """
    Captura la orden autorizada por el usuario en el popup de PayPal:
    - Si el medio fue declinado (INSTRUMENT_DECLINED), solicita reintentar con otra tarjeta.
    - Si la captura tuvo éxito, despacha correo de confirmación y devuelve URL de redirección.
    """
    id_usuario = session.get("id_usuario")
    data = request.get_json(silent=True) or {}
    order_id = data.get("orderID") or data.get("order_id")

    if not order_id:
        return jsonify({"ok": False, "error": "orderID es requerido"}), 400

    try:
        resultado = capturar_pago(id_usuario, id_pedido, order_id)

        if resultado.get("reintentar"):
            return jsonify({
                "ok": False,
                "reintentar": True,
                "codigo": resultado.get("codigo"),
                "error": resultado.get("mensaje") or "Medio de pago rechazado por PayPal. Puedes reintentar con otra tarjeta.",
            }), 422

        # Captura exitosa
        enviar_confirmacion_pedido_por_id(id_pedido, id_usuario)
        redirect_url = url_for("carrito.confirmacion", id_pedido=id_pedido)
        return jsonify({
            "ok": True,
            "reintentar": False,
            "redirect": redirect_url,
        }), 200
    except ValueError as e:
        logger.warning("Error de validación al capturar pago para pedido %s: %s", id_pedido, e)
        return jsonify({"ok": False, "error": str(e)}), 400
    except PayPalError as e:
        logger.exception("Error de PayPal al capturar orden %s: %s", order_id, e)
        status_code = 400 if e.status_code and 400 <= e.status_code < 500 else 502
        return jsonify({"ok": False, "error": e.mensaje or "Error al procesar la captura con PayPal"}), status_code
    except Exception:
        logger.exception("Error no controlado al capturar pago para pedido %s", id_pedido)
        return jsonify({"ok": False, "error": "No se pudo completar el pago con PayPal"}), 500
