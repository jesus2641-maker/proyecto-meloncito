"""
Módulo de rutas del panel operativo para Trabajadores (`/trabajador`).

Proporciona las vistas y acciones permitidas al personal operativo (rol trabajador
y también accesible para administradores):
- Dashboard con métricas básicas y últimos pedidos.
- Consulta de productos y variantes en modo solo lectura.
- Gestión de inventario (filtros, alertas de stock y actualización de cantidades).
- Gestión operativa de pedidos (listado, detalle y cambio de estados básicos,
  restringiendo la cancelación exclusivamente al administrador).
- Consulta de clientes en modo solo lectura.
- Edición de perfil propio (`/mi-cuenta`) y reporte de inventario crítico.
"""

# Módulos estándar para logging y expresiones regulares de validación numérica
import logging
import re
# Utilidades de Flask para blueprint, plantillas, sesión, redirecciones, mensajes y peticiones
from flask import Blueprint, render_template, session, redirect, url_for, flash, request
# Modelos de negocio consultados/modificados por el trabajador
from app.models.producto import Producto, VarianteProducto
from app.models.pedido import Pedido, ESTADO_CANCELADO
from app.models.pago import Pago
from app.models.usuario import Usuario
from app.models.categoria import Categoria
from app.models.reporte import Reporte
# Decoradores y utilidades de notificación por correo
from app.utils.decoradores import requiere_trabajador_o_admin
from app.utils.email_service import send_order_status_update_email

# Logger del módulo de trabajador
logger = logging.getLogger(__name__)

# Blueprint del panel trabajador bajo el prefijo /trabajador
trabajador_bp = Blueprint("trabajador", __name__, url_prefix="/trabajador")


@trabajador_bp.before_request
def verificar_permisos_trabajador():
    """
    Hook ejecutado antes de cada petición al blueprint `trabajador`.

    Verifica que el usuario en sesión tenga rol de trabajador o administrador;
    en caso contrario, muestra un mensaje flash de error y redirige al catálogo.

    Returns:
        flask.Response | None: Redirección al catálogo si no tiene permisos, o None si está autorizado.
    """
    # NOTA: El Trabajador (id_rol=4) puede ver productos/clientes, actualizar stock y avanzar pedidos,
    # pero NO puede cancelar pedidos ni crear/eliminar productos o usuarios (eso es exclusivo del Admin).
    from app.utils.decoradores import ID_ROL_TRABAJADOR, ID_ROL_ADMIN
    if session.get("id_rol") not in [ID_ROL_TRABAJADOR, ID_ROL_ADMIN]:
        flash("No tienes permisos para acceder a esta sección", "danger")
        return redirect(url_for("productos.catalogo"))


# =========================================================
# DASHBOARD TRABAJADOR
# =========================================================
@trabajador_bp.route("/dashboard")
def dashboard():
    """
    Dashboard operativo del trabajador con métricas generales y últimos 5 pedidos.

    Returns:
        str: Plantilla HTML `trabajador/dashboard.html` renderizada.
    """
    metricas = Pedido.obtener_metricas_dashboard()
    ultimos_pedidos = Pedido.listar_todos()[:5]
    estados = Pedido.obtener_estados()

    return render_template(
        "trabajador/dashboard.html",
        metricas=metricas,
        ultimos_pedidos=ultimos_pedidos,
        estados=estados
    )


# =========================================================
# PRODUCTOS (SOLO LECTURA)
# =========================================================
@trabajador_bp.route("/productos")
def productos():
    """
    Lista todos los productos del sistema en modo solo lectura para consulta operativa.

    Returns:
        str: Plantilla HTML `trabajador/productos/index.html` renderizada.
    """
    lista_productos = Producto.listar_admin()
    return render_template("trabajador/productos/index.html", productos=lista_productos)


@trabajador_bp.route("/productos/<int:id_producto>/variantes")
def variantes_producto(id_producto):
    """
    Muestra las variantes/presentaciones de un producto específico (solo lectura).

    Args:
        id_producto (int): Identificador del producto a consultar.

    Returns:
        flask.Response | str: Redirección si no existe, o plantilla de variantes.
    """
    producto = Producto.obtener_por_id(id_producto)
    if not producto:
        flash("Producto no encontrado", "danger")
        return redirect(url_for("trabajador.productos"))

    variantes = VarianteProducto.listar_por_producto(id_producto)
    return render_template("trabajador/productos/variantes.html", producto=producto, variantes=variantes)


