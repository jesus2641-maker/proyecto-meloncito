from flask import Blueprint, render_template, session, request, redirect, url_for, flash, abort
from app.models.direccion import Direccion
from app.models.metodo_pago import MetodoPago
from app.models.pedido import Pedido, PedidoDetalle, ESTADO_PENDIENTE, ESTADO_CANCELADO
from app.models.pago import Pago, ESTADO_PAGO_PENDIENTE, ESTADO_PAGO_CANCELADO
from app.services.pagos_paypal import cancelar_impagos_vencidos
from app.utils.decoradores import requiere_login
from app.utils.validaciones import (
    validar_tipo_pago,
    validar_detalle_pago,
    validar_direccion,
)

cuenta_bp = Blueprint("cuenta", __name__, url_prefix="/cuenta")


@cuenta_bp.route("/")
@requiere_login(mensaje="Debes iniciar sesión para acceder a tu cuenta")
def index():
    cancelar_impagos_vencidos()
    id_usuario = session["id_usuario"]
    direcciones = Direccion.listar_por_usuario(id_usuario)
    metodos_pago = MetodoPago.listar_por_usuario(id_usuario)
    pedidos = Pedido.listar_por_usuario(id_usuario)
    return render_template(
        "cuenta/index.html",
        direcciones=direcciones,
        metodos_pago=metodos_pago,
        pedidos=pedidos
    )


# --- DIRECCIONES ---
@cuenta_bp.route("/direcciones")
@requiere_login()
def direcciones():
    id_usuario = session["id_usuario"]
    direcciones = Direccion.listar_por_usuario(id_usuario)
    return render_template("cuenta/direcciones.html", direcciones=direcciones)


@cuenta_bp.route("/direcciones/nueva", methods=["GET", "POST"])
@requiere_login()
def nueva_direccion():
    if request.method == "POST":
        id_usuario = session["id_usuario"]
        alias = request.form.get("alias", "").strip() or None
        linea_direccion = request.form.get("linea_direccion", "").strip()
        ciudad = request.form.get("ciudad", "").strip()
        departamento = request.form.get("departamento", "").strip() or None
        codigo_postal = request.form.get("codigo_postal", "").strip() or None
        es_principal = 1 if request.form.get("es_principal") else 0

        dir_ok, dir_err = validar_direccion(
            linea_direccion=linea_direccion,
            ciudad=ciudad,
            departamento=departamento,
            codigo_postal=codigo_postal,
            alias=alias,
        )
        if not dir_ok:
            flash(dir_err, "danger")
            return render_template("cuenta/nueva_direccion.html")

        Direccion.crear(
            id_usuario=id_usuario,
            linea_direccion=linea_direccion,
            ciudad=ciudad,
            departamento=departamento,
            codigo_postal=codigo_postal,
            alias=alias,
            es_principal=es_principal
        )
        flash("Dirección guardada correctamente", "success")
        return redirect(url_for("cuenta.direcciones"))

    return render_template("cuenta/nueva_direccion.html")


@cuenta_bp.route("/direcciones/eliminar", methods=["POST"])
@requiere_login()
def eliminar_direccion():
    id_usuario = session["id_usuario"]
    id_direccion = request.form.get("id_direccion", type=int)

    if id_direccion:
        Direccion.eliminar(id_direccion, id_usuario)
        flash("Dirección eliminada correctamente", "info")

    return redirect(url_for("cuenta.direcciones"))


# --- MÉTODOS DE PAGO ---
@cuenta_bp.route("/metodos-pago")
@requiere_login()
def metodos_pago():
    id_usuario = session["id_usuario"]
    metodos = MetodoPago.listar_por_usuario(id_usuario)
    return render_template("cuenta/metodos_pago.html", metodos_pago=metodos)


@cuenta_bp.route("/metodos-pago/nuevo", methods=["GET", "POST"])
@requiere_login()
def nuevo_metodo_pago():
    if request.method == "POST":
        id_usuario = session["id_usuario"]
        tipo = request.form.get("tipo", "").strip()
        detalle = request.form.get("detalle", "").strip() or None
        es_predeterminado = 1 if request.form.get("es_predeterminado") else 0

        tipo_ok, tipo_err = validar_tipo_pago(tipo)
        if not tipo_ok:
            flash(tipo_err, "danger")
            return render_template("cuenta/nuevo_metodo_pago.html")

        det_ok, det_err = validar_detalle_pago(detalle)
        if not det_ok:
            flash(det_err, "danger")
            return render_template("cuenta/nuevo_metodo_pago.html")

        MetodoPago.crear(
            id_usuario=id_usuario,
            tipo=tipo,
            detalle=detalle,
            es_predeterminado=es_predeterminado
        )
        flash("Método de pago guardado correctamente", "success")
        return redirect(url_for("cuenta.metodos_pago"))

    return render_template("cuenta/nuevo_metodo_pago.html")


@cuenta_bp.route("/metodos-pago/eliminar", methods=["POST"])
@requiere_login()
def eliminar_metodo_pago():
    id_usuario = session["id_usuario"]
    id_metodo = request.form.get("id_metodo_pago", type=int)

    if id_metodo:
        MetodoPago.eliminar(id_metodo, id_usuario)
        flash("Método de pago eliminado correctamente", "info")

    return redirect(url_for("cuenta.metodos_pago"))


# --- PEDIDOS ---
@cuenta_bp.route("/pedidos")
@requiere_login()
def pedidos():
    cancelar_impagos_vencidos()
    id_usuario = session["id_usuario"]
    pedidos = Pedido.listar_por_usuario(id_usuario)
    return render_template("cuenta/pedidos.html", pedidos=pedidos)


@cuenta_bp.route("/pedidos/<int:id_pedido>")
@requiere_login()
def detalle_pedido(id_pedido):
    id_usuario = session["id_usuario"]
    pedido = Pedido.obtener_por_id(id_pedido)

    if not pedido or int(pedido["id_usuario"]) != int(id_usuario):
        abort(404)

    detalles = PedidoDetalle.listar_por_pedido(id_pedido)
    pago = Pago.obtener_por_pedido(id_pedido)
    return render_template(
        "cuenta/detalle_pedido.html",
        pedido=pedido,
        detalles=detalles,
        pago=pago,
    )


@cuenta_bp.route("/pedidos/<int:id_pedido>/cancelar", methods=["POST"])
@requiere_login()
def cancelar_pedido(id_pedido):
    """
    Cancela un pedido del usuario actual si está pendiente y su pago PayPal sigue pendiente.
    Libera el stock y marca el pago como cancelado.
    """
    id_usuario = session["id_usuario"]
    pedido = Pedido.obtener_por_id(id_pedido)

    if not pedido or int(pedido["id_usuario"]) != int(id_usuario):
        abort(404)

    pago = Pago.obtener_por_pedido(id_pedido)

    if int(pedido["id_estado"]) != ESTADO_PENDIENTE or not pago or pago.get("estado") != ESTADO_PAGO_PENDIENTE:
        flash("Solo puedes cancelar pedidos pendientes que tengan un pago pendiente.", "warning")
        return redirect(url_for("cuenta.detalle_pedido", id_pedido=id_pedido))

    try:
        Pedido.actualizar_estado(id_pedido, ESTADO_CANCELADO)
        Pago.marcar(id_pedido, ESTADO_PAGO_CANCELADO)
        flash("Tu pedido ha sido cancelado exitosamente y el stock ha sido liberado.", "info")
    except Exception as e:
        flash(f"No se pudo cancelar el pedido: {e}", "danger")

    return redirect(url_for("cuenta.detalle_pedido", id_pedido=id_pedido))
