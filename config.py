"""
Configuración de la Aplicación Beer House
Este archivo maneja todas las variables de configuración y credenciales.
Las variables sensibles se cargan desde el archivo .env para seguridad.
"""

import os
from dotenv import load_dotenv, find_dotenv

# Cargar variables de entorno desde archivo .env
load_dotenv()

class Config:
    """Clase de configuración principal de la aplicación Flask."""

    # Clave secreta para sesiones y CSRF
    SECRET_KEY = os.getenv("SECRET_KEY", "dev")

    # Flask-WTF CSRF Configuration - Protección contra ataques CSRF
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None
    WTF_CSRF_SSL_STRICT = False

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

    @staticmethod
    def get_db_config():
        return {
            "host": Config.DATABASE_HOST,
            "user": Config.DATABASE_USER,
            "password": Config.DATABASE_PASSWORD,
            "database": Config.DATABASE_NAME
        }