# =========================================================
# INVENTARIO (LECTURA Y ACTUALIZACIÓN DE STOCK)
# =========================================================
@trabajador_bp.route("/inventario")
def inventario():
    """
    Muestra el inventario completo con filtros por búsqueda, categoría, estado
    de stock, bandera de stock bajo y ordenamiento, junto con alertas activas.

    Returns:
        str: Plantilla HTML `trabajador/inventario.html` renderizada.
    """
    # Extrae filtros opcionales desde los query parameters de la URL
    busqueda = request.args.get("busqueda", "").strip() or None
    id_categoria = request.args.get("categoria", type=int)
    estado_stock = request.args.get("estado_stock") or None
    filtro_bajo = request.args.get("bajo", type=bool)
    ordenar_por = request.args.get("ordenar_por") or None

    inventario = VarianteProducto.obtener_inventario(
        filtro_bajo=filtro_bajo,
        busqueda=busqueda,
        id_categoria=id_categoria,
        estado_stock=estado_stock,
        ordenar_por=ordenar_por
    )
    alertas = VarianteProducto.obtener_alertas_stock()
    categorias = Categoria.listar()

    return render_template(
        "trabajador/inventario.html",
        inventario=inventario,
        alertas=alertas,
        categorias=categorias,
        busqueda=busqueda,
        id_categoria=id_categoria,
        estado_stock=estado_stock,
        filtro_bajo=filtro_bajo,
        ordenar_por=ordenar_por
    )


@trabajador_bp.route("/inventario/actualizar", methods=["POST"])
def actualizar_stock():
    """
    Actualiza el stock físico de una variante de producto.

    Valida mediante expresión regular que el valor ingresado sea un número
    entero no negativo (`^\\d+$`).

    Returns:
        flask.Response: Redirección a `trabajador.inventario`.
    """
    id_variante = request.form.get("id_variante", type=int)
    stock_raw = request.form.get("stock", "").strip()

    # Valida que el ID de variante exista y el stock sea un entero >= 0
    if not id_variante or not stock_raw or not re.match(r"^\d+$", stock_raw):
        flash("El stock no puede ser negativo y debe contener solo números enteros", "danger")
        return redirect(url_for("trabajador.inventario"))

    nuevo_stock = int(stock_raw)

    VarianteProducto.actualizar_stock(id_variante, nuevo_stock)
    flash("Stock actualizado correctamente", "success")
    return redirect(url_for("trabajador.inventario"))


# =========================================================
# PEDIDOS (VER Y CAMBIAR ESTADO)
# =========================================================
@trabajador_bp.route("/pedidos")
def pedidos():
    """
    Lista todos los pedidos del sistema con filtro opcional por estado.

    Returns:
        str: Plantilla HTML `trabajador/pedidos/index.html` renderizada.
    """
    filtro_estado = request.args.get("estado")
    pedidos_lista = Pedido.listar_todos(filtro_estado=filtro_estado)
    estados = Pedido.obtener_estados()

    return render_template(
        "trabajador/pedidos/index.html",
        pedidos=pedidos_lista,
        estados=estados,
        filtro_actual=filtro_estado
    )


@trabajador_bp.route("/pedidos/<int:id_pedido>")
def detalle_pedido(id_pedido):
    """
    Muestra el detalle completo de un pedido, sus líneas de producto y su pago.

    Args:
        id_pedido (int): Identificador del pedido.

    Returns:
        flask.Response | str: Redirección si no existe, o plantilla de detalle.
    """
    pedido = Pedido.obtener_por_id(id_pedido)
    if not pedido:
        flash("Pedido no encontrado", "danger")
        return redirect(url_for("trabajador.pedidos"))

    from app.models.pedido import PedidoDetalle
    detalles = PedidoDetalle.listar_por_pedido(id_pedido)
    estados = Pedido.obtener_estados()
    pago = Pago.obtener_por_pedido(id_pedido)
    return render_template(
        "trabajador/pedidos/detalle.html",
        pedido=pedido,
        detalles=detalles,
        estados=estados,
        pago=pago,
    )


