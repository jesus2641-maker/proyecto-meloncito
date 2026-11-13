"""
Proxy/alias para exponer app.services.paypal_service en el namespace raíz 'services'.
"""

from app.services.paypal_service import (
    get_access_token,
    create_order,
    capture_order,
    refund_capture,
)

__all__ = [
    "get_access_token",
    "create_order",
    "capture_order",
    "refund_capture",
]
