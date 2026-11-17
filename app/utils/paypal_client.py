"""
Cliente HTTP para PayPal REST API (Orders v2 y Payments v2).

Implementado únicamente con `urllib.request` y `json` de la librería estándar de Python
para no añadir dependencias externas pesadas. Incluye:
- Caché en memoria del token OAuth2 (`client_credentials`) con margen de expiración.
- Idempotencia mediante el encabezado `PayPal-Request-ID`.
- Manejo estructurado de errores (`PayPalError`) sin registrar ni exponer tokens,
  secretos ni cuerpos completos de respuesta en los logs.
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

# Logger del módulo para registrar eventos HTTP/red sin datos sensibles
logger = logging.getLogger(__name__)

# Tiempo máximo de espera por petición HTTP hacia los servidores de PayPal
TIMEOUT_SEGUNDOS = 10
# Margen de seguridad para renovar el token OAuth2 antes de su vencimiento real
MARGEN_EXPIRACION_SEGUNDOS = 60

# Caché en memoria del token OAuth2 por proceso (evita pedir token en cada petición)
_token_cache = {
    "access_token": None,
    "expira_en": 0.0,
    "cache_key": None,
}


class PayPalError(Exception):
    """
    Excepción personalizada para errores devueltos por la API de PayPal o fallos HTTP/red.

    Attributes:
        mensaje (str): Descripción legible del error.
        codigo (str): Código de error específico de PayPal (ej. `INSTRUMENT_DECLINED`)
            o código interno (`NETWORK_ERROR`, `HTTP_422`, etc.).
        status_code (int | None): Código de estado HTTP devuelto por PayPal si aplica.
    """

    def __init__(self, mensaje, codigo="PAYPAL_ERROR", status_code=None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo or "PAYPAL_ERROR"
        self.status_code = status_code


def limpiar_cache_token():
    """
    Limpia el token OAuth2 almacenado en memoria.

    Útil principalmente en pruebas unitarias o tras rotar credenciales en caliente.
    """
    _token_cache["access_token"] = None
    _token_cache["expira_en"] = 0.0
    _token_cache["cache_key"] = None


def obtener_url_base(modo=None, api_base=None):
    """
    Determina la URL base de la API de PayPal a utilizar (`sandbox` o `live`).

    Prioridad de resolución:
    1. Parámetros explícitos `modo` o `api_base`.
    2. Variable de entorno `PAYPAL_API_BASE` si está definida.
    3. Variable de entorno `PAYPAL_MODE` o valores en `Config`.

    Args:
        modo (str | None): `'sandbox'` o `'live'` (opcional).
        api_base (str | None): URL base personalizada (opcional).

    Returns:
        str: URL base sin barra final (ej. `'https://api-m.sandbox.paypal.com'`).
    """
    if api_base is not None or modo is not None:
        return resolver_paypal_api_base(modo=modo, api_base=api_base)

    # Revisamos primero si hay override explícito por variable de entorno
    env_base = os.getenv("PAYPAL_API_BASE")
    if env_base and env_base.strip():
        return env_base.strip().rstrip("/")

    cfg_base = getattr(Config, "PAYPAL_API_BASE", None)
    cfg_mode = getattr(Config, "PAYPAL_MODE", None)
    env_mode = os.getenv("PAYPAL_MODE")

    if env_mode is not None:
        return resolver_paypal_api_base(modo=env_mode, api_base=env_base)
    # Si Config tiene una URL custom (distinta a las estándar de PayPal), la respetamos
    if cfg_base and cfg_base not in ("https://api-m.sandbox.paypal.com", "https://api-m.paypal.com"):
        return cfg_base.rstrip("/")
    return resolver_paypal_api_base(modo=cfg_mode, api_base=None)


def _obtener_credenciales():
    """
    Obtiene `client_id` y `client_secret` de PayPal desde `Config` o variables de entorno.

    Soporta tanto `PAYPAL_SECRET` como `PAYPAL_CLIENT_SECRET` por compatibilidad.

    Returns:
        tuple[str, str]: Par `(client_id, client_secret)` sin espacios extremos.
    """
    client_id = (getattr(Config, "PAYPAL_CLIENT_ID", None) or os.getenv("PAYPAL_CLIENT_ID", "") or "").strip()
    client_secret = (
        getattr(Config, "PAYPAL_SECRET", None)
        or getattr(Config, "PAYPAL_CLIENT_SECRET", None)
        or os.getenv("PAYPAL_SECRET", "")
        or os.getenv("PAYPAL_CLIENT_SECRET", "")
        or ""
    ).strip()
    return client_id, client_secret


def obtener_base_url_app():
    """
    Devuelve la URL base pública de la aplicación (`BASE_URL`) sin barra final.

    Se usa para construir `return_url` y `cancel_url` en las órdenes de PayPal.
    Por defecto usa `http://localhost:5000` en entorno local.

    Returns:
        str: URL base de la aplicación Flask.
    """
    base = os.getenv("BASE_URL") or getattr(Config, "BASE_URL", None) or "http://localhost:5000"
    return str(base).strip().rstrip("/")


def paypal_configurado():
    """
    Indica si las credenciales mínimas de PayPal están presentes en el entorno.

    Returns:
        bool: `True` únicamente si tanto `PAYPAL_CLIENT_ID` como el secreto no están vacíos.
    """
    client_id, client_secret = _obtener_credenciales()
    return bool(client_id and client_secret)


def formatear_monto(monto):
    """
    Convierte un monto numérico o `Decimal` al formato string de 2 decimales
    exigido por PayPal Orders v2 (por ejemplo, `'12.50'`).

    Args:
        monto (int | float | str | Decimal): Importe a formatear (debe ser > 0).

    Returns:
        str: Monto formateado con exactamente 2 decimales y punto decimal.

    Raises:
        ValueError: Si el monto es nulo, booleano, no numérico o menor/igual a cero.
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
    Extrae el código de error específico de PayPal (ej. `INSTRUMENT_DECLINED`,
    `ORDER_ALREADY_CAPTURED`) y un mensaje seguro sin exponer el payload completo.

    Args:
        raw_body (str): Cuerpo crudo de la respuesta de error HTTP.
        status_code (int | None): Código HTTP de la respuesta fallida.

    Returns:
        tuple[str, str]: Par `(mensaje_seguro, codigo_error)`.
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

    # PayPal usa `name`/`message` en API v2 y `error`/`error_description` en OAuth2
    name = data.get("name") or data.get("error")
    message = data.get("message") or data.get("error_description")
    details = data.get("details")

    # Si existe el arreglo `details`, priorizamos el primer `issue` (código más granular)
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
    """
    Ejecuta una petición HTTP contra la API de PayPal usando `urllib.request`.

    Centraliza el timeout, decodificación UTF-8, parseo JSON y traducción de
    excepciones (`HTTPError`, `URLError`, `TimeoutError`) a `PayPalError`.

    Args:
        url (str): URL completa del endpoint de PayPal.
        method (str): Método HTTP (`POST`, `GET`, etc.).
        headers (dict | None): Encabezados HTTP de la petición.
        raw_data (bytes | None): Cuerpo binario de la petición.

    Returns:
        dict: Respuesta JSON decodificada (o `{}` si el cuerpo está vacío).

    Raises:
        PayPalError: Ante códigos HTTP >= 300, JSON inválido, fallo de red o timeout.
    """
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
        # En urllib, los códigos 4xx/5xx lanzan HTTPError; leemos su cuerpo para extraer el `issue`
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
    Obtiene un `access_token` OAuth2 mediante `POST {base}/v1/oauth2/token`
    con autenticación Basic (`client_id:secret`) y `grant_type=client_credentials`.

    Guarda el token en memoria (`_token_cache`) asociado a `(base_url, client_id)`
    hasta 60 segundos antes de su expiración para minimizar llamadas OAuth.

    Args:
        request_id (str | None): Valor opcional para el header `PayPal-Request-ID`.

    Returns:
        str: Token Bearer válido para autenticar llamadas a Orders v2 / Payments v2.

    Raises:
        PayPalError: Si faltan credenciales o PayPal no devuelve un `access_token`.
    """
    client_id, client_secret = _obtener_credenciales()
    if not client_id or not client_secret:
        raise PayPalError("PayPal no está configurado (faltan credenciales)", codigo="PAYPAL_NOT_CONFIGURED")

    base_url = obtener_url_base()
    # La clave de caché incluye URL base y client_id para no mezclar Sandbox/Live
    cache_key = f"{base_url}|{client_id}"
    ahora = time.time()

    # Si existe un token en caché para esta configuración y no ha vencido, lo reutilizamos
    if (
        _token_cache["access_token"]
        and _token_cache["cache_key"] == cache_key
        and ahora < _token_cache["expira_en"]
    ):
        return _token_cache["access_token"]

    # Codificamos `client_id:client_secret` en Base64 para HTTP Basic Auth
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

    # Almacenamos en caché restando el margen de seguridad para evitar usar un token al borde de expirar
    _token_cache["access_token"] = token
    _token_cache["expira_en"] = ahora + max(0, expires_in - MARGEN_EXPIRACION_SEGUNDOS)
    _token_cache["cache_key"] = cache_key

    return token


def crear_orden(id_pedido, monto, moneda, request_id, return_url=None, cancel_url=None):
    """
    Crea una orden de pago en PayPal Orders v2 (`POST {base}/v2/checkout/orders`).

    Configura `intent="CAPTURE"`, `reference_id="pedido-<id>"`, `custom_id="<id>"`,
    `description="Pedido #<id> Beer House"`, monto con 2 decimales y
    `shipping_preference="NO_SHIPPING"`. Si PayPal rechaza el bloque
    `payment_source.paypal.experience_context` con HTTP 400/422, reintenta con un
    payload mínimo compatible.

    Args:
        id_pedido (int | str): Identificador interno del pedido en Beer House.
        monto (Decimal | float | str): Importe a cobrar en la moneda indicada.
        moneda (str): Código ISO de moneda de 3 letras (ej. `'USD'`).
        request_id (str): Identificador de idempotencia (`PayPal-Request-ID`).
        return_url (str | None): URL de retorno tras aprobar (opcional).
        cancel_url (str | None): URL de retorno si el usuario cancela (opcional).

    Returns:
        str: Identificador de la orden creada en PayPal (`order_id`).

    Raises:
        ValueError: Si `request_id` está vacío o el monto es inválido.
        PayPalError: Si PayPal rechaza la creación o no devuelve `id`.
    """
    if not request_id or not str(request_id).strip():
        raise ValueError("request_id es obligatorio para crear una orden en PayPal")

    monto_str = formatear_monto(monto)
    moneda_str = (moneda or getattr(Config, "PAYPAL_CURRENCY", "USD") or "USD").strip().upper()
    id_pedido_str = str(id_pedido)

    token = obtener_token()
    base_url = obtener_url_base()
    base_app_url = obtener_base_url_app()

    # Construimos las URLs de retorno/cancelación por defecto si no se especificaron
    url_retorno = return_url or f"{base_app_url}/pagos/paypal/{id_pedido_str}/retorno"
    url_cancelacion = cancel_url or f"{base_app_url}/pagos/paypal/{id_pedido_str}/cancelado"

    # Unidad de compra única vinculada al pedido mediante `custom_id` para validación posterior
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
                    "return_url": url_retorno,
                    "cancel_url": url_cancelacion,
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
        # Fallback: algunas cuentas/entornos rechazan `experience_context` (ej. localhost)
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
    Captura fondos de una orden aprobada en PayPal Orders v2
    (`POST {base}/v2/checkout/orders/{id}/capture`).

    Normaliza la respuesta extrayendo los campos clave desde
    `purchase_units[0].payments.captures[0]`.

    Args:
        order_id (str): Identificador de la orden en PayPal.
        request_id (str): Clave de idempotencia (`PayPal-Request-ID`).

    Returns:
        dict: Diccionario normalizado con `estado`, `capture_id`, `monto`,
            `moneda`, `custom_id` y opcionalmente `status_details` / `processor_response`.

    Raises:
        ValueError: Si `order_id` o `request_id` están vacíos.
        PayPalError: Si PayPal falla o la estructura de la captura es incompleta.
    """
    if not order_id or not str(order_id).strip():
        raise ValueError("order_id es obligatorio para capturar una orden")
    if not request_id or not str(request_id).strip():
        raise ValueError("request_id es obligatorio para capturar una orden")

    token = obtener_token()
    base_url = obtener_url_base()
    # Escapamos el ID para evitar inyección de ruta en la URL
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

    # Navegamos la estructura anidada estándar de Orders v2: purchase_units[0].payments.captures[0]
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
    # `custom_id` puede venir en la captura o en la unidad de compra padre
    custom_id = cap0.get("custom_id") if cap0.get("custom_id") is not None else pu0.get("custom_id")
    status_details = cap0.get("status_details") or data.get("status_details")
    processor_response = cap0.get("processor_response") or data.get("processor_response")

    res = {
        "estado": str(estado) if estado is not None else None,
        "capture_id": str(capture_id) if capture_id is not None else None,
        "monto": str(monto) if monto is not None else None,
        "moneda": str(moneda) if moneda is not None else None,
        "custom_id": str(custom_id) if custom_id is not None else None,
    }
    if status_details is not None:
        res["status_details"] = status_details
    if processor_response is not None:
        res["processor_response"] = processor_response

    return res


def reembolsar_captura(capture_id, request_id):
    """
    Reembolsa totalmente una captura en PayPal Payments v2
    (`POST {base}/v2/payments/captures/{capture_id}/refund`).

    Args:
        capture_id (str): Identificador de la captura a reembolsar.
        request_id (str): Clave de idempotencia (`PayPal-Request-ID`).

    Returns:
        dict: Diccionario con `estado` y `refund_id`.

    Raises:
        ValueError: Si `capture_id` o `request_id` están vacíos.
        PayPalError: Si PayPal rechaza el reembolso o no devuelve `id`.
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

    # Un cuerpo vacío `{}` indica a PayPal un reembolso total del monto capturado
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
