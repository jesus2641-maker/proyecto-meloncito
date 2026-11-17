"""
API REST interna Beer House — v1
Base URL: /api/v1/

Endpoints públicos (no requieren autenticación):
  GET /api/v1/productos              Lista de productos con variantes y filtros
  GET /api/v1/productos/<id>         Detalle de un producto
  GET /api/v1/categorias             Lista de categorías con conteo de productos
  GET /api/v1/ofertas                Ofertas vigentes

Endpoints protegidos (requieren sesión Flask):
  GET  /api/v1/carrito               Items del carrito del usuario autenticado
  POST /api/v1/carrito/agregar       Agregar producto al carrito (requiere header X-CSRFToken además de sesión)
  GET  /api/v1/cuenta/pedidos        Historial de pedidos del cliente

Endpoints exclusivos admin/trabajador:
  GET  /api/v1/inventario            Stock actual de todas las variantes
  GET  /api/v1/estadisticas          Métricas generales del negocio (solo administrador)
"""

# Utilidades de Flask para blueprint, serialización JSON, lectura de peticiones y sesión
from flask import Blueprint, jsonify, request, session
# Tipos numéricos y temporales usados para serialización segura
from decimal import Decimal
import datetime
# Constantes de roles administrativos y operativos del sistema
from app.utils.decoradores import ID_ROL_ADMIN, ID_ROL_TRABAJADOR

# Blueprint de la API REST versión 1 bajo el prefijo /api/v1
api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _serializar(obj):
    """
    Convierte tipos no serializables nativamente a JSON (`Decimal`, `datetime`, `date`).

    Args:
        obj (Any): Objeto Python que falló al serializarse con `json.dumps`.

    Returns:
        float | str: Representación numérica flotante o cadena ISO-8601.

    Raises:
        TypeError: Si el tipo del objeto no es soportado por el serializador.
    """
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    raise TypeError(f"Tipo no serializable: {type(obj)}")


def _ok(data, status=200):
    """
    Construye una respuesta JSON estandarizada de éxito.

    Args:
        data (Any): Carga útil (payload) a devolver bajo la clave `data`.
        status (int): Código de estado HTTP (por defecto 200 OK).

    Returns:
        tuple[flask.Response, int]: Respuesta JSON y código HTTP.
    """
    return jsonify({"ok": True, "data": data}), status


def _error(mensaje, status=400):
    """
    Construye una respuesta JSON estandarizada de error.

    Args:
        mensaje (str): Descripción legible del error ocurrido.
        status (int): Código de estado HTTP (por defecto 400 Bad Request).

    Returns:
        tuple[flask.Response, int]: Respuesta JSON y código HTTP.
    """
    return jsonify({"ok": False, "error": mensaje}), status


def _requiere_sesion():
    """
    Verifica si existe un usuario autenticado en la sesión actual de Flask.

    Returns:
        bool: True si `id_usuario` está presente en `session`, False en caso contrario.
    """
    return "id_usuario" in session


def _requiere_admin_o_trabajador():
    """
    Verifica si el usuario en sesión posee rol de administrador o trabajador.

    Returns:
        bool: True si `id_rol` coincide con `ID_ROL_ADMIN` o `ID_ROL_TRABAJADOR`.
    """
    return session.get("id_rol") in (ID_ROL_ADMIN, ID_ROL_TRABAJADOR)


# ── Productos ─────────────────────────────────────────────────────────────────

@api_bp.route("/productos")
def listar_productos():
    """
    GET /api/v1/productos
    Devuelve la lista de productos activos agrupando sus variantes.

    Parámetros opcionales (query string):
      ?q=<texto>         búsqueda por nombre o marca
      ?categoria=<id>    filtrar por id de categoría

    Returns:
        tuple[flask.Response, int]: Lista JSON de productos con sus variantes.
    """
    from app.models.producto import Producto

    # Lee y normaliza los filtros opcionales de la URL
    busqueda = request.args.get("q", "").strip() or None
    categoria = request.args.get("categoria", type=int)

    # Consulta filas planas (producto + variante) desde el modelo
    filas = Producto.listar_con_variantes(busqueda=busqueda, categoria=categoria)

    # Agrupar variantes bajo cada producto usando un diccionario indexado por id_producto
    productos = {}
    for fila in filas:
        pid = fila["id_producto"]
        if pid not in productos:
            productos[pid] = {
                "id_producto":      pid,
                "nombre_producto":  fila["nombre_producto"],
                "descripcion":      fila["descripcion"],
                "marca":            fila["marca"],
                "imagen_url":       fila["imagen_url"],
                "categorias":       fila.get("categorias", ""),
                "variantes":        []
            }
        # Convierte el precio Decimal a float para serialización JSON segura
        productos[pid]["variantes"].append({
            "id_variante":   fila["id_variante"],
            "presentacion":  fila["presentacion"],
            "precio":        float(fila["precio"]) if fila["precio"] else 0,
            "stock":         fila["stock"]
        })

    return _ok(list(productos.values()))


