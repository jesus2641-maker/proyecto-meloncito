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
  POST /api/v1/carrito/agregar       Agregar producto al carrito
  GET  /api/v1/cuenta/pedidos        Historial de pedidos del cliente

Endpoints exclusivos admin/trabajador:
  GET  /api/v1/inventario            Stock actual de todas las variantes
  GET  /api/v1/estadisticas          Métricas generales del negocio
"""

from flask import Blueprint, jsonify, request, session
from decimal import Decimal
import datetime

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _serializar(obj):
    """Convierte tipos no serializables a JSON (Decimal, datetime)."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    raise TypeError(f"Tipo no serializable: {type(obj)}")


def _ok(data, status=200):
    return jsonify({"ok": True, "data": data}), status


def _error(mensaje, status=400):
    return jsonify({"ok": False, "error": mensaje}), status


def _requiere_sesion():
    return "id_usuario" in session


def _requiere_admin_o_trabajador():
    return session.get("id_rol") in (2, 3, 4)  # admin, vendedor, trabajador


# ── Productos ─────────────────────────────────────────────────────────────────

@api_bp.route("/productos")
def listar_productos():
    """
    GET /api/v1/productos
    Parámetros opcionales:
      ?q=<texto>         búsqueda por nombre o marca
      ?categoria=<id>    filtrar por id de categoría
    """
    from app.models.producto import Producto

    busqueda = request.args.get("q", "").strip() or None
    categoria = request.args.get("categoria", type=int)

    filas = Producto.listar_con_variantes(busqueda=busqueda, categoria=categoria)

    # Agrupar variantes bajo cada producto
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
        productos[pid]["variantes"].append({
            "id_variante":   fila["id_variante"],
            "presentacion":  fila["presentacion"],
            "precio":        float(fila["precio"]) if fila["precio"] else 0,
            "stock":         fila["stock"]
        })

    return _ok(list(productos.values()))


@api_bp.route("/productos/<int:id_producto>")
def detalle_producto(id_producto):
    """GET /api/v1/productos/<id>"""
    from app.models.producto import Producto, VarianteProducto

    producto = Producto.obtener_por_id(id_producto)
    if not producto:
        return _error("Producto no encontrado", 404)

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
    """GET /api/v1/categorias"""
    from app.models.categoria import Categoria

    categorias = Categoria.listar_con_conteo()
    return _ok(categorias)


# ── Ofertas ───────────────────────────────────────────────────────────────────

@api_bp.route("/ofertas")
def listar_ofertas():
    """GET /api/v1/ofertas — devuelve solo las ofertas activas"""
    from app.models.oferta import Oferta

    ofertas = Oferta.listar_activas()
    resultado = []
    for o in ofertas:
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
    """GET /api/v1/carrito — items del carrito del usuario autenticado"""
    if not _requiere_sesion():
        return _error("No autenticado", 401)

    from app.models.carrito import Carrito

    carrito = Carrito.obtener_o_crear(session["id_usuario"])
    items = Carrito.obtener_items(carrito["id_carrito"])

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
    Body JSON: { "id_variante": 3, "cantidad": 2 }
    """
    if not _requiere_sesion():
        return _error("No autenticado", 401)

    data = request.get_json()
    if not data:
        return _error("Se requiere body JSON")

    id_variante = data.get("id_variante")
    cantidad = data.get("cantidad", 1)

    if not id_variante:
        return _error("Se requiere id_variante")
    if not isinstance(cantidad, int) or cantidad < 1:
        return _error("La cantidad debe ser un entero mayor a 0")

    from app.models.carrito import Carrito, CarritoItem

    carrito = Carrito.obtener_o_crear(session["id_usuario"])
    CarritoItem.agregar(carrito["id_carrito"], id_variante, cantidad)

    return _ok({"mensaje": "Producto agregado al carrito"}, 201)


# ── Pedidos del cliente (requiere sesión) ──────────────────────────────────────

@api_bp.route("/cuenta/pedidos")
def historial_pedidos():
    """GET /api/v1/cuenta/pedidos — historial de pedidos del cliente autenticado"""
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
    """GET /api/v1/inventario — stock actual de todas las variantes"""
    if not _requiere_admin_o_trabajador():
        return _error("Acceso denegado", 403)

    from app.utils.db import get_connection

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
    """GET /api/v1/estadisticas — métricas generales del negocio"""
    if session.get("id_rol") != 2:
        return _error("Acceso denegado — solo administrador", 403)

    from app.utils.db import get_connection

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    # Total pedidos y ventas
    cursor.execute("""
        SELECT COUNT(*) AS total_pedidos,
               COALESCE(SUM(total), 0) AS ventas_totales
        FROM pedidos
    """)
    ventas = cursor.fetchone()

    # Pedidos por estado
    cursor.execute("""
        SELECT es.nombre_estado, COUNT(*) AS cantidad
        FROM pedidos pe
        JOIN estados_pedido es ON pe.id_estado = es.id_estado
        GROUP BY es.nombre_estado
    """)
    estados = cursor.fetchall()

    # Top 5 productos más vendidos
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

    # Total usuarios activos
    cursor.execute("SELECT COUNT(*) AS total FROM usuarios WHERE activo = TRUE")
    usuarios = cursor.fetchone()

    # Productos con stock crítico (≤5)
    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM variantes_producto v
        JOIN productos p ON v.id_producto = p.id_producto
        WHERE v.stock <= 5 AND p.activo = TRUE
    """)
    stock_critico = cursor.fetchone()

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
    if request.path.startswith("/api/"):
        return _error("Endpoint no encontrado", 404)
    return e


@api_bp.app_errorhandler(405)
def method_not_allowed_api(e):
    if request.path.startswith("/api/"):
        return _error("Método HTTP no permitido", 405)
    return e