@trabajador_bp.route("/pedidos/<int:id_pedido>/estado", methods=["POST"])
def cambiar_estado_pedido(id_pedido):
    """
    Actualiza el estado operativo de un pedido (ej. Confirmado, En camino, Entregado).

    Restringe la cancelación (`ESTADO_CANCELADO`) para que solo pueda ser
    realizada por un administrador (debido a reembolsos y control de stock).
    Notifica por correo al cliente cuando el cambio es exitoso.

    Args:
        id_pedido (int): Identificador del pedido a actualizar.

    Returns:
        flask.Response: Redirección segura a `next` o al listado de pedidos.
    """
    from app.utils.validaciones import ruta_segura
    id_estado = request.form.get("id_estado", type=int)
    default_url = url_for("trabajador.pedidos")
    # Valida que la URL de retorno sea interna (evita Open Redirect)
    next_url = ruta_segura(request.form.get("next"), fallback=default_url)

    if not id_estado:
        flash("Estado inválido", "danger")
        return redirect(next_url)

    # El trabajador no puede cancelar pedidos (solo admin)
    if id_estado == ESTADO_CANCELADO:
        flash("No tienes permisos para cancelar pedidos. Contacta al administrador.", "warning")
        return redirect(next_url)

    try:
        pedido = Pedido.obtener_por_id(id_pedido)
        if not pedido:
            flash("Pedido no encontrado", "danger")
            return redirect(next_url)

        # Busca el nombre legible del nuevo estado para incluirlo en el correo
        estados_info = Pedido.obtener_estados()
        nombre_estado = next(
            (e.get("nombre_estado") or e.get("nombre") for e in estados_info if e["id_estado"] == id_estado),
            "Desconocido",
        )

        # Persiste el cambio de estado en base de datos
        Pedido.actualizar_estado(id_pedido, id_estado)

        # Notifica al cliente por correo sin interrumpir el flujo si el SMTP falla
        try:
            usuario = Usuario.obtener_por_id(pedido["id_usuario"])
            send_order_status_update_email(
                usuario["email"],
                usuario["nombre"],
                id_pedido,
                nombre_estado,
            )
        except Exception:
            logger.exception("Error al enviar correo de actualización de estado")

        flash("Estado del pedido actualizado", "success")
    except ValueError as e:
        flash(str(e), "danger")
    except Exception as e:
        flash(f"Error al actualizar el estado: {str(e)}", "danger")

    return redirect(next_url)


# =========================================================
# CLIENTES (SOLO LECTURA)
# =========================================================
@trabajador_bp.route("/clientes")
def clientes():
    """
    Lista todos los usuarios/clientes registrados en modo solo lectura.

    Returns:
        str: Plantilla HTML `trabajador/clientes.html` renderizada.
    """
    lista_clientes = Usuario.listar_todos()
    return render_template("trabajador/clientes.html", clientes=lista_clientes)


# =========================================================
# MI CUENTA
# =========================================================
@trabajador_bp.route("/mi-cuenta")
def mi_cuenta():
    """
    Muestra la vista de perfil personal del trabajador autenticado.

    Returns:
        flask.Response | str: Redirección o plantilla `trabajador/mi_cuenta.html`.
    """
    id_usuario = session.get("id_usuario")
    if not id_usuario:
        return redirect(url_for("auth.login"))

    usuario = Usuario.obtener_por_id(id_usuario)
    if not usuario:
        flash("Usuario no encontrado", "danger")
        return redirect(url_for("trabajador.dashboard"))

    return render_template("trabajador/mi_cuenta.html", usuario=usuario)


