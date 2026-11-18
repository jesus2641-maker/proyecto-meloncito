# Punto de entrada para desplegar la aplicación Flask en Vercel (serverless).
import os
import sys

# Asegurar que la raíz del proyecto esté en el PYTHONPATH para importar app y config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app

# NOTA: Vercel busca una variable llamada `app` en este archivo para ejecutar las peticiones web.
app = create_app()
