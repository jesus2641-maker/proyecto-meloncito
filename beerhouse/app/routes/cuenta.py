from flask import Blueprint, render_template, session, request, redirect, url_for, flash, abort
from app.models.direccion import Direccion
from app.models.metodo_pago import MetodoPago
from app.models.pedido import Pedido, PedidoDetalle

cuenta_bp = Blueprint("cuenta", __name__, url_prefix="/cuenta")


def _requiere_sesion():
    return "id_usuario" in session


@cuenta_bp.before_request
def verificar_autenticacion():
    if not _requiere_sesion():
        flash("Debes iniciar sesión para acceder a tu cuenta", "warning")
        return redirect(url_for("auth.login"))


@cuenta_bp.route("/")
def index():
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
def direcciones():
    id_usuario = session["id_usuario"]
    direcciones = Direccion.listar_por_usuario(id_usuario)
    return render_template("cuenta/direcciones.html", direcciones=direcciones)


@cuenta_bp.route("/direcciones/nueva", methods=["GET", "POST"])
def nueva_direccion():
    if request.method == "POST":
        id_usuario = session["id_usuario"]
        alias = request.form.get("alias", "").strip() or None
        linea_direccion = request.form.get("linea_direccion", "").strip()
        ciudad = request.form.get("ciudad", "").strip()
        departamento = request.form.get("departamento", "").strip() or None
        codigo_postal = request.form.get("codigo_postal", "").strip() or None
        es_principal = 1 if request.form.get("es_principal") else 0

        if not linea_direccion or not ciudad:
            flash("La dirección y la ciudad son obligatorias", "danger")
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
def eliminar_direccion():
    id_usuario = session["id_usuario"]
    id_direccion = request.form.get("id_direccion", type=int)

    if id_direccion:
        Direccion.eliminar(id_direccion, id_usuario)
        flash("Dirección eliminada correctamente", "info")

    return redirect(url_for("cuenta.direcciones"))


# --- MÉTODOS DE PAGO ---
@cuenta_bp.route("/metodos-pago")
def metodos_pago():
    id_usuario = session["id_usuario"]
    metodos = MetodoPago.listar_por_usuario(id_usuario)
    return render_template("cuenta/metodos_pago.html", metodos_pago=metodos)


@cuenta_bp.route("/metodos-pago/nuevo", methods=["GET", "POST"])
def nuevo_metodo_pago():
    if request.method == "POST":
        id_usuario = session["id_usuario"]
        tipo = request.form.get("tipo", "").strip()
        detalle = request.form.get("detalle", "").strip() or None
        es_predeterminado = 1 if request.form.get("es_predeterminado") else 0

        if not tipo:
            flash("El tipo de método de pago es obligatorio", "danger")
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
def eliminar_metodo_pago():
    id_usuario = session["id_usuario"]
    id_metodo = request.form.get("id_metodo_pago", type=int)

    if id_metodo:
        MetodoPago.eliminar(id_metodo, id_usuario)
        flash("Método de pago eliminado correctamente", "info")

    return redirect(url_for("cuenta.metodos_pago"))


# --- PEDIDOS ---
@cuenta_bp.route("/pedidos")
def pedidos():
    id_usuario = session["id_usuario"]
    pedidos = Pedido.listar_por_usuario(id_usuario)
    return render_template("cuenta/pedidos.html", pedidos=pedidos)


@cuenta_bp.route("/pedidos/<int:id_pedido>")
def detalle_pedido(id_pedido):
    id_usuario = session["id_usuario"]
    pedido = Pedido.obtener_por_id(id_pedido)

    if not pedido or pedido["id_usuario"] != id_usuario:
        abort(404)

    detalles = PedidoDetalle.listar_por_pedido(id_pedido)
    return render_template("cuenta/detalle_pedido.html", pedido=pedido, detalles=detalles)
