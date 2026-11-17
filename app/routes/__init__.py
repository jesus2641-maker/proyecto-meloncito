"""
Paquete de rutas (Blueprints) de la aplicación Beer House.

Este módulo centraliza y reexporta los blueprints principales del sistema para
facilitar su importación y registro en la fábrica de aplicaciones (`create_app`).
Nota: Otros blueprints adicionales (como `api_bp`, `categorias_bp`, `edad_bp`,
`pagos_bp` y `trabajador_bp`) se importan directamente desde sus respectivos
submódulos cuando se registran en la aplicación.
"""

# Importación de los blueprints principales definidos en el paquete app.routes
from app.routes.auth import auth_bp
from app.routes.productos import productos_bp
from app.routes.carrito import carrito_bp
from app.routes.admin import admin_bp
from app.routes.cuenta import cuenta_bp

# Lista pública de símbolos exportados al usar `from app.routes import *`
__all__ = [
    "auth_bp",
    "productos_bp",
    "carrito_bp",
    "admin_bp",
    "cuenta_bp",
]