@api_bp.route("/productos/<int:id_producto>")
def detalle_producto(id_producto):
    """
    GET /api/v1/productos/<id>
    Obtiene el detalle completo de un producto y sus variantes serializadas.

    Args:
        id_producto (int): ID del producto a consultar.

    Returns:
        tuple[flask.Response, int]: Objeto JSON del producto o error 404 si no existe.
    """
    from app.models.producto import Producto, VarianteProducto

    # Verifica que el producto exista
    producto = Producto.obtener_por_id(id_producto)
    if not producto:
        return _error("Producto no encontrado", 404)

    # Obtiene y serializa todas las variantes asociadas al producto
    variantes = VarianteProducto.listar_por_producto(id_producto)
    variantes_serializadas = []
    for v in variantes:
        variantes_serializadas.append({
            "id_variante":  v["id_variante"],
            "presentacion": v["presentacion"],
            "precio":       float(v["precio"]) if v["precio"] else 0,
            "stock":        v["stock"],
            "sku":          v.get("sku")
        })

    return _ok({
        "id_producto":     producto["id_producto"],
        "nombre_producto": producto["nombre_producto"],
        "descripcion":     producto["descripcion"],
        "marca":           producto["marca"],
        "imagen_url":      producto["imagen_url"],
        "variantes":       variantes_serializadas
    })


# ── Categorías ────────────────────────────────────────────────────────────────

@api_bp.route("/categorias")
def listar_categorias():
    """
    GET /api/v1/categorias
    Devuelve todas las categorías junto con el conteo de productos asociados.

    Returns:
        tuple[flask.Response, int]: Lista JSON de categorías.
    """
    from app.models.categoria import Categoria

    categorias = Categoria.listar_con_conteo()
    return _ok(categorias)


# ── Ofertas ───────────────────────────────────────────────────────────────────

@api_bp.route("/ofertas")
def listar_ofertas():
    """
    GET /api/v1/ofertas — devuelve solo las ofertas activas y vigentes.

    Convierte importes `Decimal` a `float` y fechas a formato ISO-8601.

    Returns:
        tuple[flask.Response, int]: Lista JSON de ofertas activas.
    """
    from app.models.oferta import Oferta

    ofertas = Oferta.listar_activas()
    resultado = []
    for o in ofertas:
        # Normaliza campos numéricos y de fecha para evitar errores de serialización JSON
        resultado.append({
            "id_oferta":        o["id_oferta"],
            "titulo":           o.get("titulo") or o.get("nombre_oferta", ""),
            "descripcion":      o.get("descripcion"),
            "descuento":        float(o["descuento"]) if o.get("descuento") else None,
            "precio_oferta":    float(o["precio_oferta"]) if o.get("precio_oferta") else None,
            "precio_original":  float(o["precio_original"]) if o.get("precio_original") else None,
            "nombre_producto":  o.get("nombre_producto"),
            "presentacion":     o.get("presentacion"),
            "imagen_url":       o.get("imagen_url"),
            "fecha_inicio":     o["fecha_inicio"].isoformat() if o.get("fecha_inicio") else None,
            "fecha_fin":        o["fecha_fin"].isoformat() if o.get("fecha_fin") else None,
        })

    return _ok(resultado)


# ── Carrito (requiere sesión) ─────────────────────────────────────────────────

@api_bp.route("/carrito")
def ver_carrito():
    """
    GET /api/v1/carrito — devuelve los items del carrito del usuario autenticado
    junto con los subtotales por línea y el total general.

    Returns:
        tuple[flask.Response, int]: Contenido del carrito o 401 si no hay sesión.
    """
    # Control de autenticación basado en sesión Flask
    if not _requiere_sesion():
        return _error("No autenticado", 401)

    from app.models.carrito import Carrito

    # Obtiene el carrito activo del usuario (o crea uno nuevo si no existe)
    carrito = Carrito.obtener_o_crear(session["id_usuario"])
    items = Carrito.obtener_items(carrito["id_carrito"])

    # Serializa cada ítem calculando su subtotal y acumulando el total del carrito
    items_serializados = []
    total = 0
    for item in items:
        subtotal = float(item["precio"]) * item["cantidad"]
        total += subtotal
        items_serializados.append({
            "id_item":         item["id_item"],
            "id_variante":     item["id_variante"],
            "nombre_producto": item["nombre_producto"],
            "presentacion":    item["presentacion"],
            "cantidad":        item["cantidad"],
            "precio_unitario": float(item["precio"]),
            "subtotal":        subtotal
        })

    return _ok({
        "id_carrito": carrito["id_carrito"],
        "items":      items_serializados,
        "total":      total
    })


