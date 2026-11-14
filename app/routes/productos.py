import logging
from flask import Blueprint, render_template, abort, request
from app.models.producto import Producto, VarianteProducto
from app.models.categoria import Categoria

logger = logging.getLogger(__name__)

productos_bp = Blueprint("productos", __name__, url_prefix="/productos")

MAX_BUSQUEDA = 50


@productos_bp.route("/")
def catalogo():
    # Obtener parámetros de búsqueda y filtro (soporta 'busqueda' o 'q')
    busqueda_param = request.args.get('busqueda')
    if busqueda_param is None and 'q' in request.args:
        busqueda_param = request.args.get('q')

    categoria = request.args.get('categoria', '').strip()
    categoria_id = int(categoria) if categoria and categoria.isdigit() else None

    mensaje_busqueda = None
    ejecutar_consulta = True
    busqueda_final = ""

    if busqueda_param is not None:
        busqueda_limpia = busqueda_param.strip()

        if len(busqueda_limpia) > MAX_BUSQUEDA:
            mensaje_busqueda = f"El término de búsqueda no puede superar los {MAX_BUSQUEDA} caracteres."
            busqueda_limpia = busqueda_limpia[:MAX_BUSQUEDA]

        if not busqueda_limpia:
            # Si el usuario envió búsqueda vacía o solo espacios sin categoría
            if not categoria_id:
                mensaje_busqueda = "Por favor ingresa un término para realizar la búsqueda."
                ejecutar_consulta = False
            busqueda_final = ""
        else:
            busqueda_final = busqueda_limpia
    else:
        # Navegación general del catálogo sin búsqueda explícita
        busqueda_final = ""

    filas = []
    categorias = []
    try:
        categorias = Categoria.listar()
        if ejecutar_consulta:
            filas = Producto.listar_con_variantes(
                busqueda=busqueda_final if busqueda_final else None,
                categoria=categoria_id
            )
    except Exception:
        filas = []

    # Agrupar variantes bajo cada producto para la plantilla
    productos = {}
    for fila in filas:
        id_producto = fila["id_producto"]
        if id_producto not in productos:
            productos[id_producto] = {
                "id_producto": id_producto,
                "nombre_producto": fila["nombre_producto"],
                "descripcion": fila["descripcion"],
                "marca": fila["marca"],
                "imagen_url": fila["imagen_url"],
                "categorias": fila["categorias"],
                "variantes": []
            }
        stock_var = int(fila.get("stock") or 0)
        productos[id_producto]["variantes"].append({
            "id_variante": fila["id_variante"],
            "presentacion": fila["presentacion"],
            "precio": fila["precio"],
            "stock": stock_var,
            "disponible": stock_var > 0
        })

    # Calcular la disponibilidad de cada producto en el catálogo
    for idx, prod in enumerate(productos.values()):
        variantes = prod["variantes"]
        # Convertir stock a entero antes de comparar: int(stock or 0) > 0
        # La disponibilidad se calcula sobre la primera variante con stock > 0
        primera_con_stock = next((v for v in variantes if int(v.get("stock") or 0) > 0), None)
        disponible = primera_con_stock is not None
        prod["disponible"] = disponible
        prod["tiene_stock"] = disponible
        prod["total_stock"] = sum(int(v.get("stock") or 0) for v in variantes)

        # Log temporal de diagnóstico para el primer producto procesado
        if idx == 0:
            var_diag = primera_con_stock or (variantes[0] if variantes else {})
            id_var_diag = var_diag.get("id_variante")
            stock_diag = int(var_diag.get("stock") or 0)
            print(f"[DIAGNÓSTICO CATÁLOGO] id_producto: {prod.get('id_producto')}, id_variante: {id_var_diag}, stock: {stock_diag}, disponible: {disponible}")
            logger.info("[DIAGNÓSTICO CATÁLOGO] id_producto: %s, id_variante: %s, stock: %s, disponible: %s",
                        prod.get('id_producto'), id_var_diag, stock_diag, disponible)

    return render_template(
        "productos/catalogo.html",
        productos=productos.values(),
        categorias=categorias,
        busqueda=busqueda_final,
        categoria_seleccionada=categoria,
        mensaje_busqueda=mensaje_busqueda
    )


@productos_bp.route("/<int:producto_id>")
def detalle(producto_id):
    producto = Producto.obtener_por_id(producto_id)
    if not producto:
        abort(404)

    variantes = VarianteProducto.listar_por_producto(producto_id) or []

    # Consultar y convertir el stock de cada variante a entero
    for v in variantes:
        stock_v = int(v.get("stock") or 0)
        v["stock"] = stock_v
        v["disponible"] = stock_v > 0

    # Determinar la variante seleccionada (por query param 'variante' o selección por defecto)
    variante_param = request.args.get("variante", type=int)
    variante_seleccionada = None
    if variante_param:
        variante_seleccionada = next((v for v in variantes if v["id_variante"] == variante_param), None)

    # Si no se especificó o no se encontró, seleccionar la primera con stock, o la primera si ninguna tiene stock
    if not variante_seleccionada and variantes:
        variante_seleccionada = next((v for v in variantes if int(v.get("stock") or 0) > 0), variantes[0])

    # Revisa que la variante seleccionada por defecto exista (no None) antes de consultar su stock
    if variante_seleccionada is not None:
        stock_seleccionado = int(variante_seleccionada.get("stock") or 0)
        # Condición estricta stock > 0, sin comparar contra otro campo
        disponible = stock_seleccionado > 0
    else:
        stock_seleccionado = 0
        disponible = False

    # Log temporal de diagnóstico en detalle
    id_var_sel = variante_seleccionada.get("id_variante") if variante_seleccionada else None
    print(f"[DIAGNÓSTICO DETALLE] id_producto: {producto_id}, id_variante: {id_var_sel}, stock: {stock_seleccionado}, disponible: {disponible}")
    logger.info("[DIAGNÓSTICO DETALLE] id_producto: %s, id_variante: %s, stock: %s, disponible: %s",
                producto_id, id_var_sel, stock_seleccionado, disponible)

    producto["disponible"] = disponible
    producto["tiene_stock"] = disponible

    # Obtener productos relacionados de la misma categoría
    relacionados = Producto.obtener_relacionados(
        producto_id, 
        producto.get('id_categoria'), 
        limite=4
    )
    
    return render_template(
        "productos/detalle.html", 
        producto=producto, 
        variantes=variantes,
        variante_seleccionada=variante_seleccionada,
        disponible=disponible,
        relacionados=relacionados
    )
