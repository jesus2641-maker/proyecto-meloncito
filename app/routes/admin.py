"""
Módulo de rutas del panel de Administración (`/admin`).

Centraliza todas las operaciones administrativas del sistema Beer House:
- Dashboard con métricas ejecutivas y últimos pedidos.
- CRUD completo de productos, variantes de presentación e inventario.
- CRUD de categorías con carga/eliminación de imágenes en Cloudinary.
- Gestión de pedidos, cambios de estado y cancelación con reembolso en PayPal.
- Administración de usuarios (cambio de rol y activación/desactivación).
- Edición del perfil propio del administrador.
- CRUD de ofertas promocionales y endpoint auxiliar de variantes.
- Registro de compras a proveedores (con incremento atómico de stock) y CRUD de proveedores.
- Módulo de reportes gerenciales y exportación en formato CSV.
"""

# Módulos estándar para logging, expresiones regulares, fechas y precisión decimal
import logging
import re
from flask import Blueprint, render_template, session, redirect, url_for, flash, request, abort, jsonify, Response
from datetime import datetime
from decimal import Decimal
# Modelos de dominio del sistema
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
# Utilidades de reportes, almacenamiento en la nube, correo y conexión a BD
from app.utils.reportes_utils import parsear_rango_fechas, elegir_agrupacion, generar_csv
from app.utils.cloudinary_utils import upload_image, delete_image
from app.utils.email_service import send_order_status_update_email
from app.utils.db import get_connection

# Logger del módulo de administración
logger = logging.getLogger(__name__)

# Blueprint administrativo bajo el prefijo /admin
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# Constante del rol administrador en la tabla roles
ID_ROL_ADMIN = 2  # rol 'admin'

# Expresiones regulares para validar precios decimales (hasta 2 decimales) y enteros no negativos
REGEX_PRECIO = re.compile(r"^\d+(\.\d{1,2})?$")
REGEX_ENTERO = re.compile(r"^\d+$")


def _parsear_precio(valor_raw):
    """
    Valida con regex `^\\d+(\\.\\d{1,2})?$` y retorna un `float > 0` o `None` si es inválido.

    Args:
        valor_raw (Any): Valor crudo recibido desde formulario o JSON.

    Returns:
        float | None: Precio numérico positivo o `None` si falla la validación.
    """
    texto = (valor_raw if isinstance(valor_raw, str) else str(valor_raw or "")).strip()
    if not texto or not REGEX_PRECIO.match(texto):
        return None
    valor = float(texto)
    if valor <= 0:
        return None
    return valor


def _parsear_entero_no_negativo(valor_raw):
    """
    Valida con regex `^\\d+$` y retorna un `int >= 0` o `None` si es inválido.

    Args:
        valor_raw (Any): Valor crudo recibido desde formulario o JSON.

    Returns:
        int | None: Entero no negativo o `None` si contiene caracteres no numéricos.
    """
    texto = (valor_raw if isinstance(valor_raw, str) else str(valor_raw or "")).strip()
    if not texto or not REGEX_ENTERO.match(texto):
        return None
    return int(texto)


@admin_bp.before_request
def verificar_permisos_admin():
    """
    Hook ejecutado antes de cada petición al blueprint `admin`.

    Garantiza que únicamente los usuarios con rol `ID_ROL_ADMIN` puedan acceder
    a cualquier ruta administrativa; de lo contrario registra advertencia y
    redirige al catálogo público.

    Returns:
        flask.Response | None: Redirección si no es admin, o None si está autorizado.
    """
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
    """
    Panel principal del administrador con métricas globales y los últimos 6 pedidos.

    Returns:
        str: Plantilla HTML `admin/dashboard.html` renderizada.
    """
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
    """
    Lista todos los productos (activos e inactivos) para administración.

    Returns:
        str: Plantilla HTML `admin/productos/index.html` renderizada.
    """
    lista_productos = Producto.listar_admin()
    return render_template("admin/productos/index.html", productos=lista_productos)


