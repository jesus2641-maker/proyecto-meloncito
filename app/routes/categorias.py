"""
Módulo de rutas para la visualización pública de categorías de productos.

Expone la vista `/categorias`, la cual consulta el listado dinámico de categorías
almacenadas en la base de datos y las presenta en la plantilla correspondiente.
"""

# Utilidades de Flask para definir el blueprint y renderizar plantillas HTML
from flask import Blueprint, render_template
# Modelo de datos para consultar las categorías desde la base de datos
from app.models.categoria import Categoria

# Blueprint de categorías; se omite url_prefix para exponer directamente `/categorias`
categorias_bp = Blueprint("categorias", __name__)  # Sin url_prefix para no crear /categorias/categorias


@categorias_bp.route("/categorias")
def index():
    """
    Página de categorías dinámica que carga los registros desde la base de datos.

    Consulta todas las categorías disponibles mediante `Categoria.listar()` y las
    envía a la plantilla `categorias.html`.

    Returns:
        str: Contenido HTML renderizado con el listado de categorías.
    """
    # Obtiene la lista de categorías activas/registradas desde la base de datos
    categorias = Categoria.listar()
    # Renderiza la vista HTML pasando la colección de categorías al contexto de Jinja2
    return render_template("categorias.html", categorias=categorias)
