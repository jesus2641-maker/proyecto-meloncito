from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from app.models.producto import Producto, VarianteProducto
from app.models.pedido import Pedido
from app.models.usuario import Usuario
from app.models.categoria import Categoria
from app.utils.decoradores import requiere_trabajador_o_admin
from app.utils.email_service import send_order_status_update_email

trabajador_bp = Blueprint("trabajador", __name__, url_prefix="/trabajador")


@trabajador_bp.before_request
def verificar_permisos_trabajador():
    """Verifica que el usuario tenga rol de trabajador o administrador."""
    from app.utils.decoradores import ID_ROL_TRABAJADOR, ID_ROL_ADMIN
    if session.get("id_rol") not in [ID_ROL_TRABAJADOR, ID_ROL_ADMIN]:
        flash("No tienes permisos para acceder a esta sección", "danger")
        return redirect(url_for("productos.catalogo"))


# =========================================================
# DASHBOARD TRABAJADOR
# =========================================================
@trabajador_bp.route("/dashboard")
def dashboard():
    """Dashboard del trabajador con métricas básicas."""
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
    """Lista de productos (solo lectura)."""
    lista_productos = Producto.listar_admin()
    return render_template("trabajador/productos/index.html", productos=lista_productos)


@trabajador_bp.route("/productos/<int:id_producto>/variantes")
def variantes_producto(id_producto):
    """Ver variantes de un producto (solo lectura)."""
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
    """Ver inventario completo con filtros."""
    from app.models.categoria import Categoria

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
    """Actualizar stock de una variante."""
    id_variante = request.form.get("id_variante", type=int)
    nuevo_stock = request.form.get("stock", type=int)
    
    if not id_variante or nuevo_stock is None:
        flash("Datos inválidos", "danger")
        return redirect(url_for("trabajador.inventario"))
    
    if nuevo_stock < 0:
        flash("El stock no puede ser negativo", "danger")
        return redirect(url_for("trabajador.inventario"))
    
    VarianteProducto.actualizar_stock(id_variante, nuevo_stock)
    flash("Stock actualizado correctamente", "success")
    return redirect(url_for("trabajador.inventario"))


# =========================================================
# PEDIDOS (VER Y CAMBIAR ESTADO)
# =========================================================
@trabajador_bp.route("/pedidos")
def pedidos():
    """Lista de pedidos."""
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
    """Ver detalle de un pedido."""
    pedido = Pedido.obtener_por_id(id_pedido)
    if not pedido:
        flash("Pedido no encontrado", "danger")
        return redirect(url_for("trabajador.pedidos"))
    
    from app.models.pedido import PedidoDetalle
    detalles = PedidoDetalle.listar_por_pedido(id_pedido)
    estados = Pedido.obtener_estados()
    return render_template(
        "trabajador/pedidos/detalle.html",
        pedido=pedido,
        detalles=detalles,
        estados=estados
    )


@trabajador_bp.route("/pedidos/<int:id_pedido>/estado", methods=["POST"])
def cambiar_estado_pedido(id_pedido):
    """Cambiar estado de un pedido (trabajador puede cambiar estados básicos)."""
    id_estado = request.form.get("id_estado", type=int)
    next_url = request.form.get("next") or url_for("trabajador.pedidos")
    
    if not id_estado:
        flash("Estado inválido", "danger")
        return redirect(next_url)
    
    # El trabajador no puede cancelar pedidos (solo admin)
    if id_estado == 5:  # cancelado
        flash("No tienes permisos para cancelar pedidos. Contacta al administrador.", "warning")
        return redirect(next_url)
    
    # Obtener información del pedido antes de actualizar
    pedido = Pedido.obtener_por_id(id_pedido)
    if not pedido:
        flash("Pedido no encontrado", "danger")
        return redirect(next_url)

    estados_info = Pedido.obtener_estados()
    nombre_estado = next((e['nombre'] for e in estados_info if e['id_estado'] == id_estado), "Desconocido")

    Pedido.actualizar_estado(id_pedido, id_estado)

    try:
        usuario = Usuario.obtener_por_id(pedido['id_usuario'])
        send_order_status_update_email(
            usuario['email'],
            usuario['nombre'],
            id_pedido,
            nombre_estado
        )
    except Exception as e:
        print(f"Error al enviar correo de actualización de estado: {e}")
    flash("Estado del pedido actualizado", "success")
    return redirect(next_url)


# =========================================================
# CLIENTES (SOLO LECTURA)
# =========================================================
@trabajador_bp.route("/clientes")
def clientes():
    """Lista de clientes (solo lectura)."""
    lista_clientes = Usuario.listar_todos()
    return render_template("trabajador/clientes.html", clientes=lista_clientes)


# =========================================================
# MI CUENTA
# =========================================================
@trabajador_bp.route("/mi-cuenta")
def mi_cuenta():
    """Perfil del trabajador."""
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
    """Editar perfil del trabajador."""
    id_usuario = session.get("id_usuario")
    if not id_usuario:
        return redirect(url_for("auth.login"))
    
    nombre = request.form.get("nombre", "").strip()
    apellido = request.form.get("apellido", "").strip()
    telefono = request.form.get("telefono", "").strip() or None
    email = request.form.get("email", "").strip()
    contraseña_actual = request.form.get("contraseña_actual", "").strip()
    contraseña_nueva = request.form.get("contraseña_nueva", "").strip()
    
    if not nombre or not apellido or not email:
        flash("Nombre, apellido y correo son obligatorios", "danger")
        return redirect(url_for("trabajador.mi_cuenta"))
    
    if contraseña_nueva:
        if not contraseña_actual:
            flash("Debes ingresar tu contraseña actual para cambiarla", "danger")
            return redirect(url_for("trabajador.mi_cuenta"))
        
        usuario = Usuario.obtener_por_id(id_usuario)
        if not Usuario.verificar_contraseña(contraseña_actual, usuario.contraseña):
            flash("La contraseña actual es incorrecta", "danger")
            return redirect(url_for("trabajador.mi_cuenta"))
        
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
    
    return redirect(url_for("trabajador.mi_cuenta"))
