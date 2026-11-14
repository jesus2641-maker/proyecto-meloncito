import logging
import re
from flask import Blueprint, render_template, session, redirect, url_for, flash, request, abort, jsonify, Response
from datetime import datetime
from decimal import Decimal
from app.models.producto import Producto, VarianteProducto
from app.models.categoria import Categoria
from app.models.pedido import Pedido, PedidoDetalle, ESTADO_CANCELADO
from app.models.pago import Pago, ESTADO_PAGO_COMPLETADO, ESTADO_PAGO_PENDIENTE, ESTADO_PAGO_CANCELADO
from app.services.pagos_paypal import cancelar_pedido_con_reembolso
from app.models.usuario import Usuario
from app.models.oferta import Oferta
from app.models.proveedor import Proveedor
from app.models.compra import Compra, CompraDetalle
from app.models.reporte import Reporte
from app.utils.reportes_utils import parsear_rango_fechas, elegir_agrupacion, generar_csv
from app.utils.cloudinary_utils import upload_image, delete_image
from app.utils.email_service import send_order_status_update_email
from app.utils.db import get_connection

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

ID_ROL_ADMIN = 2  # rol 'admin'

REGEX_PRECIO = re.compile(r"^\d+(\.\d{1,2})?$")
REGEX_ENTERO = re.compile(r"^\d+$")


def _parsear_precio(valor_raw):
    """Valida con regex ^\\d+(\\.\\d{1,2})?$ y retorna float > 0 o None."""
    texto = (valor_raw if isinstance(valor_raw, str) else str(valor_raw or "")).strip()
    if not texto or not REGEX_PRECIO.match(texto):
        return None
    valor = float(texto)
    if valor <= 0:
        return None
    return valor


def _parsear_entero_no_negativo(valor_raw):
    """Valida con regex ^\\d+$ y retorna int >= 0 o None."""
    texto = (valor_raw if isinstance(valor_raw, str) else str(valor_raw or "")).strip()
    if not texto or not REGEX_ENTERO.match(texto):
        return None
    return int(texto)


