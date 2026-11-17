"""
Paquete de modelos de datos de la aplicación BeerHouse.

Este archivo inicializa el subpaquete `app.models` y reexporta todas las clases
de modelo principales para facilitar su importación centralizada desde otras
capas de la aplicación (rutas, servicios y utilidades).
"""

# Importación de modelos de usuarios y control de acceso
from app.models.usuario import Usuario
# Importación del modelo de categorías del catálogo
from app.models.categoria import Categoria
# Importación de modelos de productos y sus variantes/presentaciones
from app.models.producto import Producto, VarianteProducto
# Importación de modelos del carrito de compras y sus ítems
from app.models.carrito import Carrito, CarritoItem
# Importación de modelos de pedidos y sus líneas de detalle
from app.models.pedido import Pedido, PedidoDetalle
# Importación del modelo de direcciones de envío de los usuarios
from app.models.direccion import Direccion
# Importación del modelo de métodos de pago guardados por los usuarios
from app.models.metodo_pago import MetodoPago
# Importación del modelo de proveedores para abastecimiento
from app.models.proveedor import Proveedor
# Importación de modelos de compras a proveedores y su detalle
from app.models.compra import Compra, CompraDetalle
# Importación del modelo de reportes analíticos de solo lectura
from app.models.reporte import Reporte
# Importación del modelo de transacciones de pago (PayPal)
from app.models.pago import Pago

# Lista explícita de símbolos públicos exportados al hacer `from app.models import *`
__all__ = [
    "Usuario",
    "Categoria",
    "Producto",
    "VarianteProducto",
    "Carrito",
    "CarritoItem",
    "Pedido",
    "PedidoDetalle",
    "Direccion",
    "MetodoPago",
    "Proveedor",
    "Compra",
    "CompraDetalle",
    "Reporte",
    "Pago",
]
