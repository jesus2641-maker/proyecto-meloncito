from app.routes.auth import auth_bp
from app.routes.productos import productos_bp
from app.routes.carrito import carrito_bp
from app.routes.admin import admin_bp
from app.routes.cuenta import cuenta_bp

__all__ = [
    "auth_bp",
    "productos_bp",
    "carrito_bp",
    "admin_bp",
    "cuenta_bp",
]