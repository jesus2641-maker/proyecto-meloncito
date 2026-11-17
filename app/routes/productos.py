"""
Módulo de rutas públicas del catálogo y detalle de productos.

Gestiona la navegación del catálogo (`/productos/`), incluyendo búsqueda por
texto, filtrado por categoría, agrupación de variantes (presentaciones) y
cálculo de disponibilidad de stock, así como la vista individual de cada
producto (`/productos/<producto_id>`).
"""

# Módulo estándar para registrar trazas de diagnóstico en consola/archivo
import logging
# Componentes de Flask para blueprint, renderizado HTML, errores HTTP y lectura de query params
from flask import Blueprint, render_template, abort, request
# Modelos de Producto, VarianteProducto y Categoria para consultar catálogo y stock
from app.models.producto import Producto, VarianteProducto
from app.models.categoria import Categoria

# Logger específico del módulo para diagnósticos de stock y catálogo
logger = logging.getLogger(__name__)

# Blueprint de productos con prefijo `/productos`
productos_bp = Blueprint("productos", __name__, url_prefix="/productos")

# Longitud máxima permitida para el término de búsqueda ingresado por el usuario
MAX_BUSQUEDA = 50


@productos_bp.route("/")
def catalogo():
    """
    Vista principal del catálogo de productos con soporte de búsqueda y filtro.

    Lee los parámetros de consulta (`busqueda` o `q`, y `categoria`), valida la
    longitud del término de búsqueda, consulta los productos con sus variantes
    en la base de datos y agrupa las presentaciones bajo cada producto calculando
    su disponibilidad y stock total.

    Returns:
        str: Plantilla HTML `productos/catalogo.html` renderizada con los productos,
            categorías y mensajes de validación de búsqueda.
    """
    # Obtener parámetros de búsqueda y filtro (soporta 'busqueda' o 'q')
    busqueda_param = request.args.get('busqueda')
    if busqueda_param is None and 'q' in request.args:
        busqueda_param = request.args.get('q')

    # Obtiene el parámetro de categoría y lo convierte a entero solo si es numérico
    categoria = request.args.get('categoria', '').strip()
    categoria_id = int(categoria) if categoria and categoria.isdigit() else None

    # Variables de control para feedback al usuario y ejecución condicional de la consulta SQL
    mensaje_busqueda = None
    error_bd = None
    ejecutar_consulta = True
    busqueda_final = ""

    # Validación del parámetro de búsqueda cuando fue enviado explícitamente en la URL
    if busqueda_param is not None:
        busqueda_limpia = busqueda_param.strip()

        # Recorta la búsqueda si excede el límite máximo para evitar consultas excesivas
        if len(busqueda_limpia) > MAX_BUSQUEDA:
            mensaje_busqueda = f"El término de búsqueda no puede superar los {MAX_BUSQUEDA} caracteres."
            busqueda_limpia = busqueda_limpia[:MAX_BUSQUEDA]

        if not busqueda_limpia:
            # Si el usuario envió búsqueda vacía o solo espacios sin categoría, evita consultar todo
            if not categoria_id:
                mensaje_busqueda = "Por favor ingresa un término para realizar la búsqueda."
                ejecutar_consulta = False
            busqueda_final = ""
        else:
            busqueda_final = busqueda_limpia
    else:
        # Navegación general del catálogo sin búsqueda explícita
        busqueda_final = ""

    # Consulta de categorías y productos registrando y reportando fallos de BD
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
        # Registra la traza completa en el log y muestra un mensaje visible al usuario
        logger.exception(
            "Error al consultar el catálogo en MySQL (busqueda=%r, categoria=%r)",
            busqueda_final,
            categoria_id,
        )
        filas = []
        error_bd = "Ocurrió un error al consultar el catálogo en la base de datos. Por favor intenta nuevamente."

    # Agrupar variantes bajo cada producto para la plantilla (1 fila SQL = 1 variante)
    productos = {}
    for fila in filas:
        id_producto = fila["id_producto"]
        # Si es la primera vez que aparece este producto, crea su estructura base
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
        # Normaliza stock y precio para evitar errores al renderizar variantes en Jinja2
        stock_var = int(fila.get("stock") or 0)
        precio_var = fila.get("precio")
        productos[id_producto]["variantes"].append({
            "id_variante": fila["id_variante"],
            "presentacion": fila["presentacion"],
            "precio": precio_var if precio_var is not None else 0,
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
        # Suma el stock acumulado de todas las presentaciones del producto
        prod["total_stock"] = sum(int(v.get("stock") or 0) for v in variantes)

        # Log de diagnóstico para el primer producto procesado
        if idx == 0:
            var_diag = primera_con_stock or (variantes[0] if variantes else {})
            id_var_diag = var_diag.get("id_variante")
            stock_diag = int(var_diag.get("stock") or 0)
            logger.info("[DIAGNÓSTICO CATÁLOGO] id_producto: %s, id_variante: %s, stock: %s, disponible: %s",
                        prod.get('id_producto'), id_var_diag, stock_diag, disponible)

    # Renderiza la vista del catálogo pasando los valores agrupados y filtros activos
    return render_template(
        "productos/catalogo.html",
        productos=list(productos.values()),
        categorias=categorias,
        busqueda=busqueda_final,
        categoria_seleccionada=categoria,
        mensaje_busqueda=mensaje_busqueda,
        error_bd=error_bd,
        ejecutar_consulta=ejecutar_consulta
    )


@productos_bp.route("/<int:producto_id>")
def detalle(producto_id):
    """
    Vista de detalle individual de un producto y sus presentaciones/variantes.

    Si el producto no existe, responde con HTTP 404. Determina qué variante
    mostrar seleccionada por defecto (según el parámetro `variante` o la primera
    con stock disponible), calcula disponibilidad y carga productos relacionados.

    Args:
        producto_id (int): Identificador único del producto en la base de datos.

    Returns:
        str: Plantilla HTML `productos/detalle.html` renderizada.
    """
    # Busca el producto por ID; si no existe, interrumpe con error 404
    producto = Producto.obtener_por_id(producto_id)
    if not producto:
        abort(404)

    # Obtiene todas las variantes asociadas al producto (lista vacía si no hay)
    variantes = VarianteProducto.listar_por_producto(producto_id) or []

    # Consultar y convertir el stock de cada variante a entero y calcular su bandera booleana
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

    # Log de diagnóstico en detalle para verificar consistencia de stock
    id_var_sel = variante_seleccionada.get("id_variante") if variante_seleccionada else None
    logger.info("[DIAGNÓSTICO DETALLE] id_producto: %s, id_variante: %s, stock: %s, disponible: %s",
                producto_id, id_var_sel, stock_seleccionado, disponible)

    # Actualiza las banderas de disponibilidad en el diccionario del producto para la plantilla
    producto["disponible"] = disponible
    producto["tiene_stock"] = disponible

    # Obtener productos relacionados de la misma categoría (máximo 4)
    relacionados = Producto.obtener_relacionados(
        producto_id, 
        producto.get('id_categoria'), 
        limite=4
    )
    
    # Renderiza la página de detalle con el producto, variantes y recomendaciones
    return render_template(
        "productos/detalle.html", 
        producto=producto, 
        variantes=variantes,
        variante_seleccionada=variante_seleccionada,
        disponible=disponible,
        relacionados=relacionados
    )