@admin_bp.route("/productos/nuevo", methods=["GET", "POST"])
def nuevo_producto():
    """
    Crea un nuevo producto junto con su variante inicial obligatoria.

    Valida categorías (1 a 2), nombre, presentación, precio y stock antes de
    insertar en BD, sube imagen opcional a Cloudinary y aplica rollback manual
    eliminando el producto si falla la creación de su variante inicial.

    Returns:
        flask.Response | str: Redirección al listado o formulario HTML.
    """
    categorias = Categoria.listar()

    if request.method == "POST":
        # Lectura de datos principales del producto
        categorias_seleccionadas = request.form.getlist("categorias")
        nombre_producto = request.form.get("nombre_producto", "").strip()
        descripcion = request.form.get("descripcion", "").strip() or None
        marca = request.form.get("marca", "").strip() or None
        imagen_url = request.form.get("imagen_url", "").strip() or None

        # Validación de categorías (mínimo 1, máximo 2)
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

        # Manejar subida de imagen a Cloudinary si se adjuntó un archivo
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

        # Convertir IDs de categorías a enteros solo después de validar la cantidad
        try:
            lista_categorias = [int(cat) for cat in categorias_seleccionadas]
        except (ValueError, TypeError):
            flash("Categoría inválida", "danger")
            return render_template("admin/productos/formulario.html", producto=None, categorias=categorias)

        # Inserta el producto base y sus categorías asociadas
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
            return render_template("admin/productos/formulario.html", producto=None, categorias=categorias)

        flash(f"Producto '{nombre_producto}' creado exitosamente", "success")
        return redirect(url_for("admin.productos"))

    return render_template("admin/productos/formulario.html", producto=None, categorias=categorias)


@admin_bp.route("/productos/<int:id_producto>/editar", methods=["GET", "POST"])
def editar_producto(id_producto):
    """
    Edita los datos generales, categorías, estado e imagen de un producto existente.

    Si se carga una nueva imagen, elimina previamente la anterior de Cloudinary
    cuando existe un `imagen_public_id`.

    Args:
        id_producto (int): Identificador del producto a editar.

    Returns:
        flask.Response | str: Redirección o formulario HTML con datos actuales.
    """
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

        # Manejar subida de nueva imagen a Cloudinary reemplazando la anterior si existía
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
    """
    Alterna el estado activo/inactivo de un producto en el catálogo.

    Args:
        id_producto (int): Identificador del producto.

    Returns:
        flask.Response: Redirección a `admin.productos`.
    """
    Producto.toggle_activo(id_producto)
    flash("Estado del producto modificado", "info")
    return redirect(url_for("admin.productos"))


@admin_bp.route("/productos/<int:id_producto>/eliminar", methods=["POST"])
def eliminar_producto(id_producto):
    """
    Elimina un producto si no tiene dependencias bloqueantes en pedidos/compras.

    Args:
        id_producto (int): Identificador del producto a eliminar.

    Returns:
        flask.Response: Redirección a `admin.productos`.
    """
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
    """
    Lista y permite gestionar las variantes (presentaciones, precios y stock)
    asociadas a un producto específico.

    Args:
        id_producto (int): Identificador del producto padre.

    Returns:
        str: Plantilla HTML `admin/productos/variantes.html` renderizada.
    """
    producto = Producto.obtener_por_id(id_producto)
    if not producto:
        abort(404)

    variantes = VarianteProducto.listar_por_producto(id_producto)
    return render_template("admin/productos/variantes.html", producto=producto, variantes=variantes)


@admin_bp.route("/productos/<int:id_producto>/variantes/nueva", methods=["POST"])
def nueva_variante(id_producto):
    """
    Agrega una nueva variante de presentación a un producto existente.

    Valida precio positivo, presentación obligatoria, stock y stock mínimo no negativos.

    Args:
        id_producto (int): Identificador del producto padre.

    Returns:
        flask.Response: Redirección a `admin.variantes_producto`.
    """
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
    """
    Actualiza los datos de una variante existente (presentación, precio, stock,
    stock mínimo y SKU).

    Args:
        id_variante (int): Identificador de la variante a modificar.

    Returns:
        flask.Response: Redirección a `admin.variantes_producto`.
    """
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
    """
    Elimina una variante si no está referenciada en pedidos previos.

    Args:
        id_variante (int): Identificador de la variante.

    Returns:
        flask.Response: Redirección a `admin.variantes_producto`.
    """
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
    """
    Muestra el inventario completo con alertas de stock bajo/agotado y filtros
    por búsqueda, categoría, estado de stock y criterio de ordenación.

    Returns:
        str: Plantilla HTML `admin/inventario.html` renderizada.
    """
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
    """
    Lista todas las categorías con el conteo de productos asociados a cada una.

    Returns:
        str: Plantilla HTML `admin/categorias/index.html` renderizada.
    """
    lista = Categoria.listar_con_conteo()
    return render_template("admin/categorias/index.html", categorias=lista)


