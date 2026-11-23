"""
Módulo de rutas de la cuenta del cliente (`/cuenta`).

Gestiona el panel personal del usuario autenticado: resumen general,
administración de direcciones de envío, gestión de métodos de pago guardados,
consulta del historial y detalle de pedidos, y cancelación de pedidos pendientes
con pago PayPal pendiente.
"""

# Utilidades de Flask para blueprint, renderizado, sesión, peticiones, redirecciones, mensajes y 404
from flask import Blueprint, render_template, session, request, redirect, url_for, flash, abort, current_app
# Modelos de datos relacionados con la cuenta del cliente
from app.models.direccion import Direccion
from app.models.metodo_pago import MetodoPago
from app.models.pedido import Pedido, PedidoDetalle, ESTADO_PENDIENTE, ESTADO_CANCELADO
from app.models.pago import Pago, ESTADO_PAGO_PENDIENTE, ESTADO_PAGO_CANCELADO
# Servicio para expirar/cancelar automáticamente pedidos PayPal impagos vencidos
from app.services.pagos_paypal import cancelar_impagos_vencidos
# Decorador de autenticación obligatoria
from app.utils.decoradores import requiere_login
# Funciones de validación para direcciones y métodos de pago
from app.utils.validaciones import (
    validar_tipo_pago,
    validar_detalle_pago,
    validar_direccion,
)

# Blueprint de cuenta de cliente bajo el prefijo /cuenta
cuenta_bp = Blueprint("cuenta", __name__, url_prefix="/cuenta")


@cuenta_bp.route("/")
@requiere_login(mensaje="Debes iniciar sesión para acceder a tu cuenta")
def index():
    """
    Panel principal de la cuenta del usuario (`/cuenta/`).

    Depura pedidos impagos vencidos antes de listar direcciones, métodos de pago
    y pedidos del usuario en sesión.

    Returns:
        str: Plantilla HTML `cuenta/index.html` renderizada.
    """
    # Libera stock de pedidos PayPal que hayan excedido su tiempo límite de pago
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
    """
    Lista todas las direcciones de envío guardadas por el usuario autenticado.

    Returns:
        str: Plantilla HTML `cuenta/direcciones.html` renderizada.
    """
    id_usuario = session["id_usuario"]
    direcciones = Direccion.listar_por_usuario(id_usuario)
    return render_template("cuenta/direcciones.html", direcciones=direcciones)


@cuenta_bp.route("/direcciones/nueva", methods=["GET", "POST"])
@requiere_login()
def nueva_direccion():
    """
    Formulario y procesamiento para registrar una nueva dirección de envío.

    - GET: muestra el formulario vacío.
    - POST: limpia y valida los campos de dirección, guarda el registro asociado
      al usuario en sesión y redirige al listado de direcciones.

    Returns:
        flask.Response | str: Redirección o plantilla HTML del formulario.
    """
    if request.method == "POST":
        id_usuario = session["id_usuario"]
        # Extrae campos del formulario normalizando vacíos opcionales a None
        alias = request.form.get("alias", "").strip() or None
        linea_direccion = request.form.get("linea_direccion", "").strip()
        ciudad = request.form.get("ciudad", "").strip()
        departamento = request.form.get("departamento", "").strip() or None
        codigo_postal = request.form.get("codigo_postal", "").strip() or None
        es_principal = 1 if request.form.get("es_principal") else 0

        # Valida formato y longitud de los campos de dirección
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

        # Persiste la dirección en base de datos
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
    """
    Elimina una dirección perteneciente al usuario autenticado.

    El método `Direccion.eliminar` verifica internamente que `id_usuario`
    corresponda al propietario para evitar borrados no autorizados (IDOR).

    Returns:
        flask.Response: Redirección a `cuenta.direcciones`.
    """
    id_usuario = session["id_usuario"]
    id_direccion = request.form.get("id_direccion", type=int)

    if id_direccion is None:
        flash("No se recibió la dirección a eliminar. Intenta de nuevo.", "danger")
        return redirect(url_for("cuenta.direcciones"))

    direccion = Direccion.obtener_por_id(id_direccion)
    if not direccion or direccion["id_usuario"] != id_usuario:
        flash("No se encontró la dirección o no te pertenece.", "warning")
        return redirect(url_for("cuenta.direcciones"))

    if Direccion.esta_en_uso(id_direccion):
        flash(
            "Esta dirección ya está asociada a un pedido y no se puede eliminar. Puedes agregar una nueva dirección y marcarla como principal.",
            "warning",
        )
        return redirect(url_for("cuenta.direcciones"))

    try:
        eliminado = Direccion.eliminar(id_direccion, id_usuario)
        if eliminado:
            flash("Dirección eliminada correctamente", "info")
        else:
            flash("No se encontró la dirección o no te pertenece.", "warning")
    except Exception:
        current_app.logger.exception("Error al eliminar dirección %s", id_direccion)
        flash("No se pudo eliminar la dirección. Intenta de nuevo.", "danger")

    return redirect(url_for("cuenta.direcciones"))


# --- MÉTODOS DE PAGO ---
@cuenta_bp.route("/metodos-pago")
@requiere_login()
def metodos_pago():
    """
    Lista los métodos de pago guardados por el usuario autenticado.

    Returns:
        str: Plantilla HTML `cuenta/metodos_pago.html` renderizada.
    """
    id_usuario = session["id_usuario"]
    metodos = MetodoPago.listar_por_usuario(id_usuario)
    return render_template("cuenta/metodos_pago.html", metodos_pago=metodos)


