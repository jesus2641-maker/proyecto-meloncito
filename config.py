"""
Configuración de la Aplicación Beer House
Maneja todas las variables de configuración y credenciales mediante variables de entorno.
"""

import os
import logging
from datetime import timedelta
from urllib.parse import urlparse, unquote
from dotenv import load_dotenv

# Cargar variables de entorno desde archivo .env (en local)
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


def resolver_db_config():
    """
    Resuelve la configuración de base de datos (TiDB Cloud / MySQL) desde variables de entorno:
      1. DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME (estándar principal)
      2. DATABASE_URL o MYSQL_URL (opcional)
      3. Respaldo compatible con DATABASE_* / MYSQL*
    """
    def env(*nombres, default=""):
        for n in nombres:
            v = os.getenv(n)
            if v not in (None, ""):
                return v
        return default

    # Si no se definieron variables DB_* directas pero sí DATABASE_URL
    if not os.getenv("DB_HOST"):
        url = os.getenv("DATABASE_URL") or os.getenv("MYSQL_URL")
        if url and url.startswith(("mysql://", "mysql+mysqlconnector://", "mysql+pymysql://")):
            p = urlparse(url)
            return {
                "host": p.hostname or "",
                "port": int(p.port or 4000),
                "user": unquote(p.username or ""),
                "password": unquote(p.password or ""),
                "database": (p.path or "/").lstrip("/"),
            }

    port_raw = env("DB_PORT", "DATABASE_PORT", "MYSQLPORT", default="3306")
    try:
        port = int(str(port_raw).strip())
    except (TypeError, ValueError):
        port = 3306

    return {
        "host": env("DB_HOST", "DATABASE_HOST", "MYSQLHOST", default="localhost"),
        "port": port,
        "user": env("DB_USER", "DATABASE_USER", "MYSQLUSER", default="root"),
        "password": env("DB_PASSWORD", "DATABASE_PASSWORD", "MYSQLPASSWORD", default=""),
        "database": env("DB_NAME", "DATABASE_NAME", "MYSQLDATABASE", default="beerhouse_db"),
    }


def _resolver_entero(nombre_env, default):
    valor = os.getenv(nombre_env, str(default))
    try:
        num = int(str(valor).strip())
        return num if num > 0 else default
    except (TypeError, ValueError):
        return default


class Config:
    """Clase de configuración principal de la aplicación Flask."""

    # Clave secreta para sesiones y CSRF (sin credenciales fijas en el código)
    SECRET_KEY = os.getenv("SECRET_KEY") or os.urandom(32).hex()
    if not os.getenv("SECRET_KEY"):
        logger.warning("SECRET_KEY no está definida en el entorno; se generó una clave efímera temporal.")

    # URL base de la aplicación (en local: http://localhost:5000, en Render: https://tu-app.onrender.com)
    BASE_URL = (os.getenv("BASE_URL") or "http://localhost:5000").strip().rstrip("/")

    # Flask-WTF CSRF Configuration
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None
    WTF_CSRF_SSL_STRICT = False
    TEMPLATES_AUTO_RELOAD = True

    # Session Configuration
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "").lower() in ("1", "true") or BASE_URL.startswith("https://")
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)

    # Database Configuration (TiDB Cloud / MySQL)
    _DB = resolver_db_config()
    DB_HOST = _DB["host"]
    DB_PORT = _DB["port"]
    DB_USER = _DB["user"]
    DB_PASSWORD = _DB["password"]
    DB_NAME = _DB["database"]
    DB_SSL_CA = (os.getenv("DB_SSL_CA") or "").strip() or None

    # Alias por compatibilidad interna
    DATABASE_HOST = DB_HOST
    DATABASE_PORT = DB_PORT
    DATABASE_USER = DB_USER
    DATABASE_PASSWORD = DB_PASSWORD
    DATABASE_NAME = DB_NAME

    # Cloudinary Configuration
    CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
    CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
    CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

    # Brevo Configuration
    BREVO_API_KEY = os.getenv("BREVO_API_KEY")
    BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL")
    BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME")

    # PayPal Configuration (Sandbox / Live)
    PAYPAL_CLIENT_ID = (os.getenv("PAYPAL_CLIENT_ID") or "").strip()
    PAYPAL_SECRET = (os.getenv("PAYPAL_SECRET") or os.getenv("PAYPAL_CLIENT_SECRET") or "").strip()
    PAYPAL_CLIENT_SECRET = PAYPAL_SECRET
    PAYPAL_MODE = resolver_paypal_mode()
    PAYPAL_CURRENCY = (os.getenv("PAYPAL_CURRENCY", "USD") or "USD").strip().upper() or "USD"
    PAYPAL_API_BASE = resolver_paypal_api_base(PAYPAL_MODE)
    PAGO_EXPIRA_MINUTOS = _resolver_entero("PAGO_EXPIRA_MINUTOS", 30)

    # Tasa de conversión: pesos colombianos (COP) por 1 dólar (USD)
    TASA_COP_USD = float(os.getenv("TASA_COP_USD", "0") or "0")

    @staticmethod
    def get_db_config():
        """
        Construye el diccionario de conexión para mysql-connector-python.
        Habilita TLS/SSL por defecto (ssl_disabled=False), requerido por TiDB Cloud.
        Si se define DB_SSL_CA, utiliza ese certificado CA.
        """
        db = resolver_db_config()
        cfg = {
            "host": db["host"],
            "port": db["port"],
            "user": db["user"],
            "password": db["password"],
            "database": db["database"],
            "connect_timeout": 10,
            "ssl_disabled": False,
        }

        ssl_ca = (os.getenv("DB_SSL_CA") or "").strip()
        if ssl_ca:
            cfg["ssl_ca"] = ssl_ca
            cfg["ssl_verify_cert"] = True

        if os.getenv("DB_SSL_DISABLED", os.getenv("DATABASE_SSL_DISABLED", "")).lower() in ("1", "true"):
            cfg["ssl_disabled"] = True

        return cfg