@admin_bp.route("/categorias/nueva", methods=["POST"])
def nueva_categoria():
    """
    Crea una nueva categoría de productos con imagen opcional en Cloudinary.

    Returns:
        flask.Response: Redirección a `admin.categorias`.
    """
    nombre = request.form.get("nombre_categoria", "").strip()
    descripcion = request.form.get("descripcion", "").strip() or None
    imagen_url = request.form.get("imagen_url", "").strip() or None

    if not nombre:
        flash("El nombre de la categoría es obligatorio", "danger")
    else:
        try:
            # Manejar subida de imagen a Cloudinary si se adjuntó archivo
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
    """
    Actualiza el nombre, descripción e imagen (opcional en Cloudinary) de una categoría.

    Args:
        id_categoria (int): Identificador de la categoría a editar.

    Returns:
        flask.Response: Redirección a `admin.categorias`.
    """
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
            # Manejar subida de nueva imagen a Cloudinary reemplazando la anterior si existía
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
    """
    Elimina una categoría si no tiene productos vinculados.

    Args:
        id_categoria (int): Identificador de la categoría.

    Returns:
        flask.Response: Redirección a `admin.categorias`.
    """
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
    """
    Lista todos los pedidos del sistema con filtro opcional por estado.

    Returns:
        str: Plantilla HTML `admin/pedidos/index.html` renderizada.
    """
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
    """
    Muestra el detalle completo de un pedido, sus productos y su estado de pago.

    Args:
        id_pedido (int): Identificador del pedido.

    Returns:
        str: Plantilla HTML `admin/pedidos/detalle.html` renderizada.
    """
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
    """
    Cambia el estado de un pedido desde el panel administrativo.

    Si el nuevo estado es `ESTADO_CANCELADO`:
    - Cuando existe un pago PayPal completado, ejecuta `cancelar_pedido_con_reembolso`
      (reembolso en PayPal + cancelación + liberación de stock).
    - Cuando el pago PayPal está pendiente, cancela el pedido y marca el pago como cancelado.
    Para otros estados, actualiza el estado y envía correo de notificación al cliente.

    Args:
        id_pedido (int): Identificador del pedido.

    Returns:
        flask.Response: Redirección segura a `next` o al listado de pedidos.
    """
    from app.utils.validaciones import ruta_segura
    id_estado = request.form.get("id_estado", type=int)
    default_url = url_for("admin.pedidos")
    # Valida que la URL de retorno sea interna (previene Open Redirect)
    next_url = ruta_segura(request.form.get("next"), fallback=default_url)

    if id_estado:
        try:
            # Obtener información del pedido antes de actualizar
            pedido = Pedido.obtener_por_id(id_pedido)
            if not pedido:
                flash("Pedido no encontrado", "danger")
                return redirect(next_url)

            # Si el admin va a cancelar el pedido, gestionar reembolso o cancelación de pago si aplica
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

            # Notifica al cliente por correo sin interrumpir la operación si falla el SMTP
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
    """
    Lista todos los usuarios registrados y los roles disponibles en el sistema.

    Returns:
        str: Plantilla HTML `admin/usuarios/index.html` renderizada.
    """
    lista = Usuario.listar_todos()
    roles = Usuario.obtener_roles()
    return render_template("admin/usuarios/index.html", usuarios=lista, roles=roles)


@admin_bp.route("/usuarios/<int:id_usuario>/rol", methods=["POST"])
def cambiar_rol_usuario(id_usuario):
    """
    Asigna un nuevo rol a un usuario específico.

    Args:
        id_usuario (int): Identificador del usuario a modificar.

    Returns:
        flask.Response: Redirección a `admin.usuarios`.
    """
    id_rol = request.form.get("id_rol", type=int)
    if id_rol:
        Usuario.actualizar_rol(id_usuario, id_rol)
        flash("Rol del usuario actualizado", "success")

    return redirect(url_for("admin.usuarios"))


