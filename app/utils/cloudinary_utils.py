"""
Utilidades para Cloudinary — Subida y eliminación de imágenes de productos y categorías.

Centraliza la configuración del SDK de Cloudinary a partir de `Config` y ofrece
funciones seguras que validan credenciales, extensiones permitidas y capturan
excepciones para no interrumpir el flujo de la aplicación web.
"""
import logging
import os
import cloudinary
import cloudinary.uploader
from config import Config

# Logger del módulo para registrar advertencias de configuración y errores de red/SDK
logger = logging.getLogger(__name__)


def configure_cloudinary():
    """
    Configura el SDK global de Cloudinary con las credenciales del entorno.

    Lee `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY` y `CLOUDINARY_API_SECRET`
    desde la clase `Config`. Debe invocarse antes de realizar operaciones con
    `cloudinary.uploader`.
    """
    cloudinary.config(
        cloud_name=Config.CLOUDINARY_CLOUD_NAME,
        api_key=Config.CLOUDINARY_API_KEY,
        api_secret=Config.CLOUDINARY_API_SECRET
    )


def upload_image(file, folder="beerhouse"):
    """
    Sube una imagen a Cloudinary validando previamente credenciales y extensión.

    Args:
        file (werkzeug.datastructures.FileStorage): Objeto archivo recibido desde
            un formulario Flask (`request.files[...]`).
        folder (str): Carpeta destino en Cloudinary para organizar los recursos
            (por defecto `"beerhouse"`).

    Returns:
        dict | None: Diccionario con `'secure_url'` (URL HTTPS pública) y
            `'public_id'` (identificador para futuras eliminaciones), o `None` si
            faltan credenciales, el archivo es inválido o falla la subida.
    """
    try:
        # Verificar que las tres credenciales obligatorias estén definidas en la configuración
        if not Config.CLOUDINARY_CLOUD_NAME or not Config.CLOUDINARY_API_KEY or not Config.CLOUDINARY_API_SECRET:
            logger.warning("Credenciales de Cloudinary no configuradas en .env")
            return None
            
        # Inicializamos la configuración del SDK con las credenciales vigentes
        configure_cloudinary()
        
        # Validar que el objeto recibido sea un archivo válido con nombre no vacío
        if not file or not hasattr(file, 'filename') or not file.filename:
            return None
            
        # Lista blanca de extensiones de imagen permitidas para evitar subida de archivos arbitrarios
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        # Extraemos la extensión después del último punto en minúsculas
        file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        
        if file_ext not in allowed_extensions:
            logger.warning("Extensión de archivo no permitida: %s", file_ext)
            return None
        
        # Subir imagen a Cloudinary restringiendo también los formatos aceptados en el servidor remoto
        result = cloudinary.uploader.upload(
            file,
            folder=folder,
            allowed_formats=['png', 'jpg', 'jpeg', 'gif', 'webp'],
            resource_type='image'
        )
        
        # Devolvemos únicamente los campos necesarios para persistir en la BD
        return {
            'secure_url': result.get('secure_url'),
            'public_id': result.get('public_id')
        }
        
    except Exception:
        # Registramos la traza completa ante cualquier fallo de red, cuota o SDK
        logger.exception("Error al subir imagen a Cloudinary")
        return None


def delete_image(public_id):
    """
    Elimina una imagen almacenada en Cloudinary usando su `public_id`.

    Args:
        public_id (str): Identificador público único asignado por Cloudinary
            al momento de la subida.

    Returns:
        bool: `True` si Cloudinary confirmó la eliminación (`result == 'ok'`),
            `False` si el ID está vacío, no existe o ocurrió un error.
    """
    try:
        # Aseguramos que el SDK esté configurado antes de llamar a `destroy`
        configure_cloudinary()
        
        if not public_id:
            return False
            
        # Solicitamos la destrucción del recurso de tipo imagen en Cloudinary
        result = cloudinary.uploader.destroy(public_id, resource_type='image')
        return result.get('result') == 'ok'
        
    except Exception:
        logger.exception("Error al eliminar imagen de Cloudinary")
        return False