@admin_bp.before_request
def verificar_permisos_admin():
    id_rol_session = session.get("id_rol")
    if id_rol_session != ID_ROL_ADMIN:
        logger.warning("Acceso denegado al panel de administración")
        flash("No tienes permisos de administrador.", "danger")
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
        categorias_seleccionadas = request.form.getlist("categorias")
        nombre_producto = request.form.get("nombre_producto", "").strip()
        descripcion = request.form.get("descripcion", "").strip() or None
        marca = request.form.get("marca", "").strip() or None
        imagen_url = request.form.get("imagen_url", "").strip() or None

        if not categorias_seleccionadas:
            flash("Selecciona al menos una categoría", "danger")
            return render_template("admin/productos/formulario.html", producto=None, categorias=categorias)

        if len(categorias_seleccionadas) > 2:
            flash("Puedes seleccionar máximo 2 categorías", "danger")
            return render_template("admin/productos/formulario.html", producto=None, categorias=categorias)

        if not nombre_producto:
            flash("El nombre del producto es obligatorio", "danger")
            return render_template("admin/productos/formulario.html", producto=None, categorias=categorias)

        # Leer y validar la variante inicial ANTES de crear el producto,
        # para no dejar productos sin variante si el precio o el stock son inválidos.
        presentacion = request.form.get("presentacion", "").strip()
        precio_raw = request.form.get("precio", "").strip()
        stock_raw = request.form.get("stock", "0").strip()
        if stock_raw == "":
            stock_raw = "0"
        sku = request.form.get("sku", "").strip() or None

        precio = _parsear_precio(precio_raw)
        if precio is None:
            flash("El precio debe ser mayor a cero y contener solo números válidos", "danger")
            return render_template("admin/productos/formulario.html", producto=None, categorias=categorias)

        if not presentacion:
            flash("La presentación de la variante inicial es obligatoria", "danger")
            return render_template("admin/productos/formulario.html", producto=None, categorias=categorias)

        stock = _parsear_entero_no_negativo(stock_raw)
        if stock is None:
            flash("El stock no puede ser negativo y debe contener solo números enteros", "danger")
            return render_template("admin/productos/formulario.html", producto=None, categorias=categorias)

        # Manejar subida de imagen a Cloudinary
        imagen_public_id = None
        imagen_file = request.files.get("imagen_file")

        if imagen_file and imagen_file.filename:
            cloudinary_result = upload_image(imagen_file, folder="beerhouse/productos")
            if cloudinary_result:
                imagen_url = cloudinary_result['secure_url']
                imagen_public_id = cloudinary_result['public_id']
            else:
                flash("Error al subir la imagen. Verifica que las credenciales de Cloudinary estén configuradas en .env", "danger")
                return render_template("admin/productos/formulario.html", producto=None, categorias=categorias)

        # Convertir a enteros solo después de validar la cantidad
        try:
            lista_categorias = [int(cat) for cat in categorias_seleccionadas]
        except (ValueError, TypeError):
            flash("Categoría inválida", "danger")
            return render_template("admin/productos/formulario.html", producto=None, categorias=categorias)

        id_producto = Producto.crear(
            nombre_producto=nombre_producto,
            descripcion=descripcion,
            marca=marca,
            imagen_url=imagen_url,
            imagen_public_id=imagen_public_id,
            lista_categorias=lista_categorias
        )

        # Crear la variante inicial; si falla, eliminar el producto para no dejarlo huérfano
        try:
            VarianteProducto.crear(
                id_producto=id_producto,
                presentacion=presentacion,
                precio=precio,
                stock=stock,
                sku=sku
            )
        except Exception as e:
            logger.exception("Error al crear la variante inicial del producto %s", id_producto)
            try:
                Producto.eliminar(id_producto)
            except Exception:
                logger.exception("No se pudo eliminar el producto huérfano %s", id_producto)
            if isinstance(e, ValueError):
                mensaje = str(e)
            else:
                mensaje = "No se pudo crear la variante (verifica que el SKU no esté repetido)"
            flash(f"El producto no se guardó: {mensaje}", "danger")
            return render_template("admin/productos/formulario.html", producto=producto, categorias=categorias)

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
        categorias_seleccionadas = request.form.getlist("categorias")
        nombre_producto = request.form.get("nombre_producto", "").strip()
        descripcion = request.form.get("descripcion", "").strip() or None
        marca = request.form.get("marca", "").strip() or None
        imagen_url = request.form.get("imagen_url", "").strip() or None
        activo = 1 if request.form.get("activo") else 0

        if not categorias_seleccionadas:
            flash("Selecciona al menos una categoría", "danger")
            return render_template("admin/productos/formulario.html", producto=producto, categorias=categorias)

        if len(categorias_seleccionadas) > 2:
            flash("Puedes seleccionar máximo 2 categorías", "danger")
            return render_template("admin/productos/formulario.html", producto=producto, categorias=categorias)

        if not nombre_producto:
            flash("El nombre del producto es obligatorio", "danger")
            return render_template("admin/productos/formulario.html", producto=producto, categorias=categorias)

        # Manejar subida de nueva imagen a Cloudinary
        imagen_public_id = producto.get('imagen_public_id')
        imagen_file = request.files.get("imagen_file")

        if imagen_file and imagen_file.filename:
            if producto.get('imagen_public_id'):
                delete_image(producto['imagen_public_id'])

            cloudinary_result = upload_image(imagen_file, folder="beerhouse/productos")
            if cloudinary_result:
                imagen_url = cloudinary_result['secure_url']
                imagen_public_id = cloudinary_result['public_id']
            else:
                flash("Error al subir la nueva imagen. Verifica que las credenciales de Cloudinary estén configuradas en .env", "danger")
                return render_template("admin/productos/formulario.html", producto=producto, categorias=categorias)

        # Convertir a enteros solo después de validar la cantidad
        try:
            lista_categorias = [int(cat) for cat in categorias_seleccionadas]
        except (ValueError, TypeError):
            flash("Categoría inválida", "danger")
            return render_template("admin/productos/formulario.html", producto=producto, categorias=categorias)

        Producto.actualizar(
            id_producto=id_producto,
            nombre_producto=nombre_producto,
            descripcion=descripcion,
            marca=marca,
            imagen_url=imagen_url,
            imagen_public_id=imagen_public_id,
            activo=activo,
            lista_categorias=lista_categorias
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
        flash("Producto eliminado correctamente", "success")
    except ValueError as e:
        flash(str(e), "warning")
    except Exception as e:
        flash(f"Error al eliminar el producto: {str(e)}", "danger")

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
    precio_raw = request.form.get("precio", "").strip()
    stock_raw = request.form.get("stock", "0").strip()
    stock_minimo_raw = request.form.get("stock_minimo", "5").strip()
    sku = request.form.get("sku", "").strip() or None

    precio = _parsear_precio(precio_raw)
    stock = _parsear_entero_no_negativo(stock_raw if stock_raw != "" else "0")
    stock_minimo = _parsear_entero_no_negativo(stock_minimo_raw if stock_minimo_raw != "" else "5")

    if precio is None:
        flash("El precio debe ser mayor a cero y contener solo números válidos", "danger")
    elif not presentacion:
        flash("La presentación y un precio válido son obligatorios", "danger")
    elif stock is None or stock_minimo is None:
        flash("El stock no puede ser negativo y debe contener solo números enteros", "danger")
    else:
        try:
            VarianteProducto.crear(
                id_producto=id_producto,
                presentacion=presentacion,
                precio=precio,
                stock=stock,
                stock_minimo=stock_minimo,
                sku=sku
            )
            flash("Variante agregada correctamente", "success")
        except ValueError as e:
            flash(str(e), "danger")

    return redirect(url_for("admin.variantes_producto", id_producto=id_producto))


@admin_bp.route("/variantes/<int:id_variante>/editar", methods=["POST"])
def editar_variante(id_variante):
    id_producto = request.form.get("id_producto", type=int)
    presentacion = request.form.get("presentacion", "").strip()
    precio_raw = request.form.get("precio", "").strip()
    stock_raw = request.form.get("stock", "0").strip()
    stock_minimo_raw = request.form.get("stock_minimo", "5").strip()
    sku = request.form.get("sku", "").strip() or None

    precio = _parsear_precio(precio_raw)
    stock = _parsear_entero_no_negativo(stock_raw if stock_raw != "" else "0")
    stock_minimo = _parsear_entero_no_negativo(stock_minimo_raw if stock_minimo_raw != "" else "5")

    if precio is None:
        flash("El precio debe ser mayor a cero y contener solo números válidos", "danger")
    elif not presentacion:
        flash("Datos de variante inválidos", "danger")
    elif stock is None or stock_minimo is None:
        flash("El stock no puede ser negativo y debe contener solo números enteros", "danger")
    else:
        try:
            VarianteProducto.actualizar(
                id_variante=id_variante,
                presentacion=presentacion,
                precio=precio,
                stock=stock,
                stock_minimo=stock_minimo,
                sku=sku
            )
            flash("Variante actualizada correctamente", "success")
        except ValueError as e:
            flash(str(e), "danger")

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
# INVENTARIO
# =========================================================
@admin_bp.route("/inventario")
def inventario():
    """Muestra el inventario completo con alertas de stock y filtros."""
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
        "admin/inventario.html",
        inventario=inventario,
        alertas=alertas,
        categorias=categorias,
        busqueda=busqueda,
        id_categoria=id_categoria,
        estado_stock=estado_stock,
        filtro_bajo=filtro_bajo,
        ordenar_por=ordenar_por
    )


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
    imagen_url = request.form.get("imagen_url", "").strip() or None

    if not nombre:
        flash("El nombre de la categoría es obligatorio", "danger")
    else:
        try:
            # Manejar subida de imagen a Cloudinary
            imagen_public_id = None
            imagen_file = request.files.get("imagen_file")

            if imagen_file and imagen_file.filename:
                cloudinary_result = upload_image(imagen_file, folder="beerhouse/categorias")
                if cloudinary_result:
                    imagen_url = cloudinary_result['secure_url']
                    imagen_public_id = cloudinary_result['public_id']
                else:
                    flash("Error al subir la imagen. Verifica que las credenciales de Cloudinary estén configuradas en .env", "danger")
                    return redirect(url_for("admin.categorias"))

            Categoria.crear(nombre, descripcion, imagen_url, imagen_public_id)
            flash(f"Categoría '{nombre}' creada", "success")
        except Exception:
            flash(f"Error al crear: ya existe una categoría con ese nombre", "danger")

    return redirect(url_for("admin.categorias"))