@api_bp.route("/carrito/agregar", methods=["POST"])
def agregar_al_carrito():
    """
    POST /api/v1/carrito/agregar
    Agrega una cantidad específica de una variante de producto al carrito del usuario.

    Body JSON esperado:
      { "id_variante": 3, "cantidad": 2 }

    Returns:
        tuple[flask.Response, int]: Confirmación 201 Created o error 400/401/404.
    """
    # Requiere usuario autenticado en sesión
    if not _requiere_sesion():
        return _error("No autenticado", 401)

    # Parsea el cuerpo JSON de la petición
    data = request.get_json()
    if not data:
        return _error("Se requiere body JSON")

    id_variante = data.get("id_variante")
    cantidad = data.get("cantidad", 1)

    # Validaciones de entrada: id_variante obligatorio y cantidad entero >= 1 (excluyendo bool)
    if not id_variante:
        return _error("Se requiere id_variante")
    if isinstance(cantidad, bool) or not isinstance(cantidad, int) or cantidad < 1:
        return _error("La cantidad debe ser un entero mayor a 0")

    from app.models.producto import VarianteProducto, Producto
    from app.models.carrito import Carrito, CarritoItem

    # Verifica que la variante y su producto padre existan y estén activos
    variante = VarianteProducto.obtener_por_id(id_variante)
    if not variante:
        return _error("La variante del producto no existe", 404)

    producto = Producto.obtener_por_id(variante["id_producto"])
    if not producto or not producto.get("activo"):
        return _error("Este producto no está disponible", 400)

    # Valida que exista stock disponible antes de consultar el carrito
    stock_actual = int(variante.get("stock") or 0)
    if stock_actual <= 0:
        return _error(f"El producto '{producto['nombre_producto']}' ({variante['presentacion']}) no está disponible por falta de stock", 400)

    # Comprueba que la suma (ya en carrito + nueva cantidad) no supere el stock físico
    carrito = Carrito.obtener_o_crear(session["id_usuario"])
    cantidad_en_carrito = CarritoItem.obtener_cantidad(carrito["id_carrito"], id_variante)
    if cantidad_en_carrito + cantidad > stock_actual:
        disponibles = max(stock_actual - cantidad_en_carrito, 0)
        return _error(f"Stock insuficiente. Solo quedan {disponibles} unidad(es) disponible(s)", 400)

    # Inserta o incrementa la cantidad en el carrito
    CarritoItem.agregar(carrito["id_carrito"], id_variante, cantidad)

    return _ok({"mensaje": "Producto agregado al carrito"}, 201)


# ── Pedidos del cliente (requiere sesión) ──────────────────────────────────────

@api_bp.route("/cuenta/pedidos")
def historial_pedidos():
    """
    GET /api/v1/cuenta/pedidos — historial de pedidos del cliente autenticado.

    Returns:
        tuple[flask.Response, int]: Lista JSON de pedidos del usuario o 401.
    """
    if not _requiere_sesion():
        return _error("No autenticado", 401)

    from app.models.pedido import Pedido

    pedidos = Pedido.listar_por_usuario(session["id_usuario"])
    resultado = []
    for p in pedidos:
        resultado.append({
            "id_pedido":    p["id_pedido"],
            "total":        float(p["total"]) if p.get("total") else 0,
            "fecha_pedido": p["fecha_pedido"].isoformat() if p.get("fecha_pedido") else None,
            "estado":       p["nombre_estado"]
        })

    return _ok(resultado)


# ── Inventario (admin/trabajador) ─────────────────────────────────────────────

