"""
Beer House Premium Spirits - Aplicación Flask Principal
Este archivo configura la aplicación Flask, registra los blueprints y define las rutas globales.
"""

from flask import Flask, redirect, url_for, render_template, session, g, request
from flask_wtf.csrf import CSRFProtect
from config import Config

def create_app():
    """
    Factory pattern para crear la aplicación Flask.
    Permite múltiples instancias con diferentes configuraciones.
    """
    app = Flask(__name__)
    app.config.from_object(Config)

    # Detrás del proxy de Railway (o cualquier PaaS) la petición llega por HTTP
    # interno; ProxyFix lee X-Forwarded-* para que Flask sepa que el cliente
    # usó HTTPS y el host real (necesario para url_for externos y cookies Secure).
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # CSRF Protection - Protege contra ataques Cross-Site Request Forgery
    csrf = CSRFProtect(app)

    # Log temporal al iniciar la app: Conectado a BD: <nombre> usando SELECT DATABASE()
    from app.utils.db import get_connection
    import logging
    import os
    from datetime import datetime
    _init_logger = logging.getLogger(__name__)
    try:
        _conn = get_connection()
        _cur = _conn.cursor()
        _cur.execute("SELECT DATABASE()")
        _row = _cur.fetchone()
        _db_nombre = _row[0] if _row else None
        _init_logger.info("Conectado a BD: %s", _db_nombre)
        print(f"[STARTUP] Conectado a BD: {_db_nombre}")
        _cur.close()
        _conn.close()
    except Exception as _e:
        _init_logger.warning("No se pudo obtener el nombre de la BD: %s", _e)
        print(f"[STARTUP] No se pudo obtener el nombre de la BD: {_e}")

    # Diagnóstico: Confirmar ruta absoluta y fecha de modificación de app/routes/productos.py
    _ruta_productos = os.path.abspath(os.path.join(app.root_path, "routes", "productos.py"))
    if os.path.exists(_ruta_productos):
        _mtime = datetime.fromtimestamp(os.path.getmtime(_ruta_productos)).strftime('%Y-%m-%d %H:%M:%S')
        _init_logger.info("Ruta app/routes/productos.py: %s | Modificado: %s", _ruta_productos, _mtime)
        print(f"[STARTUP] Archivo: {_ruta_productos} | Modificado: {_mtime}")
    else:
        _init_logger.warning("No se encontró el archivo: %s", _ruta_productos)
        print(f"[STARTUP] No se encontró el archivo: {_ruta_productos}")

    # Importar y registrar blueprints (módulos de rutas organizados por funcionalidad)
    from app.routes.auth import auth_bp          # Autenticación y registro
    from app.routes.productos import productos_bp  # Catálogo de productos
    from app.routes.carrito import carrito_bp      # Carrito de compras
    from app.routes.admin import admin_bp          # Panel de administración
    from app.routes.cuenta import cuenta_bp        # Cuenta de usuario
    from app.routes.trabajador import trabajador_bp # Panel de trabajador
    from app.routes.categorias import categorias_bp # Gestión de categorías
    from app.routes.api import api_bp              # API endpoints
    from app.routes.edad import edad_bp, COOKIE_MAYOR_EDAD  # Verificación de mayoría de edad
    from app.routes.pagos import pagos_bp          # Pagos con PayPal
    from app.routes.paypal import paypal_bp        # PayPal Orders v2 Sandbox

    # Registrar blueprints con sus prefijos de URL
    app.register_blueprint(auth_bp)
    app.register_blueprint(productos_bp)
    app.register_blueprint(carrito_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(cuenta_bp)
    app.register_blueprint(trabajador_bp)
    app.register_blueprint(categorias_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(edad_bp)
    app.register_blueprint(pagos_bp)
    app.register_blueprint(paypal_bp)

    # Verificación de mayoría de edad (18+) para visitantes
    @app.before_request
    def exigir_mayoria_de_edad():
        """
        Redirige a /verificar-edad a quien no ha confirmado ser mayor de edad.
        No aplica a: quien ya tiene la cookie, personal (admin/trabajador),
        rutas inexistentes, archivos estáticos ni los blueprints edad, auth y api.
        """
        from app.utils.decoradores import ID_ROL_ADMIN, ID_ROL_TRABAJADOR

        if request.cookies.get(COOKIE_MAYOR_EDAD) == "1":
            return None
        if session.get("id_rol") in (ID_ROL_ADMIN, ID_ROL_TRABAJADOR):
            return None
        if request.endpoint is None:
            return None
        if request.endpoint in ("static", "health") or request.blueprint in ("edad", "auth", "api"):
            return None

        # En GET se vuelve a la página pedida; en POST no se puede repetir la
        # petición, así que se vuelve al inicio (no se pierde ningún dato guardado).
        destino = request.full_path.rstrip("?") if request.method == "GET" else "/"
        return redirect(url_for("edad.verificar_edad", next=destino))

    # Context processor para inyectar el contador del carrito en todas las plantillas
    @app.context_processor
    def inject_cart_count():
        """
        Inyecta el contador de items del carrito en todas las plantillas.
        Permite mostrar el número de productos en el icono del carrito del header.
        """
        from app.models.carrito import CarritoItem
        cart_count = 0
        try:
            if session.get('id_usuario'):
                cart_count = CarritoItem.contar_items(session['id_usuario'])
        except Exception:
            cart_count = 0
        return {'cart_count': cart_count}

    # Healthcheck para Railway/Vercel: responde 200 si la app y la BD están vivas.
    @app.route("/health")
    def health():
        from app.utils.db import get_connection
        try:
            conn = get_connection()
            conn.close()
            return {"status": "ok", "db": "ok"}, 200
        except Exception as e:
            return {"status": "degraded", "db": "unreachable", "error": str(e)}, 200

    # Ruta principal - Página de inicio
    @app.route("/")
    def inicio():
        """
        Página de inicio con categorías y productos destacados.
        Muestra las primeras 4 categorías y 3 productos destacados con sus variantes.
        """
        from app.models.categoria import Categoria
        from app.models.producto import Producto
        import logging
        _log = logging.getLogger(__name__)

        try:
            categorias = Categoria.listar()
            filas = Producto.listar_con_variantes()
        except Exception as e:
            _log.error("Error al consultar la BD en la página de inicio: %s", e)
            categorias = []
            filas = []

        # Agrupar variantes por producto y calcular el precio mínimo
        productos_destacados = {}
        for fila in filas:
            id_producto = fila["id_producto"]
            if id_producto not in productos_destacados:
                productos_destacados[id_producto] = {
                    "id_producto": id_producto,
                    "nombre_producto": fila["nombre_producto"],
                    "descripcion": fila["descripcion"],
                    "marca": fila["marca"],
                    "imagen_url": fila["imagen_url"],
                    "categorias": fila.get("categorias", ""),
                    "precio_minimo": fila["precio"]
                }
            else:
                # Actualizar precio mínimo si encontramos una variante más barata
                if fila["precio"] < productos_destacados[id_producto]["precio_minimo"]:
                    productos_destacados[id_producto]["precio_minimo"] = fila["precio"]

        # Convertir a lista y limitar a 3 productos destacados
        productos_destacados = list(productos_destacados.values())[:3]

        return render_template("home.html", categorias=categorias, productos_destacados=productos_destacados)

    # Ruta de ofertas - Muestra promociones activas
    @app.route("/ofertas")
    def ofertas():
        """
        Página de ofertas con todas las promociones activas.
        Filtra ofertas que están activas y dentro del rango de fechas válido.
        """
        from app.models.oferta import Oferta
        ofertas = Oferta.listar_activas()
        return render_template("ofertas.html", ofertas=ofertas)

    # Ruta "Nosotros" - Página informativa sobre la empresa
    @app.route("/nosotros")
    def nosotros():
        """Página de información sobre la empresa y su historia."""
        return render_template("nosotros.html")

    # Manejador de errores 404 - Página no encontrada
    @app.errorhandler(404)
    def pagina_no_encontrada(error):
        """Muestra página personalizada cuando el recurso no existe."""
        return render_template("errors/404.html"), 404

    # Manejador de errores 500 - Error interno del servidor
    @app.errorhandler(500)
    def error_interno(error):
        """Muestra página personalizada para errores del servidor."""
        import logging
        logging.getLogger(__name__).exception("Error 500 en Flask: %s", error)
        try:
            return render_template("errors/500.html"), 500
        except Exception:
            return "<h1>500 Internal Server Error</h1><p>Error interno del servidor. Revisa los logs en el dashboard de Vercel.</p>", 500

    return app