@admin_bp.route("/categorias/<int:id_categoria>/editar", methods=["POST"])
def editar_categoria(id_categoria):
    categoria = Categoria.obtener_por_id(id_categoria)
    if not categoria:
        flash("Categoría no encontrada", "danger")
        return redirect(url_for("admin.categorias"))
    
    nombre = request.form.get("nombre_categoria", "").strip()
    descripcion = request.form.get("descripcion", "").strip() or None
    imagen_url = request.form.get("imagen_url", "").strip() or None

    if not nombre:
        flash("El nombre de categoría es obligatorio", "danger")
    else:
        try:
            # Manejar subida de nueva imagen a Cloudinary
            imagen_public_id = categoria.get('imagen_public_id')
            imagen_file = request.files.get("imagen_file")

            if imagen_file and imagen_file.filename:
                if categoria.get('imagen_public_id'):
                    delete_image(categoria['imagen_public_id'])

                cloudinary_result = upload_image(imagen_file, folder="beerhouse/categorias")
                if cloudinary_result:
                    imagen_url = cloudinary_result['secure_url']
                    imagen_public_id = cloudinary_result['public_id']
                else:
                    flash("Error al subir la nueva imagen. Verifica que las credenciales de Cloudinary estén configuradas en .env", "danger")
                    return redirect(url_for("admin.categorias"))

            Categoria.actualizar(id_categoria, nombre, descripcion, imagen_url, imagen_public_id)
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
    pago = Pago.obtener_por_pedido(id_pedido)

    return render_template(
        "admin/pedidos/detalle.html",
        pedido=pedido,
        detalles=detalles,
        estados=estados,
        pago=pago,
    )


