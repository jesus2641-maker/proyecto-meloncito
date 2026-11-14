"""
Rutas del Carrito de Compras - Gestión del flujo de compra
Este módulo maneja todas las operaciones del carrito: agregar productos,
actualizar cantidades, eliminar items, y el proceso de checkout completo.
"""

import logging
from flask import Blueprint, render_template, session, jsonify, request, redirect, url_for, flash, abort
from app.models.carrito import Carrito, CarritoItem
from app.models.direccion import Direccion
from app.models.metodo_pago import MetodoPago
from app.models.pedido import Pedido, PedidoDetalle
from app.models.producto import VarianteProducto, Producto
from app.models.usuario import Usuario
from app.utils.validaciones import (
    validar_stock_carrito,
    validar_tipo_pago,
    validar_tipo_pago_checkout,
    validar_detalle_pago,
    validar_direccion,
    TIPOS_PAGO_CHECKOUT,
)
from app.utils.decoradores import requiere_login
from app.utils.email_service import send_order_confirmation_email, enviar_confirmacion_pedido_por_id
from app.utils.paypal_client import paypal_configurado
from app.models.pago import Pago
from config import Config

logger = logging.getLogger(__name__)

carrito_bp = Blueprint("carrito", __name__, url_prefix="/carrito")


def _redirigir_si_stock_invalido(items):
    """
    Función auxiliar para validar stock y redirigir si hay problemas.

    Args:
        items: Lista de items del carrito a validar

    Returns:
        Redirect si hay errores de stock, None si todo está correcto
    """
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
    total = sum((item["precio_oferta"] if item["precio_oferta"] else item["precio"]) * item["cantidad"] for item in items)

    return render_template("carrito/ver.html", items=items, total=total)


@carrito_bp.route("/agregar", methods=["POST"])
@requiere_login(mensaje="Inicia sesión para agregar productos al carrito")
def agregar():
    is_ajax = (
        request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
        or "application/json" in request.headers.get("Accept", "")
    )

    if request.is_json:
        data = request.get_json(silent=True) or {}
        id_variante = data.get("id_variante")
        cantidad = data.get("cantidad", 1)
        try:
            id_variante = int(id_variante) if id_variante is not None else None
            cantidad = int(cantidad) if cantidad is not None else 1
        except (ValueError, TypeError):
            id_variante = None
            cantidad = 0
    else:
        id_variante = request.form.get("id_variante", type=int)
        cantidad = request.form.get("cantidad", default=1, type=int)

    if not id_variante or cantidad <= 0:
        if is_ajax:
            return jsonify({"error": "Datos de producto inválidos", "success": False}), 400
        flash("Datos de producto inválidos", "danger")
        return redirect(url_for("productos.catalogo"))

    variante = VarianteProducto.obtener_por_id(id_variante)
    if not variante:
        if is_ajax:
            return jsonify({"error": "La variante del producto no existe", "success": False}), 404
        flash("La variante del producto no existe", "danger")
        return redirect(url_for("productos.catalogo"))

    producto = Producto.obtener_por_id(variante["id_producto"])
    url_producto = url_for("productos.detalle", producto_id=variante["id_producto"])

    if not producto or not producto.get("activo"):
        if is_ajax:
            return jsonify({"error": "Este producto no está disponible", "success": False}), 400
        flash("Este producto no está disponible", "warning")
        return redirect(url_for("productos.catalogo"))

    stock_actual = int(variante.get("stock") or 0)
    if stock_actual <= 0:
        mensaje_error = f"El producto '{producto['nombre_producto']}' ({variante['presentacion']}) no está disponible por falta de stock."
        if is_ajax:
            return jsonify({
                "error": mensaje_error,
                "disponible": False,
                "stock": 0,
                "success": False
            }), 400
        flash(mensaje_error, "warning")
        return redirect(url_producto)

    carrito = Carrito.obtener_o_crear(session["id_usuario"])
    cantidad_en_carrito = CarritoItem.obtener_cantidad(carrito["id_carrito"], id_variante)
    cantidad_total = cantidad_en_carrito + cantidad

    if cantidad_total > stock_actual:
        disponibles = max(stock_actual - cantidad_en_carrito, 0)
        if disponibles == 0:
            mensaje = (
                f"Ya tienes el máximo disponible de '{producto['nombre_producto']}' "
                f"({variante['presentacion']}) en tu carrito."
            )
        else:
            mensaje = (
                f"Solo hay {disponibles} unidad(es) disponible(s) de "
                f"'{producto['nombre_producto']}' ({variante['presentacion']})."
            )

        if is_ajax:
            return jsonify({
                "error": mensaje,
                "disponible": disponibles > 0,
                "stock_disponible": disponibles,
                "success": False
            }), 400
        flash(mensaje, "warning")
        return redirect(url_producto)

    CarritoItem.agregar(carrito["id_carrito"], id_variante, cantidad)

    if is_ajax:
        return jsonify({
            "mensaje": f"'{producto['nombre_producto']}' ({variante['presentacion']}) agregado al carrito exitosamente.",
            "success": True
        }), 200

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


