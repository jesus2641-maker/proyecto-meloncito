# Archivo principal para arrancar el servidor de desarrollo de Flask en local.
import os
from app import create_app

if __name__ == "__main__":
    # Se crea la aplicación usando el patrón factory definido en app/__init__.py
    app = create_app()
    # Se toma el puerto de la variable de entorno PORT (útil en la nube) o 5000 por defecto
    port = int(os.getenv("PORT", 5000))
    # Solo se activa el modo debug si FLASK_DEBUG está en "1" o "true"
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true")
    # host="0.0.0.0" permite que el servidor acepte conexiones desde fuera de localhost (ej. Docker)
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
