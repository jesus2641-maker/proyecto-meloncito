from flask import Blueprint, render_template, session, jsonify, request, redirect, url_for, flash, abort
from app.models.carrito import Carrito, CarritoItem
from app.models.direccion import Direccion
from app.models.metodo_pago import MetodoPago
from app.models.pedido import Pedido, PedidoDetalle
from app.models.producto import VarianteProducto, Producto
from app.utils.validaciones import validar_stock_carrito
from app.utils.decoradores import requiere_login

carrito_bp = Blueprint("carrito", __name__, url_prefix="/carrito")


def _redirigir_si_stock_invalido(items):
    errores = validar_stock_carrito(items)
    if errores:
        for error in errores:
            flash(error, "danger")
        flash("Actualiza tu carrito antes de confirmar el pedido.", "warning")
        return redirect(url_for("carrito.ver_carrito"))
    return None


@carrito_bp.route("/")
@requiere_login(mensaje="Inicia sesión para ver tu carrito")
def ver_carrito():
    carrito = Carrito.obtener_o_crear(session["id_usuario"])
    items = Carrito.obtener_items(carrito["id_carrito"])
    total = sum(item["precio"] * item["cantidad"] for item in items)

    return render_template("carrito/ver.html", items=items, total=total)


@carrito_bp.route("/agregar", methods=["POST"])
@requiere_login(mensaje="Inicia sesión para agregar productos al carrito")
def agregar():
    id_variante = request.form.get("id_variante", type=int)
    cantidad = request.form.get("cantidad", default=1, type=int)

    if not id_variante or cantidad <= 0:
        flash("Datos de producto inválidos", "danger")
        return redirect(url_for("productos.catalogo"))

    variante = VarianteProducto.obtener_por_id(id_variante)
    if not variante:
        flash("La variante del producto no existe", "danger")
        return redirect(url_for("productos.catalogo"))

    producto = Producto.obtener_por_id(variante["id_producto"])
    url_producto = url_for("productos.detalle", producto_id=variante["id_producto"])

    if not producto or not producto.get("activo"):
        flash("Este producto no está disponible", "warning")
        return redirect(url_for("productos.catalogo"))

    if variante["stock"] <= 0:
        flash(f"'{producto['nombre_producto']}' ({variante['presentacion']}) está agotado", "warning")
        return redirect(url_producto)

    carrito = Carrito.obtener_o_crear(session["id_usuario"])
    cantidad_en_carrito = CarritoItem.obtener_cantidad(carrito["id_carrito"], id_variante)
    cantidad_total = cantidad_en_carrito + cantidad

    if cantidad_total > variante["stock"]:
        disponibles = max(variante["stock"] - cantidad_en_carrito, 0)
        if disponibles == 0:
            flash(
                f"Ya tienes el máximo disponible de '{producto['nombre_producto']}' en tu carrito",
                "warning"
            )
        else:
            flash(
                f"Solo hay {disponibles} unidad(es) disponible(s) de "
                f"'{producto['nombre_producto']}' ({variante['presentacion']})",
                "warning"
            )
        return redirect(url_producto)

    CarritoItem.agregar(carrito["id_carrito"], id_variante, cantidad)

    flash("Producto agregado al carrito", "success")
    return redirect(url_producto)


@carrito_bp.route("/eliminar", methods=["POST"])
@requiere_login()
def eliminar():
    id_item = request.form.get("id_item", type=int)
    if id_item:
        CarritoItem.eliminar(id_item)
        flash("Producto eliminado del carrito", "info")

    return redirect(url_for("carrito.ver_carrito"))


