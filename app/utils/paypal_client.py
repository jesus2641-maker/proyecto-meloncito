"""
Cliente HTTP para PayPal REST API (Orders v2 y Payments v2).
Implementado únicamente con urllib.request y json de la librería estándar.
No registra ni expone tokens, secretos ni cuerpos completos de respuesta.
"""

import base64
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from config import Config, resolver_paypal_api_base, resolver_paypal_mode

logger = logging.getLogger(__name__)

TIMEOUT_SEGUNDOS = 10
MARGEN_EXPIRACION_SEGUNDOS = 60

_token_cache = {
    "access_token": None,
    "expira_en": 0.0,
    "cache_key": None,
}


class PayPalError(Exception):
    """Excepción para errores devueltos por PayPal o fallos de conexión HTTP."""

    def __init__(self, mensaje, codigo="PAYPAL_ERROR", status_code=None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo or "PAYPAL_ERROR"
        self.status_code = status_code


def limpiar_cache_token():
    """Limpia el token OAuth2 almacenado en memoria (útil para pruebas o cambio de credenciales)."""
    _token_cache["access_token"] = None
    _token_cache["expira_en"] = 0.0
    _token_cache["cache_key"] = None


def obtener_url_base(modo=None, api_base=None):
    """
    Obtiene la URL base de PayPal según PAYPAL_MODE ('sandbox' por defecto;
    solo 'live' si se especifica explícitamente) o PAYPAL_API_BASE si está definida.
    """
    if api_base is not None or modo is not None:
        return resolver_paypal_api_base(modo=modo, api_base=api_base)

    env_base = os.getenv("PAYPAL_API_BASE")
    if env_base and env_base.strip():
        return env_base.strip().rstrip("/")

    cfg_base = getattr(Config, "PAYPAL_API_BASE", None)
    cfg_mode = getattr(Config, "PAYPAL_MODE", None)
    env_mode = os.getenv("PAYPAL_MODE")

    if env_mode is not None:
        return resolver_paypal_api_base(modo=env_mode, api_base=env_base)
    if cfg_base and cfg_base not in ("https://api-m.sandbox.paypal.com", "https://api-m.paypal.com"):
        return cfg_base.rstrip("/")
    return resolver_paypal_api_base(modo=cfg_mode, api_base=None)


def _obtener_credenciales():
    client_id = (getattr(Config, "PAYPAL_CLIENT_ID", None) or os.getenv("PAYPAL_CLIENT_ID", "") or "").strip()
    client_secret = (getattr(Config, "PAYPAL_CLIENT_SECRET", None) or os.getenv("PAYPAL_CLIENT_SECRET", "") or "").strip()
    return client_id, client_secret


def paypal_configurado():
    """Devuelve True solo si tanto PAYPAL_CLIENT_ID como PAYPAL_CLIENT_SECRET están configurados."""
    client_id, client_secret = _obtener_credenciales()
    return bool(client_id and client_secret)


def formatear_monto(monto):
    """
    Convierte un monto numérico o Decimal al formato string de 2 decimales
    requerido por PayPal Orders v2 (por ejemplo, '12.50').
    """
    if monto is None or isinstance(monto, bool):
        raise ValueError("El monto no puede ser nulo")
    try:
        valor = Decimal(str(monto)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("El monto proporcionado no es válido") from exc
    if valor <= Decimal("0.00"):
        raise ValueError("El monto debe ser mayor que cero")
    return f"{valor:.2f}"


def _extraer_error_paypal(raw_body, status_code=None):
    """
    Extrae el código de error específico de PayPal (ej. INSTRUMENT_DECLINED,
    ORDER_ALREADY_CAPTURED) y un mensaje seguro sin exponer todo el payload.
    """
    codigo = f"HTTP_{status_code}" if status_code else "PAYPAL_API_ERROR"
    mensaje = "Error al comunicarse con PayPal"

    if not raw_body:
        return mensaje, codigo

    try:
        data = json.loads(raw_body)
    except Exception:
        return mensaje, codigo

    if not isinstance(data, dict):
        return mensaje, codigo

    name = data.get("name") or data.get("error")
    message = data.get("message") or data.get("error_description")
    details = data.get("details")

    if isinstance(details, list) and details:
        primero = details[0] if isinstance(details[0], dict) else {}
        issue = primero.get("issue")
        description = primero.get("description")
        if issue:
            codigo = str(issue)
        elif name:
            codigo = str(name)
        if description:
            mensaje = str(description)
        elif message:
            mensaje = str(message)
    else:
        if name:
            codigo = str(name)
        if message:
            mensaje = str(message)

    return mensaje, codigo


def _ejecutar_peticion(url, method="POST", headers=None, raw_data=None):
    req_headers = dict(headers or {})
    req = urllib.request.Request(url=url, data=raw_data, headers=req_headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            contenido = resp.read().decode("utf-8", errors="replace")
            if status < 200 or status >= 300:
                mensaje, codigo = _extraer_error_paypal(contenido, status_code=status)
                raise PayPalError(mensaje, codigo=codigo, status_code=status)
            if not contenido.strip():
                return {}
            try:
                return json.loads(contenido)
            except json.JSONDecodeError as exc:
                raise PayPalError("Respuesta JSON inválida de PayPal", codigo="INVALID_JSON_RESPONSE", status_code=status) from exc
    except urllib.error.HTTPError as err:
        cuerpo_error = ""
        try:
            if err.fp is not None:
                cuerpo_error = err.read().decode("utf-8", errors="replace")
        except Exception:
            cuerpo_error = ""
        mensaje, codigo = _extraer_error_paypal(cuerpo_error, status_code=err.code)
        logger.warning("PayPal respondió con error HTTP %s (código=%s)", err.code, codigo)
        raise PayPalError(mensaje, codigo=codigo, status_code=err.code) from err
    except urllib.error.URLError as err:
        logger.error("Error de red al conectar con PayPal: %s", getattr(err, "reason", "desconocido"))
        raise PayPalError("No se pudo conectar con PayPal", codigo="NETWORK_ERROR") from err
    except TimeoutError as err:
        logger.error("Tiempo de espera agotado al conectar con PayPal")
        raise PayPalError("Tiempo de espera agotado al conectar con PayPal", codigo="TIMEOUT_ERROR") from err


def obtener_token(request_id=None):
    """
    Obtiene un access_token OAuth2 mediante POST {base}/v1/oauth2/token
    con autenticación Basic (client_id:secret) y grant_type=client_credentials.
    Guarda el token en memoria hasta 60 segundos antes de que expire.
    """
    client_id, client_secret = _obtener_credenciales()
    if not client_id or not client_secret:
        raise PayPalError("PayPal no está configurado (faltan credenciales)", codigo="PAYPAL_NOT_CONFIGURED")

    base_url = obtener_url_base()
    cache_key = f"{base_url}|{client_id}"
    ahora = time.time()

    if (
        _token_cache["access_token"]
        and _token_cache["cache_key"] == cache_key
        and ahora < _token_cache["expira_en"]
    ):
        return _token_cache["access_token"]

    credenciales_b64 = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    headers = {
        "Authorization": f"Basic {credenciales_b64}",
        "Accept": "application/json",
        "Accept-Language": "en_US",
        "Content-Type": "application/x-www-form-urlencoded",
        "PayPal-Request-ID": str(request_id or f"oauth-{int(ahora * 1000)}"),
    }
    cuerpo = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")

    data = _ejecutar_peticion(
        url=f"{base_url}/v1/oauth2/token",
        method="POST",
        headers=headers,
        raw_data=cuerpo,
    )

    token = data.get("access_token")
    if not token:
        raise PayPalError("PayPal no devolvió un token de acceso válido", codigo="INVALID_TOKEN_RESPONSE")

    try:
        expires_in = int(data.get("expires_in", 3600))
    except (TypeError, ValueError):
        expires_in = 3600

    _token_cache["access_token"] = token
    _token_cache["expira_en"] = ahora + max(0, expires_in - MARGEN_EXPIRACION_SEGUNDOS)
    _token_cache["cache_key"] = cache_key

    return token


def crear_orden(id_pedido, monto, moneda, request_id):
    """
    Crea una orden en PayPal Orders v2:
    POST {base}/v2/checkout/orders con intent CAPTURE, reference_id 'pedido-<id>',
    custom_id '<id>', description 'Pedido #<id> Beer House', amount con value en
    string de 2 decimales y shipping_preference NO_SHIPPING.
    Devuelve el id de la orden.
    """
    if not request_id or not str(request_id).strip():
        raise ValueError("request_id es obligatorio para crear una orden en PayPal")

    monto_str = formatear_monto(monto)
    moneda_str = (moneda or getattr(Config, "PAYPAL_CURRENCY", "USD") or "USD").strip().upper()
    id_pedido_str = str(id_pedido)

    token = obtener_token()
    base_url = obtener_url_base()

    purchase_units = [
        {
            "reference_id": f"pedido-{id_pedido_str}",
            "custom_id": id_pedido_str,
            "description": f"Pedido #{id_pedido_str} Beer House",
            "amount": {
                "currency_code": moneda_str,
                "value": monto_str,
            },
        }
    ]

    payload_inicial = {
        "intent": "CAPTURE",
        "purchase_units": purchase_units,
        "payment_source": {
            "paypal": {
                "experience_context": {
                    "shipping_preference": "NO_SHIPPING",
                }
            }
        },
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "PayPal-Request-ID": str(request_id).strip(),
    }

    try:
        data = _ejecutar_peticion(
            url=f"{base_url}/v2/checkout/orders",
            method="POST",
            headers=headers,
            raw_data=json.dumps(payload_inicial).encode("utf-8"),
        )
    except PayPalError as exc:
        if exc.status_code in (400, 422):
            logger.warning(
                "PayPal respondió con error HTTP %s (%s) en creación de orden con experience_context; reintentando con payload mínimo",
                exc.status_code,
                exc.codigo or exc.mensaje,
            )
            payload_minimo = {
                "intent": "CAPTURE",
                "purchase_units": purchase_units,
            }
            data = _ejecutar_peticion(
                url=f"{base_url}/v2/checkout/orders",
                method="POST",
                headers=headers,
                raw_data=json.dumps(payload_minimo).encode("utf-8"),
            )
        else:
            raise

    order_id = data.get("id")
    if not order_id:
        raise PayPalError("PayPal no devolvió el identificador de la orden", codigo="INVALID_ORDER_RESPONSE")

    return str(order_id)


def capturar_orden(order_id, request_id):
    """
    Captura una orden aprobada en PayPal Orders v2:
    POST {base}/v2/checkout/orders/{id}/capture con cuerpo {}.
    Devuelve un dict normalizado {estado, capture_id, monto, moneda, custom_id}
    extraído de purchase_units[0].payments.captures[0].
    """
    if not order_id or not str(order_id).strip():
        raise ValueError("order_id es obligatorio para capturar una orden")
    if not request_id or not str(request_id).strip():
        raise ValueError("request_id es obligatorio para capturar una orden")

    token = obtener_token()
    base_url = obtener_url_base()
    order_id_limpio = urllib.parse.quote(str(order_id).strip(), safe="")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "PayPal-Request-ID": str(request_id).strip(),
    }

    data = _ejecutar_peticion(
        url=f"{base_url}/v2/checkout/orders/{order_id_limpio}/capture",
        method="POST",
        headers=headers,
        raw_data=b"{}",
    )

    purchase_units = data.get("purchase_units") or []
    if not purchase_units or not isinstance(purchase_units[0], dict):
        raise PayPalError("Respuesta de captura sin purchase_units", codigo="INVALID_CAPTURE_RESPONSE")

    pu0 = purchase_units[0]
    payments = pu0.get("payments") or {}
    captures = payments.get("captures") or []
    if not captures or not isinstance(captures[0], dict):
        raise PayPalError("Respuesta de captura sin captures", codigo="INVALID_CAPTURE_RESPONSE")

    cap0 = captures[0]
    amount = cap0.get("amount") or {}

    estado = cap0.get("status") or data.get("status")
    capture_id = cap0.get("id")
    monto = amount.get("value")
    moneda = amount.get("currency_code")
    custom_id = cap0.get("custom_id") if cap0.get("custom_id") is not None else pu0.get("custom_id")

    return {
        "estado": str(estado) if estado is not None else None,
        "capture_id": str(capture_id) if capture_id is not None else None,
        "monto": str(monto) if monto is not None else None,
        "moneda": str(moneda) if moneda is not None else None,
        "custom_id": str(custom_id) if custom_id is not None else None,
    }


def reembolsar_captura(capture_id, request_id):
    """
    Reembolsa totalmente una captura en PayPal Payments v2:
    POST {base}/v2/payments/captures/{capture_id}/refund con cuerpo {}.
    Devuelve {estado, refund_id}.
    """
    if not capture_id or not str(capture_id).strip():
        raise ValueError("capture_id es obligatorio para reembolsar una captura")
    if not request_id or not str(request_id).strip():
        raise ValueError("request_id es obligatorio para reembolsar una captura")

    token = obtener_token()
    base_url = obtener_url_base()
    capture_id_limpio = urllib.parse.quote(str(capture_id).strip(), safe="")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "PayPal-Request-ID": str(request_id).strip(),
    }

    data = _ejecutar_peticion(
        url=f"{base_url}/v2/payments/captures/{capture_id_limpio}/refund",
        method="POST",
        headers=headers,
        raw_data=b"{}",
    )

    refund_id = data.get("id")
    estado = data.get("status")
    if not refund_id:
        raise PayPalError("PayPal no devolvió el identificador del reembolso", codigo="INVALID_REFUND_RESPONSE")

    return {
        "estado": str(estado) if estado is not None else None,
        "refund_id": str(refund_id),
    }