@admin_bp.route("/pedidos/<int:id_pedido>/estado", methods=["POST"])
def cambiar_estado_pedido(id_pedido):
    id_estado = request.form.get("id_estado", type=int)
    next_url = request.form.get("next") or url_for("admin.pedidos")

    if id_estado:
        try:
            # Obtener información del pedido antes de actualizar
            pedido = Pedido.obtener_por_id(id_pedido)
            if not pedido:
                flash("Pedido no encontrado", "danger")
                return redirect(next_url)

            # Si el admin va a cancelar el pedido, gestionar reembolso si aplica
            if id_estado == ESTADO_CANCELADO:
                pago = Pago.obtener_por_pedido(id_pedido)
                if pago and pago.get("estado") == ESTADO_PAGO_COMPLETADO:
                    try:
                        cancelar_pedido_con_reembolso(id_pedido)
                        flash(f"Pedido #{id_pedido} cancelado y pago de PayPal reembolsado exitosamente", "success")
                        return redirect(next_url)
                    except Exception as e:
                        logger.exception("Error al reembolsar pago para pedido %s: %s", id_pedido, e)
                        flash(f"No se pudo cancelar el pedido porque el reembolso en PayPal falló: {e}", "danger")
                        return redirect(next_url)
                elif pago and pago.get("estado") == ESTADO_PAGO_PENDIENTE:
                    Pedido.actualizar_estado(id_pedido, ESTADO_CANCELADO)
                    Pago.marcar(id_pedido, ESTADO_PAGO_CANCELADO)
                    flash(f"Pedido #{id_pedido} cancelado y stock liberado", "success")
                    return redirect(next_url)

            estados_info = Pedido.obtener_estados()
            nombre_estado = next((e.get('nombre_estado') or e.get('nombre') for e in estados_info if e['id_estado'] == id_estado), "Desconocido")

            Pedido.actualizar_estado(id_pedido, id_estado)

            try:
                usuario = Usuario.obtener_por_id(pedido['id_usuario'])
                send_order_status_update_email(
                    usuario['email'],
                    usuario['nombre'],
                    id_pedido,
                    nombre_estado
                )
            except Exception:
                logger.exception("Error al enviar correo de actualización de estado")

            flash(f"Estado del pedido #{id_pedido} actualizado exitosamente", "success")
        except ValueError as e:
            flash(str(e), "danger")
        except Exception as e:
            flash(f"Error al actualizar el estado: {str(e)}", "danger")

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


# =========================================================
# MI CUENTA ADMIN
# =========================================================
@admin_bp.route("/mi-cuenta")
def mi_cuenta():
    """Página de perfil del administrador."""
    id_usuario = session.get("id_usuario")
    if not id_usuario:
        return redirect(url_for("auth.login"))
    
    usuario = Usuario.obtener_por_id(id_usuario)
    if not usuario:
        flash("Usuario no encontrado", "danger")
        return redirect(url_for("admin.dashboard"))
    
    return render_template("admin/mi_cuenta.html", usuario=usuario)


@admin_bp.route("/mi-cuenta/editar", methods=["POST"])
def editar_mi_cuenta():
    """Edita el perfil del administrador actual."""
    id_usuario = session.get("id_usuario")
    if not id_usuario:
        return redirect(url_for("auth.login"))
    
    nombre = request.form.get("nombre", "").strip()
    apellido = request.form.get("apellido", "").strip()
    telefono_raw = request.form.get("telefono", "").strip()
    email = request.form.get("email", "").strip()
    contraseña_actual = request.form.get("contraseña_actual", "").strip()
    contraseña_nueva = request.form.get("contraseña_nueva", "").strip()
    
    if not nombre or not apellido or not email:
        flash("Nombre, apellido y correo son obligatorios", "danger")
        return redirect(url_for("admin.mi_cuenta"))

    # Validación de celular colombiano
    from app.utils.validaciones import validar_telefono_colombiano
    if telefono_raw:
        valido_tel, msg_tel, tel_normalizado = validar_telefono_colombiano(telefono_raw)
        if not valido_tel:
            flash(msg_tel, "danger")
            return redirect(url_for("admin.mi_cuenta"))
        telefono = tel_normalizado
    else:
        telefono = None
    
    # Si se quiere cambiar la contraseña
    if contraseña_nueva:
        if not contraseña_actual:
            flash("Debes ingresar tu contraseña actual para cambiarla", "danger")
            return redirect(url_for("admin.mi_cuenta"))
        
        # Verificar contraseña actual
        usuario = Usuario.obtener_por_id(id_usuario)
        if not Usuario.verificar_contraseña(contraseña_actual, usuario['password_hash']):
            flash("La contraseña actual es incorrecta", "danger")
            return redirect(url_for("admin.mi_cuenta"))
        
        # Actualizar con nueva contraseña
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
        # Actualizar sin cambiar contraseña
        Usuario.actualizar(
            id_usuario=id_usuario,
            nombre=nombre,
            apellido=apellido,
            telefono=telefono,
            email=email
        )
        flash("Perfil actualizado correctamente", "success")
    
    return redirect(url_for("admin.mi_cuenta"))


