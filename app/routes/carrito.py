"""
Rutas del Carrito de Compras - Gestión del flujo de compra.

Este módulo maneja todas las operaciones del carrito: visualizar ítems,
agregar productos (tanto vía formulario HTML como vía petición AJAX/JSON),
actualizar cantidades con validación de stock, eliminar ítems, ejecutar el
proceso completo de checkout (dirección, método de pago, transacción atómica
de pedido, flujo PayPal o contra entrega) y mostrar la confirmación del pedido.
"""

# Módulo de logging para trazabilidad de errores y validaciones de inventario
import logging
# Componentes de Flask para blueprint, vistas, sesión, JSON, peticiones, redirecciones, flash y abort
from flask import Blueprint, render_template, session, jsonify, request, redirect, url_for, flash, abort
# Modelos del dominio de compra
from app.models.carrito import Carrito, CarritoItem
from app.models.direccion import Direccion
from app.models.metodo_pago import MetodoPago
from app.models.pedido import Pedido, PedidoDetalle
from app.models.producto import VarianteProducto, Producto
from app.models.usuario import Usuario
# Funciones de validación de stock, dirección y métodos de pago
from app.utils.validaciones import (
    validar_stock_carrito,
    validar_tipo_pago,
    validar_tipo_pago_checkout,
    validar_detalle_pago,
    validar_direccion,
    TIPOS_PAGO_CHECKOUT,
)
# Decorador que exige sesión activa
from app.utils.decoradores import requiere_login
# Servicios de correo para confirmación de pedidos
from app.utils.email_service import send_order_confirmation_email, enviar_confirmacion_pedido_por_id
# Verificador de disponibilidad de credenciales PayPal
from app.utils.paypal_client import paypal_configurado
# Modelo de pagos para registrar transacciones PayPal
from app.models.pago import Pago
# Configuración global de la aplicación (moneda PayPal, etc.)
from config import Config

# Logger del módulo de carrito
logger = logging.getLogger(__name__)

# Blueprint del carrito bajo el prefijo /carrito
carrito_bp = Blueprint("carrito", __name__, url_prefix="/carrito")


