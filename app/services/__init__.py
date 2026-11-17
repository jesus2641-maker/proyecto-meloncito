"""
Paquete `app.services` — Capa de servicios de lógica de negocio de Beer House.

Expone las funciones principales de orquestación que coordinan modelos,
transacciones de base de datos y clientes externos (como la pasarela PayPal),
manteniendo las rutas Flask limpias y desacopladas de la lógica compleja.
"""

# Reexportamos las operaciones públicas del servicio de pagos con PayPal
# para permitir importaciones directas desde `app.services`.
from app.services.pagos_paypal import (
    iniciar_pago,
    capturar_pago,
    cancelar_pedido_con_reembolso,
    cancelar_impagos_vencidos,
)

# `__all__` define explícitamente la interfaz pública del paquete cuando se
# importa con `from app.services import *` y documenta los símbolos exportados.
__all__ = [
    "iniciar_pago",
    "capturar_pago",
    "cancelar_pedido_con_reembolso",
    "cancelar_impagos_vencidos",
]
