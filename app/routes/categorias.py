from flask import Blueprint, render_template
from app.models.categoria import Categoria

categorias_bp = Blueprint("categorias", __name__)  # Sin url_prefix para no crear /categorias/categorias


@categorias_bp.route("/categorias")
def index():
    """Página de categorías dinámica que carga desde la base de datos."""
    categorias = Categoria.listar()
    return render_template("categorias.html", categorias=categorias)
