"""
Configuración de la Aplicación Beer House
Este archivo maneja todas las variables de configuración y credenciales.
Las variables sensibles se cargan desde el archivo .env para seguridad.
"""

import os
import logging
from datetime import timedelta
from dotenv import load_dotenv, find_dotenv

# Cargar variables de entorno desde archivo .env
load_dotenv()

# Configurar logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def resolver_paypal_mode(modo=None):
    """Normaliza PAYPAL_MODE: solo 'live' si se escribe explícitamente, en otro caso 'sandbox'."""
    valor = modo if modo is not None else os.getenv("PAYPAL_MODE", "sandbox")
    return "live" if str(valor or "").strip().lower() == "live" else "sandbox"


def resolver_paypal_api_base(modo=None, api_base=None):
    """
    Devuelve la URL base de la API de PayPal según PAYPAL_MODE,
    permitiendo sobreescribirla explícitamente con PAYPAL_API_BASE.
    """
    override = api_base if api_base is not None else os.getenv("PAYPAL_API_BASE", "")
    if override and str(override).strip():
        return str(override).strip().rstrip("/")
    modo_efectivo = resolver_paypal_mode(modo)
    if modo_efectivo == "live":
        return "https://api-m.paypal.com"
    return "https://api-m.sandbox.paypal.com"


def _resolver_entero(nombre_env, default):
    valor = os.getenv(nombre_env, str(default))
    try:
        num = int(str(valor).strip())
        return num if num > 0 else default
    except (TypeError, ValueError):
        return default


class Config:
    """Clase de configuración principal de la aplicación Flask."""

    # Clave secreta para sesiones y CSRF
    SECRET_KEY = os.getenv("SECRET_KEY")
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY no está configurada en el entorno. Configúrala en el archivo .env.")
    if len(SECRET_KEY) < 32:
        logger.warning("SECRET_KEY tiene menos de 32 caracteres. Se recomienda usar una clave más larga para mayor seguridad.")

    # Flask-WTF CSRF Configuration - Protección contra ataques CSRF
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None
    WTF_CSRF_SSL_STRICT = False
    TEMPLATES_AUTO_RELOAD = True

    # Session Configuration
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "").lower() in ("1", "true")
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)

    # Database Configuration - Credenciales MySQL
    DATABASE_HOST = os.getenv("DATABASE_HOST", "localhost")
    DATABASE_USER = os.getenv("DATABASE_USER", "root")
    DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD", "")
    DATABASE_NAME = os.getenv("DATABASE_NAME", "beerhouse_db")

    # Cloudinary Configuration - Servicio de almacenamiento de imágenes
    CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
    CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
    CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

    # Brevo Configuration - Servicio de envío de emails
    BREVO_API_KEY = os.getenv("BREVO_API_KEY")
    BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL")
    BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME")

    # PayPal Configuration - Pasarela de pagos (Orders v2 / Payments v2)
    PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "") or ""
    PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "") or ""
    PAYPAL_MODE = resolver_paypal_mode()
    PAYPAL_CURRENCY = (os.getenv("PAYPAL_CURRENCY", "USD") or "USD").strip().upper() or "USD"
    PAYPAL_API_BASE = resolver_paypal_api_base(PAYPAL_MODE)
    PAGO_EXPIRA_MINUTOS = _resolver_entero("PAGO_EXPIRA_MINUTOS", 30)

    # Tasa de conversión: pesos colombianos (COP) por 1 dólar (USD).
    # Si vale 0 o falta, el cálculo de un pago debe fallar con un error claro.
    TASA_COP_USD = float(os.getenv("TASA_COP_USD", "0"))

    @staticmethod
    def get_db_config():
        return {
            "host": Config.DATABASE_HOST,
            "user": Config.DATABASE_USER,
            "password": Config.DATABASE_PASSWORD,
            "database": Config.DATABASE_NAME
        }
