from flask import Blueprint, render_template, session, redirect, url_for, flash, request, abort
from decimal import Decimal
from app.models.producto import Producto, VarianteProducto
from app.models.categoria import Categoria
from app.models.pedido import Pedido, PedidoDetalle
from app.models.usuario import Usuario

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

ID_ROL_ADMIN = 2  # rol 'admin'


@admin_bp.before_request
def verificar_permisos_admin():
    if session.get("id_rol") != ID_ROL_ADMIN:
        flash("No tienes permisos de administrador para acceder a esta sección", "danger")
        return redirect(url_for("productos.catalogo"))


# =========================================================
# DASHBOARD
# =========================================================
@admin_bp.route("/dashboard")
def dashboard():
    metricas = Pedido.obtener_metricas_dashboard()
    ultimos_pedidos = Pedido.listar_todos()[:6]
    estados = Pedido.obtener_estados()

    return render_template(
        "admin/dashboard.html",
        metricas=metricas,
        ultimos_pedidos=ultimos_pedidos,
        estados=estados
    )


# =========================================================
# PRODUCTOS (CRUD)
# =========================================================
@admin_bp.route("/productos")
def productos():
    lista_productos = Producto.listar_admin()
    return render_template("admin/productos/index.html", productos=lista_productos)


@admin_bp.route("/productos/nuevo", methods=["GET", "POST"])
def nuevo_producto():
    categorias = Categoria.listar()

    if request.method == "POST":
        id_categoria = request.form.get("id_categoria", type=int)
        nombre_producto = request.form.get("nombre_producto", "").strip()
        descripcion = request.form.get("descripcion", "").strip() or None
        marca = request.form.get("marca", "").strip() or None
        imagen_url = request.form.get("imagen_url", "").strip() or None

        if not id_categoria or not nombre_producto:
            flash("El nombre y la categoría del producto son obligatorios", "danger")
            return render_template("admin/productos/formulario.html", producto=None, categorias=categorias)

        id_producto = Producto.crear(
            id_categoria=id_categoria,
            nombre_producto=nombre_producto,
            descripcion=descripcion,
            marca=marca,
            imagen_url=imagen_url
        )

        # Crear variante inicial si se ingresaron datos
        presentacion = request.form.get("presentacion", "").strip()
        precio = request.form.get("precio", type=float)
        stock = request.form.get("stock", default=0, type=int)
        sku = request.form.get("sku", "").strip() or None

        if presentacion and precio is not None:
            VarianteProducto.crear(
                id_producto=id_producto,
                presentacion=presentacion,
                precio=precio,
                stock=stock,
                sku=sku
            )

        flash(f"Producto '{nombre_producto}' creado exitosamente", "success")
        return redirect(url_for("admin.productos"))

    return render_template("admin/productos/formulario.html", producto=None, categorias=categorias)


@admin_bp.route("/productos/<int:id_producto>/editar", methods=["GET", "POST"])
def editar_producto(id_producto):
    producto = Producto.obtener_por_id(id_producto)
    if not producto:
        flash("Producto no encontrado", "danger")
        return redirect(url_for("admin.productos"))

    categorias = Categoria.listar()

    if request.method == "POST":
        id_categoria = request.form.get("id_categoria", type=int)
        nombre_producto = request.form.get("nombre_producto", "").strip()
        descripcion = request.form.get("descripcion", "").strip() or None
        marca = request.form.get("marca", "").strip() or None
        imagen_url = request.form.get("imagen_url", "").strip() or None
        activo = 1 if request.form.get("activo") else 0

        if not id_categoria or not nombre_producto:
            flash("El nombre y la categoría son obligatorios", "danger")
            return render_template("admin/productos/formulario.html", producto=producto, categorias=categorias)

        Producto.actualizar(
            id_producto=id_producto,
            id_categoria=id_categoria,
            nombre_producto=nombre_producto,
            descripcion=descripcion,
            marca=marca,
            imagen_url=imagen_url,
            activo=activo
        )

        flash(f"Producto '{nombre_producto}' actualizado correctamente", "success")
        return redirect(url_for("admin.productos"))

    return render_template("admin/productos/formulario.html", producto=producto, categorias=categorias)


@admin_bp.route("/productos/<int:id_producto>/toggle", methods=["POST"])
def toggle_producto(id_producto):
    Producto.toggle_activo(id_producto)
    flash("Estado del producto modificado", "info")
    return redirect(url_for("admin.productos"))


@admin_bp.route("/productos/<int:id_producto>/eliminar", methods=["POST"])
def eliminar_producto(id_producto):
    try:
        Producto.eliminar(id_producto)
        flash("Producto eliminado correctamente", "info")
    except Exception as e:
        flash(f"No se pudo eliminar el producto (puede tener pedidos vinculados). Se recomienda desactivarlo.", "warning")

    return redirect(url_for("admin.productos"))


# =========================================================
# VARIANTES DE PRODUCTO
# =========================================================
@admin_bp.route("/productos/<int:id_producto>/variantes")
def variantes_producto(id_producto):
    producto = Producto.obtener_por_id(id_producto)
    if not producto:
        abort(404)

    variantes = VarianteProducto.listar_por_producto(id_producto)
    return render_template("admin/productos/variantes.html", producto=producto, variantes=variantes)


@admin_bp.route("/productos/<int:id_producto>/variantes/nueva", methods=["POST"])
def nueva_variante(id_producto):
    presentacion = request.form.get("presentacion", "").strip()
    precio = request.form.get("precio", type=float)
    stock = request.form.get("stock", default=0, type=int)
    sku = request.form.get("sku", "").strip() or None

    if not presentacion or precio is None or precio < 0:
        flash("La presentación y un precio válido son obligatorios", "danger")
    else:
        VarianteProducto.crear(
            id_producto=id_producto,
            presentacion=presentacion,
            precio=precio,
            stock=stock,
            sku=sku
        )
        flash("Variante agregada correctamente", "success")

    return redirect(url_for("admin.variantes_producto", id_producto=id_producto))