def _redirigir_si_stock_invalido(items):
    """
    Función auxiliar para validar stock de todos los ítems del carrito y redirigir
    si existe algún problema de disponibilidad.

    Args:
        items (list[dict]): Lista de ítems del carrito a validar.

    Returns:
        flask.Response | None: Redirección a `carrito.ver_carrito` si hay errores
            de stock, o `None` si todos los ítems son válidos.
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
    """
    Muestra el contenido actual del carrito del usuario autenticado.

    Calcula el total considerando el precio promocional (`precio_oferta`) cuando
    esté vigente, o el precio regular en caso contrario.

    Returns:
        str: Plantilla HTML `carrito/ver.html` renderizada.
    """
    carrito = Carrito.obtener_o_crear(session["id_usuario"])
    items = Carrito.obtener_items(carrito["id_carrito"])
    # Prioriza precio_oferta si existe una promoción activa sobre la variante
    total = sum((item["precio_oferta"] if item.get("precio_oferta") is not None else item["precio"]) * item["cantidad"] for item in items)

    return render_template("carrito/ver.html", items=items, total=total)


@carrito_bp.route("/agregar", methods=["POST"])
@requiere_login(mensaje="Inicia sesión para agregar productos al carrito")
def agregar():
    """
    Agrega una variante de producto al carrito del usuario autenticado.

    Soporta tanto peticiones tradicionales de formulario (`application/x-www-form-urlencoded`)
    como peticiones asíncronas AJAX/fetch con JSON (`application/json`), devolviendo
    respuestas JSON o redirecciones con mensajes flash según el caso.

    Returns:
        flask.Response | tuple[flask.Response, int]: Respuesta JSON (AJAX) o
            redirección HTTP (formulario estándar).
    """
    # Detecta si el cliente espera una respuesta JSON (AJAX / Fetch API)
    is_ajax = (
        request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
        or "application/json" in request.headers.get("Accept", "")
    )

    # Extrae id_variante y cantidad desde JSON o desde formulario HTML
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

    # Valida que los parámetros básicos sean enteros positivos válidos
    if not id_variante or cantidad <= 0:
        if is_ajax:
            return jsonify({"error": "Datos de producto inválidos", "success": False}), 400
        flash("Datos de producto inválidos", "danger")
        return redirect(url_for("productos.catalogo"))

    # Verifica que la variante exista en la base de datos
    variante = VarianteProducto.obtener_por_id(id_variante)
    if not variante:
        if is_ajax:
            return jsonify({"error": "La variante del producto no existe", "success": False}), 404
        flash("La variante del producto no existe", "danger")
        return redirect(url_for("productos.catalogo"))

    # Obtiene el producto padre y verifica que esté activo
    producto = Producto.obtener_por_id(variante["id_producto"])
    url_producto = url_for("productos.detalle", producto_id=variante["id_producto"])

    if not producto or not producto.get("activo"):
        if is_ajax:
            return jsonify({"error": "Este producto no está disponible", "success": False}), 400
        flash("Este producto no está disponible", "warning")
        return redirect(url_for("productos.catalogo"))

    # Verifica que haya stock disponible (> 0)
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

    # Verifica que la suma de lo que ya está en el carrito + lo solicitado no supere el stock
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

    # Inserta o suma la cantidad en el carrito
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
    """
    Elimina un ítem específico del carrito verificando que pertenezca al usuario.

    Returns:
        flask.Response: Redirección a `carrito.ver_carrito`.
    """
    id_item = request.form.get("id_item", type=int)
    if id_item:
        carrito = Carrito.obtener_o_crear(session["id_usuario"])
        item = CarritoItem.obtener_por_id(id_item)
        # Valida propiedad del ítem antes de eliminarlo
        if not item or item["id_carrito"] != carrito["id_carrito"]:
            flash("Item no encontrado en tu carrito", "danger")
            return redirect(url_for("carrito.ver_carrito"))
        CarritoItem.eliminar(id_item, id_carrito=carrito["id_carrito"])
        flash("Producto eliminado del carrito", "info")

    return redirect(url_for("carrito.ver_carrito"))


@carrito_bp.route("/actualizar", methods=["POST"])
@requiere_login()
def actualizar():
    """
    Actualiza la cantidad de un item en el carrito con validación de stock y propiedad.

    Returns:
        flask.Response: Redirección a `carrito.ver_carrito` con mensaje de resultado.
    """
    id_item = request.form.get("id_item", type=int)
    nueva_cantidad = request.form.get("cantidad", type=int)

    logger.debug("Actualizar cantidad de carrito: id_item=%s, nueva_cantidad=%s", id_item, nueva_cantidad)

    # Verifica presencia y validez numérica de los datos recibidos
    if not id_item or nueva_cantidad is None:
        logger.warning("Datos inválidos al actualizar carrito")
        flash("Datos inválidos", "danger")
        return redirect(url_for("carrito.ver_carrito"))

    if nueva_cantidad <= 0:
        logger.warning("Cantidad no válida al actualizar carrito: %s", nueva_cantidad)
        flash("La cantidad debe ser mayor a 0", "danger")
        return redirect(url_for("carrito.ver_carrito"))

    # Obtener el item actual y verificar que pertenezca al carrito del usuario
    carrito = Carrito.obtener_o_crear(session["id_usuario"])
    item = CarritoItem.obtener_por_id(id_item)
    if not item or item["id_carrito"] != carrito["id_carrito"]:
        logger.warning("Item de carrito no encontrado o no pertenece al usuario: id_item=%s", id_item)
        flash("Item no encontrado", "danger")
        return redirect(url_for("carrito.ver_carrito"))

    # Verificar stock disponible en la variante asociada
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

    # Actualizar cantidad en base de datos
    logger.debug("Actualizando cantidad de item %s a %s", id_item, nueva_cantidad)
    CarritoItem.actualizar_cantidad(id_item, nueva_cantidad, id_carrito=carrito["id_carrito"])
    flash("Cantidad actualizada", "success")
    return redirect(url_for("carrito.ver_carrito"))


@carrito_bp.route("/checkout", methods=["GET", "POST"])
@requiere_login(mensaje="Inicia sesión para completar tu compra")
def checkout():
    """
    Gestiona el proceso completo de finalización de compra (checkout).

    - GET: muestra el resumen del carrito, direcciones guardadas, métodos de
      pago permitidos (`Efectivo contra entrega` y `PayPal`), y advertencias de stock.
    - POST: valida stock, dirección (nueva o existente), método de pago (nuevo o
      existente), crea la dirección/método si son nuevos, ejecuta
      `Pedido.crear_con_transaccion` (transacción atómica que descuenta stock y
      vacía el carrito) y redirige al flujo de PayPal o a la confirmación directa.

    Returns:
        flask.Response | str: Redirección o plantilla HTML `carrito/checkout.html`.
    """
    id_usuario = session["id_usuario"]
    carrito = Carrito.obtener_o_crear(id_usuario)
    items = Carrito.obtener_items(carrito["id_carrito"])

    # No permite acceder al checkout con el carrito vacío
    if not items:
        flash("Tu carrito está vacío. Agrega productos antes de continuar.", "warning")
        return redirect(url_for("carrito.ver_carrito"))

    # Calcula el total del pedido considerando precios de oferta vigentes
    total = sum((item["precio_oferta"] if item.get("precio_oferta") is not None else item["precio"]) * item["cantidad"] for item in items)

    if request.method == "POST":
        # Revalida el stock antes de procesar cualquier dato del formulario
        respuesta_stock = _redirigir_si_stock_invalido(items)
        if respuesta_stock:
            return respuesta_stock

        # 1. Validar Dirección (antes de insertar en BD para evitar registros huérfanos si falla el pago)
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
            # Validar que la dirección seleccionada pertenezca al usuario en sesión
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

        # Si el tipo es PayPal, reutiliza el método PayPal guardado del usuario o crea uno nuevo
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

        # 3. Crear pedido completo con transacción atómica (bloquea filas, descuenta stock y limpia carrito)
        resultado_pedido = Pedido.crear_con_transaccion(
            id_usuario=id_usuario,
            id_direccion=id_direccion,
            id_metodo_pago=id_metodo_pago,
            total=total,
            items=items
        )

        # Verificar si hubo error de stock concurrente durante la transacción
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

        # Flujo según tipo de pago: PayPal crea registro de pago y redirige a pasarela
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

        # Efectivo contra entrega: enviar confirmación por correo de inmediato
        enviar_confirmacion_pedido_por_id(id_pedido, id_usuario)
        flash("¡Tu pedido ha sido confirmado con éxito!", "success")
        return redirect(url_for("carrito.confirmacion", id_pedido=id_pedido))

    # Petición GET: carga datos auxiliares para renderizar el formulario de checkout
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
    """
    Muestra la página de confirmación de un pedido recién creado o pagado.

    Verifica que el pedido exista y pertenezca al usuario en sesión.

    Args:
        id_pedido (int): Identificador del pedido a mostrar.

    Returns:
        str: Plantilla HTML `carrito/confirmacion.html` renderizada.
    """
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