# =========================================================
# OFERTAS
# =========================================================
@admin_bp.route("/ofertas")
def ofertas():
    """Lista todas las ofertas."""
    lista_ofertas = Oferta.listar_todas()
    return render_template("admin/ofertas/index.html", ofertas=lista_ofertas)


@admin_bp.route("/ofertas/nueva", methods=["GET", "POST"])
def nueva_oferta():
    """Crea una nueva oferta."""
    productos = Producto.listar_admin()
    
    if request.method == "POST":
        id_producto = request.form.get("id_producto", type=int)
        id_variante = request.form.get("id_variante", type=int) or None
        descuento_raw = request.form.get("descuento_porcentaje", "").strip()
        precio_oferta_raw = request.form.get("precio_oferta", "").strip()
        titulo = request.form.get("titulo", "").strip()
        descripcion = request.form.get("descripcion", "").strip() or None
        fecha_inicio = request.form.get("fecha_inicio") or None
        fecha_fin = request.form.get("fecha_fin") or None

        precio_oferta = _parsear_precio(precio_oferta_raw)
        descuento_porcentaje = _parsear_precio(descuento_raw)

        if not id_producto or not titulo:
            flash("El producto, descuento, precio y título son obligatorios", "danger")
            return render_template("admin/ofertas/formulario.html", oferta=None, productos=productos)

        if precio_oferta is None:
            flash("El precio de oferta debe ser mayor a cero y contener solo números válidos", "danger")
            return render_template("admin/ofertas/formulario.html", oferta=None, productos=productos)

        if descuento_porcentaje is None or descuento_porcentaje > 100:
            flash("El porcentaje de descuento debe ser un número válido entre 0.01 y 100", "danger")
            return render_template("admin/ofertas/formulario.html", oferta=None, productos=productos)

        try:
            Oferta.crear(id_producto, id_variante, descuento_porcentaje, precio_oferta, titulo, descripcion, fecha_inicio, fecha_fin)
            flash(f"Oferta '{titulo}' creada", "success")
            return redirect(url_for("admin.ofertas"))
        except Exception as e:
            flash(f"Error al crear oferta: {str(e)}", "danger")

    return render_template("admin/ofertas/formulario.html", oferta=None, productos=productos)


@admin_bp.route("/ofertas/<int:id_oferta>/editar", methods=["GET", "POST"])
def editar_oferta(id_oferta):
    """Edita una oferta existente."""
    oferta = Oferta.obtener_por_id(id_oferta)
    if not oferta:
        flash("Oferta no encontrada", "danger")
        return redirect(url_for("admin.ofertas"))

    productos = Producto.listar_admin()

    if request.method == "POST":
        id_producto = request.form.get("id_producto", type=int)
        id_variante = request.form.get("id_variante", type=int) or None
        descuento_raw = request.form.get("descuento_porcentaje", "").strip()
        precio_oferta_raw = request.form.get("precio_oferta", "").strip()
        titulo = request.form.get("titulo", "").strip()
        descripcion = request.form.get("descripcion", "").strip() or None
        activa = 1 if request.form.get("activa") else 0
        fecha_inicio = request.form.get("fecha_inicio") or None
        fecha_fin = request.form.get("fecha_fin") or None

        precio_oferta = _parsear_precio(precio_oferta_raw)
        descuento_porcentaje = _parsear_precio(descuento_raw)

        if not id_producto or not titulo:
            flash("El producto, descuento, precio y título son obligatorios", "danger")
            return render_template("admin/ofertas/formulario.html", oferta=oferta, productos=productos)

        if precio_oferta is None:
            flash("El precio de oferta debe ser mayor a cero y contener solo números válidos", "danger")
            return render_template("admin/ofertas/formulario.html", oferta=oferta, productos=productos)

        if descuento_porcentaje is None or descuento_porcentaje > 100:
            flash("El porcentaje de descuento debe ser un número válido entre 0.01 y 100", "danger")
            return render_template("admin/ofertas/formulario.html", oferta=oferta, productos=productos)

        try:
            Oferta.actualizar(id_oferta, id_producto, id_variante, descuento_porcentaje, precio_oferta, titulo, descripcion, activa, fecha_inicio, fecha_fin)
            flash(f"Oferta '{titulo}' actualizada", "success")
            return redirect(url_for("admin.ofertas"))
        except Exception as e:
            flash(f"Error al actualizar oferta: {str(e)}", "danger")

    return render_template("admin/ofertas/formulario.html", oferta=oferta, productos=productos)


@admin_bp.route("/ofertas/<int:id_oferta>/toggle", methods=["POST"])
def toggle_oferta(id_oferta):
    """Activa/desactiva una oferta."""
    Oferta.toggle_activa(id_oferta)
    flash("Estado de la oferta modificado", "info")
    return redirect(url_for("admin.ofertas"))