@cuenta_bp.route("/metodos-pago/nuevo", methods=["GET", "POST"])
@requiere_login()
def nuevo_metodo_pago():
    """
    Formulario y procesamiento para agregar un nuevo método de pago.

    Valida tanto el tipo de pago permitido como el detalle asociado antes de
    guardar el registro en la base de datos.

    Returns:
        flask.Response | str: Redirección o formulario HTML.
    """
    if request.method == "POST":
        id_usuario = session["id_usuario"]
        tipo = request.form.get("tipo", "").strip()
        detalle = request.form.get("detalle", "").strip() or None
        es_predeterminado = 1 if request.form.get("es_predeterminado") else 0

        # Valida que el tipo de pago sea uno de los aceptados por el sistema
        tipo_ok, tipo_err = validar_tipo_pago(tipo)
        if not tipo_ok:
            flash(tipo_err, "danger")
            return render_template("cuenta/nuevo_metodo_pago.html")

        # Valida longitud/formato del detalle del método de pago
        det_ok, det_err = validar_detalle_pago(detalle)
        if not det_ok:
            flash(det_err, "danger")
            return render_template("cuenta/nuevo_metodo_pago.html")

        # Crea el método de pago vinculado al usuario
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
    """
    Elimina un método de pago perteneciente al usuario autenticado.

    Returns:
        flask.Response: Redirección a `cuenta.metodos_pago`.
    """
    id_usuario = session["id_usuario"]
    id_metodo = request.form.get("id_metodo_pago", type=int)

    if id_metodo is None:
        flash("No se recibió el método de pago a eliminar. Intenta de nuevo.", "danger")
        return redirect(url_for("cuenta.metodos_pago"))

    metodo = MetodoPago.obtener_por_id(id_metodo)
    if not metodo or metodo["id_usuario"] != id_usuario:
        flash("No se encontró el método de pago o no te pertenece.", "warning")
        return redirect(url_for("cuenta.metodos_pago"))

    if MetodoPago.esta_en_uso(id_metodo):
        flash(
            "Este método de pago ya está asociado a un pedido y no se puede eliminar. Puedes agregar otro método y dejarlo como predeterminado.",
            "warning",
        )
        return redirect(url_for("cuenta.metodos_pago"))

    try:
        eliminado = MetodoPago.eliminar(id_metodo, id_usuario)
        if eliminado:
            flash("Método de pago eliminado correctamente", "info")
        else:
            flash("No se encontró el método de pago o no te pertenece.", "warning")
    except Exception:
        current_app.logger.exception("Error al eliminar método de pago %s", id_metodo)
        flash("No se pudo eliminar el método de pago. Intenta de nuevo.", "danger")

    return redirect(url_for("cuenta.metodos_pago"))


# --- PEDIDOS ---
@cuenta_bp.route("/pedidos")
@requiere_login()
def pedidos():
    """
    Muestra el historial completo de pedidos del usuario autenticado.

    Ejecuta primero `cancelar_impagos_vencidos()` para reflejar estados
    actualizados de órdenes PayPal expiradas.

    Returns:
        str: Plantilla HTML `cuenta/pedidos.html` renderizada.
    """
    cancelar_impagos_vencidos()
    id_usuario = session["id_usuario"]
    pedidos = Pedido.listar_por_usuario(id_usuario)
    return render_template("cuenta/pedidos.html", pedidos=pedidos)


@cuenta_bp.route("/pedidos/<int:id_pedido>")
@requiere_login()
def detalle_pedido(id_pedido):
    """
    Muestra el detalle de un pedido específico del usuario autenticado.

    Verifica la propiedad del pedido (abortando con 404 si no existe o pertenece
    a otro usuario) y carga sus líneas de detalle e información de pago.

    Args:
        id_pedido (int): Identificador del pedido a consultar.

    Returns:
        str: Plantilla HTML `cuenta/detalle_pedido.html` renderizada.
    """
    id_usuario = session["id_usuario"]
    pedido = Pedido.obtener_por_id(id_pedido)

    # Control de propiedad (evita acceso a pedidos de otros clientes)
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

    Args:
        id_pedido (int): Identificador del pedido a cancelar.

    Returns:
        flask.Response: Redirección al detalle del pedido con mensaje informativo.
    """
    id_usuario = session["id_usuario"]
    pedido = Pedido.obtener_por_id(id_pedido)

    # Verifica existencia y propiedad del pedido
    if not pedido or int(pedido["id_usuario"]) != int(id_usuario):
        abort(404)

    pago = Pago.obtener_por_pedido(id_pedido)

    # Solo permite cancelar si tanto el pedido como su pago están en estado pendiente
    if int(pedido["id_estado"]) != ESTADO_PENDIENTE or not pago or pago.get("estado") != ESTADO_PAGO_PENDIENTE:
        flash("Solo puedes cancelar pedidos pendientes que tengan un pago pendiente.", "warning")
        return redirect(url_for("cuenta.detalle_pedido", id_pedido=id_pedido))

    # Actualiza el estado del pedido (lo cual restaura el stock) y marca el pago como cancelado
    try:
        Pedido.actualizar_estado(id_pedido, ESTADO_CANCELADO)
        Pago.marcar(id_pedido, ESTADO_PAGO_CANCELADO)
        flash("Tu pedido ha sido cancelado exitosamente y el stock ha sido liberado.", "info")
    except Exception as e:
        flash(f"No se pudo cancelar el pedido: {e}", "danger")

    return redirect(url_for("cuenta.detalle_pedido", id_pedido=id_pedido))
