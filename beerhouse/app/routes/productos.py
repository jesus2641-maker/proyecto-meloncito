from flask import Blueprint, render_template, abort
from app.models.producto import Producto, VarianteProducto

productos_bp = Blueprint("productos", __name__, url_prefix="/productos")


@productos_bp.route("/")
def catalogo():
    filas = Producto.listar_con_variantes()

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

    return render_template("productos/catalogo.html", productos=productos.values())


@productos_bp.route("/<int:producto_id>")
def detalle(producto_id):
    producto = Producto.obtener_por_id(producto_id)
    if not producto:
        abort(404)

    variantes = VarianteProducto.listar_por_producto(producto_id)
    return render_template("productos/detalle.html", producto=producto, variantes=variantes)