@carrito_bp.route("/actualizar", methods=["POST"])
@requiere_login()
def actualizar():
    """Actualiza la cantidad de un item en el carrito con validación de stock."""
    id_item = request.form.get("id_item", type=int)
    nueva_cantidad = request.form.get("cantidad", type=int)

    logger.debug("Actualizar cantidad de carrito: id_item=%s, nueva_cantidad=%s", id_item, nueva_cantidad)

    if not id_item or nueva_cantidad is None:
        logger.warning("Datos inválidos al actualizar carrito")
        flash("Datos inválidos", "danger")
        return redirect(url_for("carrito.ver_carrito"))

    if nueva_cantidad <= 0:
        logger.warning("Cantidad no válida al actualizar carrito: %s", nueva_cantidad)
        flash("La cantidad debe ser mayor a 0", "danger")
        return redirect(url_for("carrito.ver_carrito"))

    # Obtener el item actual
    item = CarritoItem.obtener_por_id(id_item)
    if not item:
        logger.warning("Item de carrito no encontrado: id_item=%s", id_item)
        flash("Item no encontrado", "danger")
        return redirect(url_for("carrito.ver_carrito"))

    # Verificar stock disponible
    variante = VarianteProducto.obtener_por_id(item["id_variante"])
    if not variante:
        logger.warning("Variante de producto no disponible: id_variante=%s", item["id_variante"])
        flash("Producto no disponible", "danger")
        return redirect(url_for("carrito.ver_carrito"))

    if variante["stock"] <= 0:
        logger.info("Producto agotado al actualizar carrito: id_variante=%s", item["id_variante"])
        flash("Este producto está agotado", "warning")
        return redirect(url_for("carrito.ver_carrito"))

    if nueva_cantidad > variante["stock"]:
        disponibles = variante["stock"]
        logger.info("Stock insuficiente al actualizar carrito: solicitado=%s, disponible=%s", nueva_cantidad, disponibles)
        flash(f"Solo hay {disponibles} unidad(es) disponible(s)", "warning")
        return redirect(url_for("carrito.ver_carrito"))

    # Actualizar cantidad
    logger.debug("Actualizando cantidad de item %s a %s", id_item, nueva_cantidad)
    CarritoItem.actualizar_cantidad(id_item, nueva_cantidad)
    flash("Cantidad actualizada", "success")
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

    total = sum((item["precio_oferta"] if item["precio_oferta"] else item["precio"]) * item["cantidad"] for item in items)

    if request.method == "POST":
        respuesta_stock = _redirigir_si_stock_invalido(items)
        if respuesta_stock:
            return respuesta_stock

        # 1. Validar Dirección (antes de insertar en BD)
        opcion_direccion = request.form.get("opcion_direccion")  # 'guardada' o 'nueva'
        id_direccion = request.form.get("id_direccion", type=int)
        crear_nueva_direccion = opcion_direccion == "nueva" or not id_direccion

        if crear_nueva_direccion:
            alias = request.form.get("alias_direccion", "").strip() or None
            linea_direccion = request.form.get("linea_direccion", "").strip()
            ciudad = request.form.get("ciudad", "").strip()
            departamento = request.form.get("departamento", "").strip() or None
            codigo_postal = request.form.get("codigo_postal", "").strip() or None

            dir_ok, dir_err = validar_direccion(
                linea_direccion=linea_direccion,
                ciudad=ciudad,
                departamento=departamento,
                codigo_postal=codigo_postal,
                alias=alias,
            )
            if not dir_ok:
                flash(dir_err, "danger")
                direcciones = Direccion.listar_por_usuario(id_usuario)
                metodos_pago = [mp for mp in MetodoPago.listar_por_usuario(id_usuario) if mp.get("tipo") in ("Efectivo contra entrega", "PayPal")]
                return render_template("carrito/checkout.html", items=items, total=total, direcciones=direcciones, metodos_pago=metodos_pago, paypal_disponible=paypal_configurado())
        else:
            # Validar que la dirección seleccionada pertenezca al usuario
            dir_existente = Direccion.obtener_por_id(id_direccion)
            if not dir_existente or dir_existente["id_usuario"] != id_usuario:
                flash("Dirección no válida", "danger")
                return redirect(url_for("carrito.checkout"))

        # 2. Validar Método de Pago (antes de insertar en BD)
        opcion_pago = request.form.get("opcion_pago")  # 'guardado' o 'nuevo'
        id_metodo_pago = request.form.get("id_metodo_pago", type=int)
        crear_nuevo_pago = opcion_pago == "nuevo" or not id_metodo_pago

        if crear_nuevo_pago:
            tipo = request.form.get("tipo_pago", "").strip()
            detalle = request.form.get("detalle_pago", "").strip() or None

            tipo_ok, tipo_err = validar_tipo_pago_checkout(tipo)
            if not tipo_ok:
                flash(tipo_err, "danger")
                direcciones = Direccion.listar_por_usuario(id_usuario)
                metodos_pago = [mp for mp in MetodoPago.listar_por_usuario(id_usuario) if mp.get("tipo") in TIPOS_PAGO_CHECKOUT]
                return render_template("carrito/checkout.html", items=items, total=total, direcciones=direcciones, metodos_pago=metodos_pago, paypal_disponible=paypal_configurado())

            if tipo == "PayPal":
                if not paypal_configurado():
                    flash("El pago con PayPal no está disponible en este momento", "danger")
                    return redirect(url_for("carrito.checkout"))
                detalle = "Pago en línea con PayPal"
            else:
                det_ok, det_err = validar_detalle_pago(detalle)
                if not det_ok:
                    flash(det_err, "danger")
                    direcciones = Direccion.listar_por_usuario(id_usuario)
                    metodos_pago = [mp for mp in MetodoPago.listar_por_usuario(id_usuario) if mp.get("tipo") in TIPOS_PAGO_CHECKOUT]
                    return render_template("carrito/checkout.html", items=items, total=total, direcciones=direcciones, metodos_pago=metodos_pago, paypal_disponible=paypal_configurado())
        else:
            # Validar que el método de pago seleccionado pertenezca al usuario
            metodo_existente = MetodoPago.obtener_por_id(id_metodo_pago)
            if not metodo_existente or metodo_existente["id_usuario"] != id_usuario:
                flash("Método de pago no válido", "danger")
                return redirect(url_for("carrito.checkout"))
            tipo = metodo_existente["tipo"]
            detalle = metodo_existente.get("detalle")

            tipo_ok, tipo_err = validar_tipo_pago_checkout(tipo)
            if not tipo_ok:
                flash(tipo_err, "danger")
                return redirect(url_for("carrito.checkout"))

            if tipo == "PayPal" and not paypal_configurado():
                flash("El pago con PayPal no está disponible en este momento", "danger")
                return redirect(url_for("carrito.checkout"))

        # 2.5 Persistir nueva dirección / nuevo método de pago una vez validados ambos
        if crear_nueva_direccion:
            id_direccion = Direccion.crear(
                id_usuario=id_usuario,
                linea_direccion=linea_direccion,
                ciudad=ciudad,
                departamento=departamento,
                codigo_postal=codigo_postal,
                alias=alias,
                es_principal=1 if not Direccion.listar_por_usuario(id_usuario) else 0
            )

        if tipo == "PayPal":
            metodos_usuario = MetodoPago.listar_por_usuario(id_usuario)
            mp_paypal = next((m for m in metodos_usuario if m.get("tipo") == "PayPal"), None)
            if mp_paypal:
                id_metodo_pago = mp_paypal["id_metodo_pago"]
            else:
                id_metodo_pago = MetodoPago.crear(
                    id_usuario=id_usuario,
                    tipo="PayPal",
                    detalle="Pago en línea con PayPal",
                    es_predeterminado=1 if not metodos_usuario else 0
                )
        elif crear_nuevo_pago:
            id_metodo_pago = MetodoPago.crear(
                id_usuario=id_usuario,
                tipo=tipo,
                detalle=detalle,
                es_predeterminado=1 if not MetodoPago.listar_por_usuario(id_usuario) else 0
            )

        # 3. Crear pedido completo con transacción atómica
        resultado_pedido = Pedido.crear_con_transaccion(
            id_usuario=id_usuario,
            id_direccion=id_direccion,
            id_metodo_pago=id_metodo_pago,
            total=total,
            items=items
        )

        # Verificar si hubo error de stock
        if isinstance(resultado_pedido, dict) and resultado_pedido.get('error') == 'stock_insuficiente':
            error_info = resultado_pedido
            mensaje_error = (
                f"'{error_info['nombre_producto']}' ({error_info['presentacion']}): "
                f"solo hay {error_info['stock_disponible']} disponible(s), "
                f"pero solicitaste {error_info['cantidad_solicitada']}. "
                f"Por favor actualiza tu carrito."
            )
            flash(mensaje_error, "danger")
            return redirect(url_for("carrito.checkout"))

        if not resultado_pedido:
            flash("No hay suficiente stock para completar tu pedido. Por favor intenta nuevamente.", "danger")
            return redirect(url_for("carrito.checkout"))

        id_pedido = resultado_pedido

        # Flujo según tipo de pago
        if tipo == "PayPal":
            from app.utils.moneda import cop_a_usd, obtener_tasa_cop_usd
            try:
                tasa_cop_usd = obtener_tasa_cop_usd()
                monto_usd = cop_a_usd(total, tasa_cop_usd)
            except ValueError:
                tasa_cop_usd = None
                monto_usd = None
            Pago.crear_para_pedido(
                id_pedido=id_pedido,
                monto=total,
                moneda=Config.PAYPAL_CURRENCY,
                tasa_cop_usd=tasa_cop_usd,
                monto_usd=monto_usd
            )
            return redirect(url_for("pagos.paypal_checkout", id_pedido=id_pedido))

        # Efectivo contra entrega: enviar confirmación de inmediato
        enviar_confirmacion_pedido_por_id(id_pedido, id_usuario)
        flash("¡Tu pedido ha sido confirmado con éxito!", "success")
        return redirect(url_for("carrito.confirmacion", id_pedido=id_pedido))

    direcciones = Direccion.listar_por_usuario(id_usuario)
    metodos_guardados = MetodoPago.listar_por_usuario(id_usuario)
    metodos_pago = [mp for mp in metodos_guardados if mp.get("tipo") in TIPOS_PAGO_CHECKOUT]
    problemas_stock = validar_stock_carrito(items)
    paypal_disponible = paypal_configurado()

    return render_template(
        "carrito/checkout.html",
        items=items,
        total=total,
        direcciones=direcciones,
        metodos_pago=metodos_pago,
        problemas_stock=problemas_stock,
        paypal_disponible=paypal_disponible,
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