@api_bp.route("/inventario")
def inventario():
    """
    GET /api/v1/inventario — stock actual de todas las variantes activas.

    Acceso restringido a administradores y trabajadores. Marca con
    `alerta_stock = True` aquellas variantes con 5 o menos unidades.

    Returns:
        tuple[flask.Response, int]: Listado JSON de inventario o 403 si no tiene permisos.
    """
    if not _requiere_admin_o_trabajador():
        return _error("Acceso denegado", 403)

    from app.utils.db import get_connection

    # Consulta directa a la base de datos para obtener productos activos y sus variantes
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT p.id_producto, p.nombre_producto, p.marca,
               v.id_variante, v.presentacion, v.precio, v.stock, v.sku
        FROM productos p
        JOIN variantes_producto v ON v.id_producto = p.id_producto
        WHERE p.activo = TRUE
        ORDER BY p.nombre_producto, v.presentacion
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    # Transforma cada fila agregando la bandera de alerta de stock crítico
    resultado = []
    for r in rows:
        resultado.append({
            "id_producto":     r["id_producto"],
            "nombre_producto": r["nombre_producto"],
            "marca":           r["marca"],
            "id_variante":     r["id_variante"],
            "presentacion":    r["presentacion"],
            "precio":          float(r["precio"]) if r["precio"] else 0,
            "stock":           r["stock"],
            "sku":             r.get("sku"),
            "alerta_stock":    r["stock"] <= 5  # True si stock crítico
        })

    return _ok(resultado)


# ── Estadísticas (solo admin) ─────────────────────────────────────────────────

@api_bp.route("/estadisticas")
def estadisticas():
    """
    GET /api/v1/estadisticas — métricas generales del negocio (solo para administrador).

    Ejecuta consultas agregadas sobre pedidos, estados, top 5 productos más
    vendidos, usuarios activos y variantes con stock crítico.

    Returns:
        tuple[flask.Response, int]: Diccionario JSON con KPIs del negocio o 403.
    """
    # Verifica estrictamente que el rol sea Administrador
    if session.get("id_rol") != ID_ROL_ADMIN:
        return _error("Acceso denegado — solo administrador", 403)

    from app.utils.db import get_connection

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Total pedidos y ventas acumuladas
    cursor.execute("""
        SELECT COUNT(*) AS total_pedidos,
               COALESCE(SUM(total), 0) AS ventas_totales
        FROM pedidos
    """)
    ventas = cursor.fetchone()

    # Conteo de pedidos agrupados por estado
    cursor.execute("""
        SELECT es.nombre_estado, COUNT(*) AS cantidad
        FROM pedidos pe
        JOIN estados_pedido es ON pe.id_estado = es.id_estado
        GROUP BY es.nombre_estado
    """)
    estados = cursor.fetchall()

    # Top 5 productos/variantes más vendidos por unidades e ingresos
    cursor.execute("""
        SELECT p.nombre_producto, v.presentacion,
               SUM(pd.cantidad) AS unidades_vendidas,
               SUM(pd.cantidad * pd.precio_unitario) AS ingresos
        FROM pedido_detalle pd
        JOIN variantes_producto v ON pd.id_variante = v.id_variante
        JOIN productos p ON v.id_producto = p.id_producto
        GROUP BY p.id_producto, v.id_variante
        ORDER BY unidades_vendidas DESC
        LIMIT 5
    """)
    top_productos = cursor.fetchall()

    # Total de usuarios activos en el sistema
    cursor.execute("SELECT COUNT(*) AS total FROM usuarios WHERE activo = TRUE")
    usuarios = cursor.fetchone()

    # Cantidad de variantes activas con stock crítico (<= 5 unidades)
    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM variantes_producto v
        JOIN productos p ON v.id_producto = p.id_producto
        WHERE v.stock <= 5 AND p.activo = TRUE
    """)
    stock_critico = cursor.fetchone()

    # Libera cursor y conexión a la base de datos
    cursor.close()
    conn.close()

    return _ok({
        "pedidos": {
            "total":          ventas["total_pedidos"],
            "ventas_totales": float(ventas["ventas_totales"]),
            "por_estado":     estados
        },
        "top_productos": [
            {
                "nombre_producto":  p["nombre_producto"],
                "presentacion":     p["presentacion"],
                "unidades_vendidas": p["unidades_vendidas"],
                "ingresos":         float(p["ingresos"]) if p["ingresos"] else 0
            }
            for p in top_productos
        ],
        "usuarios_activos":    usuarios["total"],
        "variantes_stock_critico": stock_critico["total"]
    })


# ── 404 y 405 de la API ───────────────────────────────────────────────────────

@api_bp.app_errorhandler(404)
def not_found_api(e):
    """
    Manejador global de errores 404 para devolver JSON en rutas `/api/*`.

    Si la ruta no pertenece a la API, devuelve la excepción original para que
    Flask la maneje con la plantilla HTML estándar.
    """
    if request.path.startswith("/api/"):
        return _error("Endpoint no encontrado", 404)
    return e


@api_bp.app_errorhandler(405)
def method_not_allowed_api(e):
    """
    Manejador global de errores 405 (método no permitido) para rutas `/api/*`.
    """
    if request.path.startswith("/api/"):
        return _error("Método HTTP no permitido", 405)
    return e