@trabajador_bp.route("/mi-cuenta/editar", methods=["POST"])
def editar_mi_cuenta():
    """
    Procesa la actualización del perfil del trabajador (datos personales y cambio
    opcional de contraseña verificando la contraseña actual).

    Returns:
        flask.Response: Redirección a `trabajador.mi_cuenta`.
    """
    from app.utils.validaciones import (
        validar_telefono_colombiano,
        validar_email,
        validar_password,
        NOMBRE_REGEX,
    )

    id_usuario = session.get("id_usuario")
    if not id_usuario:
        return redirect(url_for("auth.login"))

    # Extrae los campos del formulario
    nombre = request.form.get("nombre", "").strip()
    apellido = request.form.get("apellido", "").strip()
    telefono_raw = request.form.get("telefono", "").strip()
    email = request.form.get("email", "").strip()
    contraseña_actual = request.form.get("contraseña_actual", "").strip()
    contraseña_nueva = request.form.get("contraseña_nueva", "").strip()

    # Validaciones de obligatoriedad, longitud y formato
    if not nombre or not apellido or not email:
        flash("Nombre, apellido y correo son obligatorios", "danger")
        return redirect(url_for("trabajador.mi_cuenta"))

    if len(nombre) < 2 or len(nombre) > 50 or not NOMBRE_REGEX.match(nombre):
        flash("El nombre debe tener entre 2 y 50 caracteres y solo puede contener letras y espacios", "danger")
        return redirect(url_for("trabajador.mi_cuenta"))

    if len(apellido) < 2 or len(apellido) > 50 or not NOMBRE_REGEX.match(apellido):
        flash("El apellido debe tener entre 2 y 50 caracteres y solo puede contener letras y espacios", "danger")
        return redirect(url_for("trabajador.mi_cuenta"))

    if not validar_email(email):
        flash("Ingresa un correo electrónico válido", "danger")
        return redirect(url_for("trabajador.mi_cuenta"))

    # Validación de celular colombiano (si se proporcionó)
    if telefono_raw:
        valido_tel, msg_tel, tel_normalizado = validar_telefono_colombiano(telefono_raw)
        if not valido_tel:
            flash(msg_tel, "danger")
            return redirect(url_for("trabajador.mi_cuenta"))
        telefono = tel_normalizado
    else:
        telefono = None

    # Si desea cambiar contraseña, valida fortaleza y comprueba la contraseña actual
    if contraseña_nueva:
        valido_pass, msg_pass = validar_password(contraseña_nueva)
        if not valido_pass:
            flash(msg_pass, "danger")
            return redirect(url_for("trabajador.mi_cuenta"))

        if not contraseña_actual:
            flash("Debes ingresar tu contraseña actual para cambiarla", "danger")
            return redirect(url_for("trabajador.mi_cuenta"))

        usuario = Usuario.obtener_por_id(id_usuario)
        if not Usuario.verificar_contraseña(contraseña_actual, usuario["password_hash"]):
            flash("La contraseña actual es incorrecta", "danger")
            return redirect(url_for("trabajador.mi_cuenta"))

    # Verifica unicidad del correo y guarda los cambios en base de datos
    try:
        existente = Usuario.obtener_por_email(email)
        if existente and int(existente["id_usuario"]) != int(id_usuario):
            flash("Ese correo electrónico ya está registrado por otro usuario", "danger")
            return redirect(url_for("trabajador.mi_cuenta"))

        if contraseña_nueva:
            Usuario.actualizar(
                id_usuario=id_usuario,
                nombre=nombre,
                apellido=apellido,
                telefono=telefono,
                email=email,
                contraseña=contraseña_nueva
            )
            flash("Perfil y contraseña actualizados correctamente", "success")
        else:
            Usuario.actualizar(
                id_usuario=id_usuario,
                nombre=nombre,
                apellido=apellido,
                telefono=telefono,
                email=email
            )
            flash("Perfil actualizado correctamente", "success")
    except Exception as err:
        err_str = str(err).lower()
        if "duplicate" in err_str or "1062" in err_str:
            flash("Ese correo electrónico ya está registrado por otro usuario", "danger")
        else:
            logger.exception("Error al actualizar perfil de trabajador: %s", err)
            flash("No se pudo actualizar el perfil. Intenta de nuevo.", "danger")

    return redirect(url_for("trabajador.mi_cuenta"))


# =========================================================
# REPORTES (SOLO INVENTARIO CRÍTICO)
# =========================================================
@trabajador_bp.route("/reportes")
def reportes():
    """
    Reporte operativo del trabajador: muestra únicamente el inventario crítico
    (productos cuyo stock actual es menor o igual a su stock mínimo).

    Returns:
        str: Plantilla HTML `trabajador/reportes.html` renderizada.
    """
    inventario_critico = Reporte.inventario_critico()
    return render_template("trabajador/reportes.html", inventario_critico=inventario_critico)