@carrito_bp.route("/checkout", methods=["GET", "POST"])
@requiere_login(mensaje="Inicia sesión para completar tu compra")
def checkout():
    id_usuario = session["id_usuario"]
    carrito = Carrito.obtener_o_crear(id_usuario)
    items = Carrito.obtener_items(carrito["id_carrito"])

    if not items:
        flash("Tu carrito está vacío. Agrega productos antes de continuar.", "warning")
        return redirect(url_for("carrito.ver_carrito"))

    total = sum(item["precio"] * item["cantidad"] for item in items)

    if request.method == "POST":
        respuesta_stock = _redirigir_si_stock_invalido(items)
        if respuesta_stock:
            return respuesta_stock

        # 1. Resolver Dirección
        opcion_direccion = request.form.get("opcion_direccion")  # 'guardada' o 'nueva'
        id_direccion = request.form.get("id_direccion", type=int)

        if opcion_direccion == "nueva" or not id_direccion:
            alias = request.form.get("alias_direccion", "").strip() or None
            linea_direccion = request.form.get("linea_direccion", "").strip()
            ciudad = request.form.get("ciudad", "").strip()
            departamento = request.form.get("departamento", "").strip() or None
            codigo_postal = request.form.get("codigo_postal", "").strip() or None
            guardar_direccion = request.form.get("guardar_direccion")

            if not linea_direccion or not ciudad:
                flash("Por favor ingresa la dirección de entrega y la ciudad", "danger")
                direcciones = Direccion.listar_por_usuario(id_usuario)
                metodos_pago = MetodoPago.listar_por_usuario(id_usuario)
                return render_template("carrito/checkout.html", items=items, total=total, direcciones=direcciones, metodos_pago=metodos_pago)

            id_direccion = Direccion.crear(
                id_usuario=id_usuario,
                linea_direccion=linea_direccion,
                ciudad=ciudad,
                departamento=departamento,
                codigo_postal=codigo_postal,
                alias=alias,
                es_principal=1 if not Direccion.listar_por_usuario(id_usuario) else 0
            )
        else:
            # Validar que la dirección seleccionada pertenezca al usuario
            dir_existente = Direccion.obtener_por_id(id_direccion)
            if not dir_existente or dir_existente["id_usuario"] != id_usuario:
                flash("Dirección no válida", "danger")
                return redirect(url_for("carrito.checkout"))

        # 2. Resolver Método de Pago
        opcion_pago = request.form.get("opcion_pago")  # 'guardado' o 'nuevo'
        id_metodo_pago = request.form.get("id_metodo_pago", type=int)

        if opcion_pago == "nuevo" or not id_metodo_pago:
            tipo = request.form.get("tipo_pago", "").strip()
            detalle = request.form.get("detalle_pago", "").strip() or None

            if not tipo:
                flash("Por favor selecciona un método de pago", "danger")
                direcciones = Direccion.listar_por_usuario(id_usuario)
                metodos_pago = MetodoPago.listar_por_usuario(id_usuario)
                return render_template("carrito/checkout.html", items=items, total=total, direcciones=direcciones, metodos_pago=metodos_pago)

            id_metodo_pago = MetodoPago.crear(
                id_usuario=id_usuario,
                tipo=tipo,
                detalle=detalle,
                es_predeterminado=1 if not MetodoPago.listar_por_usuario(id_usuario) else 0
            )
        else:
            # Validar que el método de pago seleccionado pertenezca al usuario
            metodo_existente = MetodoPago.obtener_por_id(id_metodo_pago)
            if not metodo_existente or metodo_existente["id_usuario"] != id_usuario:
                flash("Método de pago no válido", "danger")
                return redirect(url_for("carrito.checkout"))

        # 3. Crear pedido completo con transacción atómica
        id_pedido = Pedido.crear_con_transaccion(
            id_usuario=id_usuario,
            id_direccion=id_direccion,
            id_metodo_pago=id_metodo_pago,
            total=total,
            items=items
        )
        
        if not id_pedido:
            flash("No hay suficiente stock para completar tu pedido. Por favor intenta nuevamente.", "danger")
            return redirect(url_for("carrito.checkout"))

        flash("¡Tu pedido ha sido confirmado con éxito!", "success")
        return redirect(url_for("carrito.confirmacion", id_pedido=id_pedido))

    direcciones = Direccion.listar_por_usuario(id_usuario)
    metodos_pago = MetodoPago.listar_por_usuario(id_usuario)
    problemas_stock = validar_stock_carrito(items)

    return render_template(
        "carrito/checkout.html",
        items=items,
        total=total,
        direcciones=direcciones,
        metodos_pago=metodos_pago,
        problemas_stock=problemas_stock
    )


@carrito_bp.route("/confirmacion/<int:id_pedido>")
@requiere_login(mensaje="Inicia sesión para consultar tu pedido")
def confirmacion(id_pedido):
    id_usuario = session["id_usuario"]
    pedido = Pedido.obtener_por_id(id_pedido)

    if not pedido or pedido["id_usuario"] != id_usuario:
        abort(404)

    detalles = PedidoDetalle.listar_por_pedido(id_pedido)

    return render_template(
        "carrito/confirmacion.html",
        pedido=pedido,
        detalles=detalles
    )