@admin_bp.route("/ofertas/<int:id_oferta>/eliminar", methods=["POST"])
def eliminar_oferta(id_oferta):
    """Elimina una oferta."""
    try:
        Oferta.eliminar(id_oferta)
        flash("Oferta eliminada", "info")
    except Exception as e:
        flash(f"Error al eliminar oferta: {str(e)}", "danger")
    
    return redirect(url_for("admin.ofertas"))


# API para cargar variantes de un producto
@admin_bp.route("/api/productos/<int:id_producto>/variantes")
def api_variantes_producto(id_producto):
    """API para obtener variantes de un producto (para el formulario de ofertas)."""
    variantes = VarianteProducto.listar_por_producto(id_producto)
    return jsonify([{
        'id_variante': v['id_variante'],
        'presentacion': v['presentacion'],
        'precio': float(v['precio'])
    } for v in variantes])


# =========================================================
# COMPRAS (HISTORIAL Y REGISTRO)
# =========================================================
@admin_bp.route("/compras")
def compras():
    """Historial de compras realizadas con métricas de inversión."""
    lista_compras = Compra.listar_todas()
    metricas = Compra.obtener_metricas()
    return render_template("admin/compras/index.html", compras=lista_compras, metricas=metricas)


@admin_bp.route("/compras/nueva", methods=["GET", "POST"])
def nueva_compra():
    """Registra una nueva compra a un proveedor con uno o varios productos."""
    proveedores = Proveedor.listar(activos_solo=True)

    # Catálogo de variantes activas con stock actual y presentación
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT v.id_variante, v.id_producto, v.presentacion, v.precio, v.stock, v.sku,
               p.nombre_producto, p.marca, c.nombre_categoria
        FROM variantes_producto v
        JOIN productos p ON v.id_producto = p.id_producto
        LEFT JOIN productos_categorias pc ON p.id_producto = pc.id_producto
        LEFT JOIN categorias c ON pc.id_categoria = c.id_categoria
        WHERE p.activo = TRUE
        ORDER BY p.nombre_producto ASC, v.presentacion ASC
    """)
    variantes_catalogo = cursor.fetchall()
    cursor.close()
    conn.close()

    if request.method == "POST":
        id_usuario = session.get("id_usuario")
        if not id_usuario:
            flash("Sesión no válida para registrar compras", "danger")
            return redirect(url_for("auth.login"))

        # Determinar si es petición JSON o formulario tradicional
        if request.is_json:
            data = request.get_json()
            id_proveedor = data.get("id_proveedor")
            fecha_compra = data.get("fecha_compra")
            raw_items = data.get("items", [])
        else:
            id_proveedor = request.form.get("id_proveedor", type=int)
            fecha_compra = request.form.get("fecha_compra")

            variantes_ids = request.form.getlist("id_variante[]") or request.form.getlist("id_variante")
            cantidades = request.form.getlist("cantidad[]") or request.form.getlist("cantidad")
            precios = request.form.getlist("precio_unitario[]") or request.form.getlist("precio_unitario")

            raw_items = []
            for v_id, cant, prec in zip(variantes_ids, cantidades, precios):
                if v_id and str(v_id).strip():
                    raw_items.append({
                        "id_variante": v_id,
                        "cantidad": cant,
                        "precio_unitario": prec
                    })

            logger.debug("Recibidos %s items en el formulario de nueva compra", len(raw_items))

        # Si no se especificó fecha, usar fecha/hora actual automáticamente
        if not fecha_compra:
            fecha_compra = datetime.now()

        try:
            items_validados = []
            for idx, item in enumerate(raw_items, start=1):
                cant_val = _parsear_entero_no_negativo(item.get("cantidad"))
                if cant_val is None or cant_val <= 0:
                    raise ValueError(f"Fila {idx}: La cantidad debe ser un número entero mayor a cero.")
                precio_val = _parsear_precio(item.get("precio_unitario"))
                if precio_val is None:
                    raise ValueError(f"Fila {idx}: El precio de compra unitario debe ser mayor a cero y contener solo números válidos.")
                items_validados.append({
                    "id_variante": item.get("id_variante"),
                    "cantidad": cant_val,
                    "precio_unitario": precio_val
                })

            id_compra = Compra.crear_con_transaccion(
                id_proveedor=id_proveedor,
                id_usuario=id_usuario,
                fecha_compra=fecha_compra,
                items=items_validados
            )
            flash(f"Compra #{id_compra} registrada exitosamente. El inventario ha sido actualizado.", "success")
            
            if request.is_json:
                return jsonify({"success": True, "redirect_url": url_for("admin.detalle_compra", id_compra=id_compra)})
            
            return redirect(url_for("admin.detalle_compra", id_compra=id_compra))

        except ValueError as ve:
            flash(str(ve), "danger")
            if request.is_json:
                return jsonify({"success": False, "error": str(ve)}), 400
        except Exception as e:
            flash(f"Error inesperado al registrar la compra: {str(e)}", "danger")
            if request.is_json:
                return jsonify({"success": False, "error": str(e)}), 500

    return render_template(
        "admin/compras/formulario.html",
        proveedores=proveedores,
        variantes=variantes_catalogo
    )


@admin_bp.route("/compras/<int:id_compra>")
def detalle_compra(id_compra):
    """Muestra el detalle completo de una compra registrada."""
    compra = Compra.obtener_por_id(id_compra)
    if not compra:
        flash("Compra no encontrada", "danger")
        return redirect(url_for("admin.compras"))

    detalles = CompraDetalle.listar_por_compra(id_compra)
    return render_template("admin/compras/detalle.html", compra=compra, detalles=detalles)


# =========================================================
# CRUD PROVEEDORES (CONECTADO A BD)
# =========================================================
@admin_bp.route("/proveedores", methods=["GET"])
def proveedores():
    """Listado y gestión integral de proveedores con estadísticas de compras."""
    busqueda = request.args.get("busqueda", "").strip() or None
    lista_proveedores = Proveedor.listar(activos_solo=False, busqueda=busqueda)
    
    total_proveedores = len(lista_proveedores)
    total_activos = sum(1 for p in lista_proveedores if p["activo"])
    total_inactivos = total_proveedores - total_activos

    return render_template(
        "admin/proveedores/index.html",
        proveedores=lista_proveedores,
        busqueda=busqueda or "",
        total_proveedores=total_proveedores,
        total_activos=total_activos,
        total_inactivos=total_inactivos
    )


@admin_bp.route("/proveedores/nuevo", methods=["POST"])
def nuevo_proveedor():
    """Registra un nuevo proveedor en la base de datos."""
    nombre = request.form.get("nombre", "").strip()
    identificacion = request.form.get("identificacion", "").strip() or None

    if not nombre:
        flash("El nombre del proveedor es obligatorio.", "danger")
    else:
        try:
            nuevo_id = Proveedor.crear(nombre, identificacion)
            flash(f"Proveedor '{nombre}' (#PROV-{nuevo_id:03d}) registrado con éxito.", "success")
        except Exception as e:
            flash(f"Error al registrar proveedor: {str(e)}", "danger")

    return redirect(url_for("admin.proveedores"))


@admin_bp.route("/proveedores/<int:id_proveedor>/editar", methods=["GET", "POST"])
def editar_proveedor(id_proveedor):
    """Apartado para editar los datos de un proveedor y gestionar su estado."""
    proveedor = Proveedor.obtener_por_id(id_proveedor)
    if not proveedor:
        flash("Proveedor no encontrado en el sistema.", "danger")
        return redirect(url_for("admin.proveedores"))

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        identificacion = request.form.get("identificacion", "").strip() or None
        activo = True if request.form.get("activo") in ["1", "true", "on"] else False

        if not nombre:
            flash("El nombre del proveedor es obligatorio.", "danger")
        else:
            try:
                Proveedor.actualizar(id_proveedor, nombre, identificacion, activo=activo)
                flash(f"Proveedor '{nombre}' actualizado correctamente.", "success")
                return redirect(url_for("admin.proveedores"))
            except Exception as e:
                flash(f"Error al actualizar proveedor: {str(e)}", "danger")

    # Obtener historial de compras asociadas a este proveedor
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT c.id_compra, c.fecha_compra, c.total,
               COUNT(cd.id_detalle_compra) as total_items,
               COALESCE(SUM(cd.cantidad), 0) as total_unidades
        FROM compras c
        LEFT JOIN compra_detalle cd ON c.id_compra = cd.id_compra
        WHERE c.id_proveedor = %s
        GROUP BY c.id_compra, c.fecha_compra, c.total
        ORDER BY c.fecha_compra DESC
        LIMIT 10
    """, (id_proveedor,))
    compras_asociadas = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template(
        "admin/proveedores/editar.html",
        proveedor=proveedor,
        compras_asociadas=compras_asociadas
    )