@admin_bp.route("/usuarios/<int:id_usuario>/toggle", methods=["POST"])
def toggle_usuario(id_usuario):
    """
    Activa o desactiva la cuenta de un usuario, impidiendo que el administrador
    se desactive a sí mismo.

    Args:
        id_usuario (int): Identificador del usuario.

    Returns:
        flask.Response: Redirección a `admin.usuarios`.
    """
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
    """
    Página de perfil personal del administrador autenticado.

    Returns:
        flask.Response | str: Redirección o plantilla `admin/mi_cuenta.html`.
    """
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
    """
    Edita el perfil del administrador actual (datos básicos, teléfono colombiano
    opcional, correo único y cambio de contraseña previa verificación de la actual).

    Returns:
        flask.Response: Redirección a `admin.mi_cuenta`.
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
    
    nombre = request.form.get("nombre", "").strip()
    apellido = request.form.get("apellido", "").strip()
    telefono_raw = request.form.get("telefono", "").strip()
    email = request.form.get("email", "").strip()
    contraseña_actual = request.form.get("contraseña_actual", "").strip()
    contraseña_nueva = request.form.get("contraseña_nueva", "").strip()
    
    if not nombre or not apellido or not email:
        flash("Nombre, apellido y correo son obligatorios", "danger")
        return redirect(url_for("admin.mi_cuenta"))

    if len(nombre) < 2 or len(nombre) > 50 or not NOMBRE_REGEX.match(nombre):
        flash("El nombre debe tener entre 2 y 50 caracteres y solo puede contener letras y espacios", "danger")
        return redirect(url_for("admin.mi_cuenta"))

    if len(apellido) < 2 or len(apellido) > 50 or not NOMBRE_REGEX.match(apellido):
        flash("El apellido debe tener entre 2 y 50 caracteres y solo puede contener letras y espacios", "danger")
        return redirect(url_for("admin.mi_cuenta"))

    if not validar_email(email):
        flash("Ingresa un correo electrónico válido", "danger")
        return redirect(url_for("admin.mi_cuenta"))

    # Validación de celular colombiano
    if telefono_raw:
        valido_tel, msg_tel, tel_normalizado = validar_telefono_colombiano(telefono_raw)
        if not valido_tel:
            flash(msg_tel, "danger")
            return redirect(url_for("admin.mi_cuenta"))
        telefono = tel_normalizado
    else:
        telefono = None
    
    # Si se quiere cambiar la contraseña, valida la nueva y verifica la actual
    if contraseña_nueva:
        valido_pass, msg_pass = validar_password(contraseña_nueva)
        if not valido_pass:
            flash(msg_pass, "danger")
            return redirect(url_for("admin.mi_cuenta"))

        if not contraseña_actual:
            flash("Debes ingresar tu contraseña actual para cambiarla", "danger")
            return redirect(url_for("admin.mi_cuenta"))
        
        # Verificar contraseña actual
        usuario = Usuario.obtener_por_id(id_usuario)
        if not Usuario.verificar_contraseña(contraseña_actual, usuario['password_hash']):
            flash("La contraseña actual es incorrecta", "danger")
            return redirect(url_for("admin.mi_cuenta"))

    try:
        existente = Usuario.obtener_por_email(email)
        if existente and int(existente["id_usuario"]) != int(id_usuario):
            flash("Ese correo electrónico ya está registrado por otro usuario", "danger")
            return redirect(url_for("admin.mi_cuenta"))

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
            logger.exception("Error al actualizar perfil de admin: %s", err)
            flash("No se pudo actualizar el perfil. Intenta de nuevo.", "danger")
    
    return redirect(url_for("admin.mi_cuenta"))


# =========================================================
# OFERTAS
# =========================================================
@admin_bp.route("/ofertas")
def ofertas():
    """
    Lista todas las ofertas registradas (activas, programadas o vencidas).

    Returns:
        str: Plantilla HTML `admin/ofertas/index.html` renderizada.
    """
    lista_ofertas = Oferta.listar_todas()
    return render_template("admin/ofertas/index.html", ofertas=lista_ofertas)


@admin_bp.route("/ofertas/nueva", methods=["GET", "POST"])
def nueva_oferta():
    """
    Crea una nueva oferta promocional asociada a un producto (y variante opcional).

    Valida producto, título, precio de oferta positivo y porcentaje de descuento
    en el rango `(0, 100]`.

    Returns:
        flask.Response | str: Redirección o formulario HTML de oferta.
    """
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
    """
    Edita los parámetros y vigencia de una oferta existente.

    Args:
        id_oferta (int): Identificador de la oferta.

    Returns:
        flask.Response | str: Redirección o formulario HTML de oferta.
    """
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
    """
    Activa o desactiva una oferta promocional.

    Args:
        id_oferta (int): Identificador de la oferta.

    Returns:
        flask.Response: Redirección a `admin.ofertas`.
    """
    Oferta.toggle_activa(id_oferta)
    flash("Estado de la oferta modificado", "info")
    return redirect(url_for("admin.ofertas"))


@admin_bp.route("/ofertas/<int:id_oferta>/eliminar", methods=["POST"])
def eliminar_oferta(id_oferta):
    """
    Elimina una oferta promocional de la base de datos.

    Args:
        id_oferta (int): Identificador de la oferta.

    Returns:
        flask.Response: Redirección a `admin.ofertas`.
    """
    try:
        Oferta.eliminar(id_oferta)
        flash("Oferta eliminada", "info")
    except Exception as e:
        flash(f"Error al eliminar oferta: {str(e)}", "danger")
    
    return redirect(url_for("admin.ofertas"))


# API interna para cargar dinámicamente variantes de un producto en el formulario de ofertas
@admin_bp.route("/api/productos/<int:id_producto>/variantes")
def api_variantes_producto(id_producto):
    """
    API JSON para obtener las variantes de un producto (usado por el selector
    dinámico del formulario de ofertas).

    Args:
        id_producto (int): Identificador del producto.

    Returns:
        flask.Response: Lista JSON de variantes con id, presentación y precio.
    """
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
    """
    Historial de compras a proveedores con métricas generales de inversión.

    Returns:
        str: Plantilla HTML `admin/compras/index.html` renderizada.
    """
    lista_compras = Compra.listar_todas()
    metricas = Compra.obtener_metricas()
    return render_template("admin/compras/index.html", compras=lista_compras, metricas=metricas)


@admin_bp.route("/compras/nueva", methods=["GET", "POST"])
def nueva_compra():
    """
    Registra una nueva compra a un proveedor con uno o varios productos/variantes.

    - GET: carga proveedores activos y el catálogo de variantes activas para
      el selector dinámico del formulario.
    - POST: acepta tanto JSON como formulario HTML tradicional (`id_variante[]`,
      `cantidad[]`, `precio_unitario[]`), valida cantidades enteras > 0 y precios > 0,
      y ejecuta `Compra.crear_con_transaccion` incrementando el stock automáticamente.

    Returns:
        flask.Response | tuple[flask.Response, int] | str: Respuesta JSON, redirección
            al detalle de la compra o plantilla HTML del formulario.
    """
    proveedores = Proveedor.listar(activos_solo=True)

    # Catálogo de variantes activas con stock actual, presentación y categoría
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

        # Determinar si es petición JSON (AJAX) o formulario tradicional HTML
        if request.is_json:
            data = request.get_json()
            id_proveedor = data.get("id_proveedor")
            fecha_compra = data.get("fecha_compra")
            raw_items = data.get("items", [])
        else:
            id_proveedor = request.form.get("id_proveedor", type=int)
            fecha_compra = request.form.get("fecha_compra")

            # Soporta nombres de campos con o sin corchetes `[]`
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

        # Valida cada línea de compra y ejecuta la transacción en base de datos
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

            # Registra cabecera, detalles y suma las cantidades al stock de cada variante
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
    """
    Muestra el detalle completo (cabecera y líneas) de una compra registrada.

    Args:
        id_compra (int): Identificador de la compra.

    Returns:
        flask.Response | str: Redirección si no existe, o plantilla de detalle.
    """
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
    """
    Listado y gestión integral de proveedores con búsqueda y conteos de estado.

    Returns:
        str: Plantilla HTML `admin/proveedores/index.html` renderizada.
    """
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
    """
    Registra un nuevo proveedor en la base de datos.

    Returns:
        flask.Response: Redirección a `admin.proveedores`.
    """
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
    """
    Edita los datos de un proveedor, gestiona su estado activo/inactivo y
    muestra las últimas 10 compras asociadas a él.

    Args:
        id_proveedor (int): Identificador del proveedor.

    Returns:
        flask.Response | str: Redirección o plantilla `admin/proveedores/editar.html`.
    """
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

    # Obtener historial de las últimas 10 compras asociadas a este proveedor
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
    """
    Activa o desactiva un proveedor en el sistema.

    Args:
        id_proveedor (int): Identificador del proveedor.

    Returns:
        flask.Response: Redirección a `admin.proveedores`.
    """
    try:
        Proveedor.toggle_activo(id_proveedor)
        flash("Estado del proveedor modificado.", "info")
    except Exception as e:
        flash(f"Error al cambiar estado del proveedor: {str(e)}", "danger")

    return redirect(url_for("admin.proveedores"))


@admin_bp.route("/proveedores/<int:id_proveedor>/eliminar", methods=["GET", "POST"])
def eliminar_proveedor(id_proveedor):
    """
    Muestra la confirmación (GET) o ejecuta la eliminación (POST) de un proveedor
    siempre que no tenga compras históricas asociadas.

    Args:
        id_proveedor (int): Identificador del proveedor.

    Returns:
        flask.Response | str: Redirección o plantilla de confirmación.
    """
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
    """
    API JSON para registrar un proveedor rápido desde el formulario de compras vía modal.

    Valida obligatoriedad y caracteres permitidos mediante `validar_nombre_comercial`.

    Returns:
        tuple[flask.Response, int] | flask.Response: JSON con los datos del nuevo proveedor o error.
    """
    from app.utils.validaciones import validar_nombre_comercial

    data = request.get_json() if request.is_json else request.form
    nombre = (data.get("nombre") or "").strip()
    identificacion = (data.get("identificacion") or "").strip() or None

    if not nombre:
        return jsonify({"success": False, "error": "El nombre del proveedor es obligatorio"}), 400

    # Validar que el nombre comercial cumpla las reglas permitidas
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
# Tipos de reporte permitidos para descarga en CSV
TIPOS_EXPORTACION_VALIDOS = ("ventas", "productos", "inventario", "compras")


@admin_bp.route("/reportes")
def reportes():
    """
    Módulo de reportes administrativos con filtros de rango de fechas y gráficas:
    resumen de ventas, serie temporal, top productos, inventario crítico,
    valoración de inventario y comparativa compras vs ventas.

    Returns:
        str: Plantilla HTML `admin/reportes.html` renderizada.
    """
    desde_str = request.args.get("desde")
    hasta_str = request.args.get("hasta")
    desde, hasta, error = parsear_rango_fechas(desde_str, hasta_str)

    if error:
        flash(error, "warning")

    # Elige automáticamente agrupación por día, semana o mes según la amplitud del rango
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
    """
    Exporta una sección de reportes en formato CSV (UTF-8 con BOM y separador `;`
    para compatibilidad directa con Excel en español).

    Args:
        tipo (str): Tipo de reporte (`ventas`, `productos`, `inventario` o `compras`).

    Returns:
        flask.Response: Respuesta HTTP con cabecera `Content-Disposition: attachment`.
    """
    if tipo not in TIPOS_EXPORTACION_VALIDOS:
        abort(404)

    desde_str = request.args.get("desde")
    hasta_str = request.args.get("hasta")
    desde, hasta, _ = parsear_rango_fechas(desde_str, hasta_str)

    # Construye encabezados y filas según la sección solicitada
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

    # Codifica con UTF-8 BOM para que Excel reconozca tildes y eñes correctamente
    contenido_csv = generar_csv(encabezados, filas).encode("utf-8-sig")
    nombre_archivo = f"beerhouse_{tipo}_{desde.isoformat()}_{hasta.isoformat()}.csv"

    return Response(
        contenido_csv,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={nombre_archivo}"
        }
    )


