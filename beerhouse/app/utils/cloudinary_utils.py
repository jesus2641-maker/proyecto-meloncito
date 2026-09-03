"""
Utilidades para Cloudinary - Subida y eliminación de imágenes
"""
import os
import cloudinary
import cloudinary.uploader
from config import Config


def configure_cloudinary():
    """Configura Cloudinary con las credenciales del entorno"""
    cloudinary.config(
        cloud_name=Config.CLOUDINARY_CLOUD_NAME,
        api_key=Config.CLOUDINARY_API_KEY,
        api_secret=Config.CLOUDINARY_API_SECRET
    )


def upload_image(file, folder="beerhouse"):
    """
    Sube una imagen a Cloudinary
    
    Args:
        file: Objeto FileStorage de Flask
        folder: Carpeta en Cloudinary para organizar las imágenes
        
    Returns:
        dict: Con 'secure_url' y 'public_id' de la imagen subida
        None: Si la subida falla
    """
    try:
        # Verificar que las credenciales estén configuradas
        if not Config.CLOUDINARY_CLOUD_NAME or not Config.CLOUDINARY_API_KEY or not Config.CLOUDINARY_API_SECRET:
            print("Error: Credenciales de Cloudinary no configuradas en .env")
            return None
            
        configure_cloudinary()
        
        # Validar que sea una imagen
        if not file or not hasattr(file, 'filename') or not file.filename:
            return None
            
        # Validar extensión del archivo
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        
        if file_ext not in allowed_extensions:
            print(f"Error: Extension de archivo no permitida: {file_ext}")
            return None
        
        # Subir imagen a Cloudinary
        result = cloudinary.uploader.upload(
            file,
            folder=folder,
            allowed_formats=['png', 'jpg', 'jpeg', 'gif', 'webp'],
            resource_type='image'
        )
        
        return {
            'secure_url': result.get('secure_url'),
            'public_id': result.get('public_id')
        }
        
    except Exception as e:
        print(f"Error al subir imagen a Cloudinary: {e}")
        return None


def delete_image(public_id):
    """
    Elimina una imagen de Cloudinary usando su public_id
    
    Args:
        public_id: ID público de la imagen en Cloudinary
        
    Returns:
        bool: True si se eliminó correctamente, False en caso contrario
    """
    try:
        configure_cloudinary()
        
        if not public_id:
            return False
            
        result = cloudinary.uploader.destroy(public_id, resource_type='image')
        return result.get('result') == 'ok'
        
    except Exception as e:
        print(f"Error al eliminar imagen de Cloudinary: {e}")
        return False