@admin_bp.route("/proveedores/<int:id_proveedor>/toggle", methods=["POST"])
def toggle_proveedor(id_proveedor):
    """Activa o desactiva un proveedor."""
    try:
        Proveedor.toggle_activo(id_proveedor)
        flash("Estado del proveedor modificado.", "info")
    except Exception as e:
        flash(f"Error al cambiar estado del proveedor: {str(e)}", "danger")

    return redirect(url_for("admin.proveedores"))


@admin_bp.route("/proveedores/<int:id_proveedor>/eliminar", methods=["GET", "POST"])
def eliminar_proveedor(id_proveedor):
    """Apartado para eliminar un proveedor o confirmar su eliminación."""
    proveedor = Proveedor.obtener_por_id(id_proveedor)
    if not proveedor:
        flash("Proveedor no encontrado.", "danger")
        return redirect(url_for("admin.proveedores"))

    if request.method == "POST":
        try:
            Proveedor.eliminar(id_proveedor)
            flash(f"Proveedor '{proveedor['nombre']}' eliminado correctamente del sistema.", "info")
            return redirect(url_for("admin.proveedores"))
        except ValueError as ve:
            flash(str(ve), "danger")
            return redirect(url_for("admin.editar_proveedor", id_proveedor=id_proveedor))
        except Exception as e:
            flash(f"Error al eliminar proveedor: {str(e)}", "danger")
            return redirect(url_for("admin.proveedores"))

    return render_template("admin/proveedores/eliminar.html", proveedor=proveedor)