@admin_bp.route("/variantes/<int:id_variante>/editar", methods=["POST"])
def editar_variante(id_variante):
    id_producto = request.form.get("id_producto", type=int)
    presentacion = request.form.get("presentacion", "").strip()
    precio = request.form.get("precio", type=float)
    stock = request.form.get("stock", default=0, type=int)
    sku = request.form.get("sku", "").strip() or None

    if not presentacion or precio is None:
        flash("Datos de variante inválidos", "danger")
    else:
        VarianteProducto.actualizar(
            id_variante=id_variante,
            presentacion=presentacion,
            precio=precio,
            stock=stock,
            sku=sku
        )
        flash("Variante actualizada correctamente", "success")

    return redirect(url_for("admin.variantes_producto", id_producto=id_producto))


@admin_bp.route("/variantes/<int:id_variante>/eliminar", methods=["POST"])
def eliminar_variante(id_variante):
    id_producto = request.form.get("id_producto", type=int)
    try:
        VarianteProducto.eliminar(id_variante)
        flash("Variante eliminada", "info")
    except Exception:
        flash("No se puede eliminar la variante porque está asociada a pedidos previos", "warning")

    return redirect(url_for("admin.variantes_producto", id_producto=id_producto))


# =========================================================
# CATEGORÍAS
# =========================================================
@admin_bp.route("/categorias")
def categorias():
    lista = Categoria.listar_con_conteo()
    return render_template("admin/categorias/index.html", categorias=lista)


@admin_bp.route("/categorias/nueva", methods=["POST"])
def nueva_categoria():
    nombre = request.form.get("nombre_categoria", "").strip()
    descripcion = request.form.get("descripcion", "").strip() or None

    if not nombre:
        flash("El nombre de la categoría es obligatorio", "danger")
    else:
        try:
            Categoria.crear(nombre, descripcion)
            flash(f"Categoría '{nombre}' creada", "success")
        except Exception:
            flash(f"Error al crear: ya existe una categoría con ese nombre", "danger")

    return redirect(url_for("admin.categorias"))


@admin_bp.route("/categorias/<int:id_categoria>/editar", methods=["POST"])
def editar_categoria(id_categoria):
    nombre = request.form.get("nombre_categoria", "").strip()
    descripcion = request.form.get("descripcion", "").strip() or None

    if not nombre:
        flash("El nombre de categoría es obligatorio", "danger")
    else:
        try:
            Categoria.actualizar(id_categoria, nombre, descripcion)
            flash("Categoría actualizada correctamente", "success")
        except Exception:
            flash("Error: el nombre ya pertenece a otra categoría", "danger")

    return redirect(url_for("admin.categorias"))


@admin_bp.route("/categorias/<int:id_categoria>/eliminar", methods=["POST"])
def eliminar_categoria(id_categoria):
    try:
        Categoria.eliminar(id_categoria)
        flash("Categoría eliminada", "info")
    except Exception:
        flash("No se puede eliminar una categoría que contiene productos vinculados", "warning")

    return redirect(url_for("admin.categorias"))


# =========================================================
# PEDIDOS
# =========================================================
@admin_bp.route("/pedidos")
def pedidos():
    filtro_estado = request.args.get("estado")
    pedidos_lista = Pedido.listar_todos(filtro_estado=filtro_estado)
    estados = Pedido.obtener_estados()

    return render_template(
        "admin/pedidos/index.html",
        pedidos=pedidos_lista,
        estados=estados,
        filtro_actual=filtro_estado
    )


@admin_bp.route("/pedidos/<int:id_pedido>")
def detalle_pedido(id_pedido):
    pedido = Pedido.obtener_por_id(id_pedido)
    if not pedido:
        abort(404)

    detalles = PedidoDetalle.listar_por_pedido(id_pedido)
    estados = Pedido.obtener_estados()

    return render_template(
        "admin/pedidos/detalle.html",
        pedido=pedido,
        detalles=detalles,
        estados=estados
    )


@admin_bp.route("/pedidos/<int:id_pedido>/estado", methods=["POST"])
def cambiar_estado_pedido(id_pedido):
    id_estado = request.form.get("id_estado", type=int)
    next_url = request.form.get("next") or url_for("admin.pedidos")

    if id_estado:
        Pedido.actualizar_estado(id_pedido, id_estado)
        flash(f"Estado del pedido #{id_pedido} actualizado exitosamente", "success")

    return redirect(next_url)


# =========================================================
# USUARIOS
# =========================================================
@admin_bp.route("/usuarios")
def usuarios():
    lista = Usuario.listar_todos()
    roles = Usuario.obtener_roles()
    return render_template("admin/usuarios/index.html", usuarios=lista, roles=roles)


@admin_bp.route("/usuarios/<int:id_usuario>/rol", methods=["POST"])
def cambiar_rol_usuario(id_usuario):
    id_rol = request.form.get("id_rol", type=int)
    if id_rol:
        Usuario.actualizar_rol(id_usuario, id_rol)
        flash("Rol del usuario actualizado", "success")

    return redirect(url_for("admin.usuarios"))


@admin_bp.route("/usuarios/<int:id_usuario>/toggle", methods=["POST"])
def toggle_usuario(id_usuario):
    if id_usuario == session.get("id_usuario"):
        flash("No puedes desactivar tu propia cuenta de administrador", "warning")
    else:
        Usuario.toggle_activo(id_usuario)
        flash("Estado del usuario modificado", "info")

    return redirect(url_for("admin.usuarios"))
