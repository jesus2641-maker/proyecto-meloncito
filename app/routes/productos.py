from flask import Blueprint, render_template, abort, request
from app.models.producto import Producto, VarianteProducto
from app.models.categoria import Categoria

productos_bp = Blueprint("productos", __name__, url_prefix="/productos")


@productos_bp.route("/")
def catalogo():
    # Obtener parámetros de búsqueda y filtro
    busqueda = request.args.get('busqueda', '')
    categoria = request.args.get('categoria', '')
    
    # Convertir parámetros numéricos
    categoria_id = int(categoria) if categoria else None
    
    filas = Producto.listar_con_variantes(
        busqueda=busqueda if busqueda else None,
        categoria=categoria_id
    )

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
                "nombre_categoria": fila["nombre_categoria"],
                "variantes": []
            }
        productos[id_producto]["variantes"].append({
            "id_variante": fila["id_variante"],
            "presentacion": fila["presentacion"],
            "precio": fila["precio"],
            "stock": fila["stock"]
        })

    # Obtener categorías para el filtro
    categorias = Categoria.listar()
    
    return render_template("productos/catalogo.html", 
                         productos=productos.values(),
                         categorias=categorias,
                         busqueda=busqueda,
                         categoria_seleccionada=categoria)


@productos_bp.route("/<int:producto_id>")
def detalle(producto_id):
    producto = Producto.obtener_por_id(producto_id)
    if not producto:
        abort(404)

    variantes = VarianteProducto.listar_por_producto(producto_id)
    
    # Obtener productos relacionados de la misma categoría
    relacionados = Producto.obtener_relacionados(
        producto_id, 
        producto.get('id_categoria'), 
        limite=4
    )
    
    return render_template("productos/detalle.html", 
                         producto=producto, 
                         variantes=variantes,
                         relacionados=relacionados)