@admin_bp.route("/api/proveedores/rapido", methods=["POST"])
def api_crear_proveedor_rapido():
    """API para registrar un proveedor rápido desde el formulario de compras vía modal."""
    from app.utils.validaciones import validar_nombre_comercial

    data = request.get_json() if request.is_json else request.form
    nombre = (data.get("nombre") or "").strip()
    identificacion = (data.get("identificacion") or "").strip() or None

    if not nombre:
        return jsonify({"success": False, "error": "El nombre del proveedor es obligatorio"}), 400

    # Validar que el nombre solo contenga letras
    nombre_valido, error_msg = validar_nombre_comercial(nombre)
    if not nombre_valido:
        return jsonify({"success": False, "error": error_msg}), 400

    try:
        nuevo_id = Proveedor.crear(nombre, identificacion)
        return jsonify({
            "success": True,
            "id_proveedor": nuevo_id,
            "nombre": nombre,
            "identificacion": identificacion or ""
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =========================================================
# REPORTES Y EXPORTACIÓN CSV
# =========================================================
TIPOS_EXPORTACION_VALIDOS = ("ventas", "productos", "inventario", "compras")


@admin_bp.route("/reportes")
def reportes():
    """Módulo de reportes administrativos con filtros de fecha y gráficas."""
    desde_str = request.args.get("desde")
    hasta_str = request.args.get("hasta")
    desde, hasta, error = parsear_rango_fechas(desde_str, hasta_str)

    if error:
        flash(error, "warning")

    agrupar = elegir_agrupacion(desde, hasta)
    resumen = Reporte.resumen_ventas(desde, hasta)
    ventas_periodo = Reporte.ventas_por_periodo(desde, hasta, agrupar)
    top_productos = Reporte.productos_mas_vendidos(desde, hasta)
    inv_critico = Reporte.inventario_critico()
    val_inventario = Reporte.valor_inventario()
    flujo_periodo = Reporte.compras_vs_ventas(desde, hasta)

    return render_template(
        "admin/reportes.html",
        desde=desde.isoformat(),
        hasta=hasta.isoformat(),
        agrupar=agrupar,
        resumen=resumen,
        ventas_periodo=ventas_periodo,
        top_productos=top_productos,
        inventario_critico=inv_critico,
        valor_inventario=val_inventario,
        compras_vs_ventas=flujo_periodo
    )


@admin_bp.route("/reportes/exportar/<tipo>")
def exportar_reporte(tipo):
    """Exporta una sección de reportes en formato CSV (UTF-8 con BOM y separador ';')."""
    if tipo not in TIPOS_EXPORTACION_VALIDOS:
        abort(404)

    desde_str = request.args.get("desde")
    hasta_str = request.args.get("hasta")
    desde, hasta, _ = parsear_rango_fechas(desde_str, hasta_str)

    if tipo == "ventas":
        agrupar = elegir_agrupacion(desde, hasta)
        datos = Reporte.ventas_por_periodo(desde, hasta, agrupar)
        encabezados = ["Período", "Pedidos", "Total vendido"]
        filas = [[d["periodo"], d["pedidos"], d["total"]] for d in datos]
    elif tipo == "productos":
        datos = Reporte.productos_mas_vendidos(desde, hasta)
        encabezados = ["Producto", "Unidades vendidas", "Ingresos"]
        filas = [[d["producto"], d["unidades"], d["ingresos"]] for d in datos]
    elif tipo == "inventario":
        datos = Reporte.inventario_critico()
        encabezados = ["Producto", "Presentación", "SKU", "Stock actual", "Stock mínimo", "Faltante"]
        filas = [
            [d["producto"], d["presentacion"], d["sku"] or "", d["stock"], d["stock_minimo"], d["faltante"]]
            for d in datos
        ]
    else:  # compras
        datos = Reporte.compras_vs_ventas(desde, hasta)
        encabezados = ["Desde", "Hasta", "Ventas", "Compras", "Flujo del período", "Número de compras"]
        filas = [[
            desde.isoformat(),
            hasta.isoformat(),
            datos["ventas"],
            datos["compras"],
            datos["diferencia"],
            datos["num_compras"]
        ]]

    contenido_csv = generar_csv(encabezados, filas).encode("utf-8-sig")
    nombre_archivo = f"beerhouse_{tipo}_{desde.isoformat()}_{hasta.isoformat()}.csv"

    return Response(
        contenido_csv,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={nombre_archivo}"
        }
    )


