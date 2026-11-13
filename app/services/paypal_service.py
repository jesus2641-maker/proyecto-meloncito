"""
Servicio de integración con PayPal Orders v2 (Modo Sandbox / Live)
Maneja autenticación OAuth2 con caché de tokens, creación de órdenes,
captura de pagos y reembolsos ante fallas de transacción.
"""

import os
import time
import logging
from decimal import Decimal
import requests

logger = logging.getLogger(__name__)

# Caché en memoria para el token de acceso OAuth2
_TOKEN_CACHE = {
    "access_token": None,
    "expires_at": 0,
}


def _obtener_config_paypal():
    """
    Lee las variables de entorno para PayPal.
    No expone credenciales en código.
    """
    client_id = os.getenv("PAYPAL_CLIENT_ID", "").strip()
    client_secret = os.getenv("PAYPAL_CLIENT_SECRET", "").strip()
    modo = os.getenv("PAYPAL_MODE", "sandbox").strip().lower()

    if modo == "live":
        base_url = "https://api-m.paypal.com"
    else:
        base_url = "https://api-m.sandbox.paypal.com"

    # Permite sobreescribir la URL base si está configurada en .env
    override_base = os.getenv("PAYPAL_API_BASE", "").strip()
    if override_base:
        base_url = override_base.rstrip("/")

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "mode": modo,
        "base_url": base_url,
    }


def get_access_token():
    """
    Obtiene un token de acceso OAuth2 contra PayPal usando client_credentials.
    Mantiene el token en caché hasta que expire (con un margen de seguridad de 60 segundos).

    Returns:
        str: Token de acceso válido (Bearer token)
    Raises:
        RuntimeError: Si las credenciales no están configuradas
        requests.RequestException: Si falla la petición HTTP contra PayPal
    """
    global _TOKEN_CACHE

    ahora = time.time()
    if _TOKEN_CACHE["access_token"] and ahora < (_TOKEN_CACHE["expires_at"] - 60):
        return _TOKEN_CACHE["access_token"]

    cfg = _obtener_config_paypal()
    client_id = cfg["client_id"]
    client_secret = cfg["client_secret"]

    if not client_id or not client_secret:
        raise RuntimeError("PAYPAL_CLIENT_ID o PAYPAL_CLIENT_SECRET no están configurados en el entorno.")

    url = f"{cfg['base_url']}/v1/oauth2/token"
    headers = {
        "Accept": "application/json",
        "Accept-Language": "en_US",
    }
    data = {"grant_type": "client_credentials"}

    logger.info("Solicitando nuevo access token a PayPal (%s)...", cfg["mode"])
    response = requests.post(
        url,
        auth=(client_id, client_secret),
        headers=headers,
        data=data,
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()

    access_token = payload.get("access_token")
    expires_in = int(payload.get("expires_in", 3600))

    _TOKEN_CACHE["access_token"] = access_token
    _TOKEN_CACHE["expires_at"] = ahora + expires_in
    logger.info("Access token de PayPal obtenido exitosamente (expira en %ss)", expires_in)

    return access_token


def create_order(total, currency="USD", reference_id=None):
    """
    Crea una orden en PayPal v2 con intent CAPTURE.

    Args:
        total: Monto total (int, float, Decimal o str). Formateado a 2 decimales.
        currency: Código de moneda (ej: 'USD').
        reference_id: Referencia interna opcional (ej: id_carrito).

    Returns:
        dict: Respuesta JSON de PayPal conteniendo el 'id' de la orden.
    Raises:
        requests.RequestException: Si falla la comunicación o PayPal rechaza la orden.
    """
    cfg = _obtener_config_paypal()
    token = get_access_token()

    monto_formateado = f"{Decimal(str(total)):.2f}"
    url = f"{cfg['base_url']}/v2/checkout/orders"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    purchase_unit = {
        "amount": {
            "currency_code": currency.upper(),
            "value": monto_formateado,
        }
    }
    if reference_id is not None:
        purchase_unit["reference_id"] = str(reference_id)
        purchase_unit["custom_id"] = str(reference_id)

    body = {
        "intent": "CAPTURE",
        "purchase_units": [purchase_unit],
    }

    logger.info("Creando orden de PayPal v2 por monto %s %s...", monto_formateado, currency)
    response = requests.post(url, json=body, headers=headers, timeout=15)
    response.raise_for_status()
    orden = response.json()
    logger.info("Orden de PayPal creada con ID: %s", orden.get("id"))
    return orden


def capture_order(order_id):
    """
    Captura una orden aprobada en PayPal v2.

    Args:
        order_id: ID de la orden devuelto por create_order y aprobado por el comprador.

    Returns:
        dict: Respuesta JSON de PayPal con el estado de la captura ('COMPLETED', etc.).
    Raises:
        requests.RequestException: Si falla la captura.
    """
    cfg = _obtener_config_paypal()
    token = get_access_token()

    url = f"{cfg['base_url']}/v2/checkout/orders/{order_id}/capture"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    logger.info("Capturando orden de PayPal con ID: %s...", order_id)
    response = requests.post(url, headers=headers, timeout=15)
    response.raise_for_status()
    datos_captura = response.json()
    logger.info("Orden %s capturada con estado: %s", order_id, datos_captura.get("status"))
    return datos_captura


def refund_capture(capture_id, note="Reembolso por fallo en creación de pedido"):
    """
    Reembolsa una captura de PayPal en caso de fallo en la transacción local.
    Garantiza que nunca quede un cobro realizado sin pedido en la base de datos.

    Args:
        capture_id: ID de la captura de PayPal.
        note: Motivo del reembolso.

    Returns:
        dict: Respuesta JSON del reembolso.
    """
    cfg = _obtener_config_paypal()
    token = get_access_token()

    url = f"{cfg['base_url']}/v2/payments/captures/{capture_id}/refund"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    body = {"note_to_payer": note}

    logger.warning("Iniciando reembolso para capture_id %s. Motivo: %s", capture_id, note)
    response = requests.post(url, json=body, headers=headers, timeout=15)
    response.raise_for_status()
    resultado = response.json()
    logger.info("Reembolso para capture_id %s completado con estado: %s", capture_id, resultado.get("status"))
    return resultado
