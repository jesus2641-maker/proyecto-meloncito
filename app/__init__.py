"""
Beer House Premium Spirits — Aplicación Flask Principal.

Este archivo implementa el patrón Application Factory (`create_app`) que:
1. Instancia y configura la aplicación Flask a partir de `config.Config`.
2. Aplica middleware `ProxyFix` para despliegues detrás de proxy inverso (Render/PaaS).
3. Habilita protección global contra CSRF (`CSRFProtect`).
4. Registra el cierre automático de conexiones de base de datos (`init_db_app`).
5. Registra todos los blueprints modulares del sitio.
6. Define hooks globales (`before_request` para mayoría de edad, `context_processor`
   para contador del carrito), rutas raíz (`/`, `/ofertas`, `/nosotros`, `/health`)
   y manejadores personalizados de errores HTTP (404 y 500).
"""

from flask import Flask, redirect, url_for, render_template, session, g, request
from flask_wtf.csrf import CSRFProtect
from config import Config
from app.utils.db import init_db_app


def create_app():
    """
    Factory pattern para crear y configurar una instancia de la aplicación Flask.

    Permite instanciar múltiples aplicaciones aisladas con diferentes
    configuraciones (por ejemplo, producción, desarrollo o pruebas automatizadas).

    Returns:
        flask.Flask: Instancia completamente configurada y lista para servir peticiones.
    """
    # Creamos la instancia base de Flask usando el paquete actual (`app`) como raíz
    app = Flask(__name__)
    # Cargamos las variables y parámetros de configuración definidos en `config.Config`
    app.config.from_object(Config)

    # Detrás del proxy de Render (o cualquier PaaS) la petición llega por HTTP
    # interno; ProxyFix lee X-Forwarded-* para que Flask sepa que el cliente
    # usó HTTPS y el host real (necesario para url_for externos y cookies Secure).
    # NOTA: Si se quita ProxyFix en producción, las cookies de sesión y los links de PayPal pueden fallar.
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # CSRF Protection - Protege formularios y endpoints POST contra ataques Cross-Site Request Forgery
    # NOTA: Todas las peticiones POST (formularios y fetch/AJAX) deben enviar el token CSRF o Flask las rechaza.
    CSRFProtect(app)

    # Registrar cierre automático de la conexión de BD al finalizar cada petición (teardown_appcontext)
    # NOTA: Depende de app/utils/db.py para cerrar la conexión guardada en `g` y no dejar conexiones abiertas.
    init_db_app(app)

    # Importar blueprints (módulos de rutas organizados por dominio funcional)
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

    # Registrar cada blueprint en la aplicación con sus respectivos prefijos de URL
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

    # Hook global ejecutado antes de cada petición para exigir verificación de edad (18+)
    @app.before_request
    def exigir_mayoria_de_edad():
        """
        Redirige a `/verificar-edad` a quien no ha confirmado ser mayor de edad.

        Excepciones (permite el paso sin redirigir):
        - Visitantes que ya poseen la cookie `COOKIE_MAYOR_EDAD == "1"`.
        - Personal autenticado con rol de Administrador o Trabajador.
        - Rutas inexistentes (`request.endpoint is None`, para que responda 404).
        - Archivos estáticos, healthcheck (`/health`) y blueprints `edad`, `auth` y `api`.

        Returns:
            werkzeug.wrappers.Response | None: Redirección a la verificación de edad
                si aplica, o `None` para continuar con la petición normal.
        """
        from app.utils.decoradores import ID_ROL_ADMIN, ID_ROL_TRABAJADOR

        # 1. Si el navegador ya tiene la cookie de confirmación de edad, permitimos el acceso
        if request.cookies.get(COOKIE_MAYOR_EDAD) == "1":
            return None
        # 2. El personal interno (admin/trabajador) no requiere pasar por el filtro de visitante
        if session.get("id_rol") in (ID_ROL_ADMIN, ID_ROL_TRABAJADOR):
            return None
        # 3. Si la URL no coincide con ninguna ruta, dejamos que Flask dispare el error 404
        if request.endpoint is None:
            return None
        # 4. Excluimos recursos estáticos, monitoreo y los flujos de edad/login/API
        if request.endpoint in ("static", "health") or request.blueprint in ("edad", "auth", "api"):
            return None

        # En GET se vuelve a la página pedida; en POST no se puede repetir la
        # petición, así que se vuelve al inicio (no se pierde ningún dato guardado).
        destino = request.full_path.rstrip("?") if request.method == "GET" else "/"
        return redirect(url_for("edad.verificar_edad", next=destino))

    # Context processor para inyectar el contador del carrito en todas las plantillas Jinja2
    @app.context_processor
    def inject_cart_count():
        """
        Inyecta la variable `cart_count` en el contexto global de todas las plantillas.

        Permite mostrar la cantidad de unidades en el icono del carrito del encabezado
        sin tener que consultarlo manualmente en cada ruta. Si ocurre un error de BD,
        degrada silenciosamente a `0` para no romper el renderizado de la página.

        Returns:
            dict: Diccionario `{'cart_count': int}` disponible en todas las vistas HTML.
        """
        from app.models.carrito import CarritoItem
        cart_count = 0
        try:
            # Solo consultamos el carrito si hay un usuario autenticado en sesión
            if session.get('id_usuario'):
                cart_count = CarritoItem.contar_items(session['id_usuario'])
        except Exception:
            # Ante cualquier fallo de conexión o consulta, mostramos 0 en el header
            cart_count = 0
        return {'cart_count': cart_count}

    # Healthcheck para Render / balanceadores de carga: responde 200 verificando BD
    @app.route("/health")
    def health():
        """
        Endpoint de verificación de salud (healthcheck) para infraestructura PaaS.

        Intenta abrir y cerrar una conexión a la base de datos e informa el estado
        en formato JSON sin exponer credenciales.

        Returns:
            tuple[dict, int]: JSON con `status` y `db`, junto con código HTTP 200.
        """
        from app.utils.db import get_connection
        try:
            conn = get_connection()
            conn.close()
            return {"status": "ok", "db": "ok"}, 200
        except Exception as e:
            return {"status": "degraded", "db": "unreachable", "error": str(e)}, 200

    # Ruta principal - Página de inicio de la tienda
    @app.route("/")
    def inicio():
        """
        Página de inicio con categorías y productos destacados.

        Consulta las categorías disponibles y las variantes activas de productos,
        agrupa las variantes por producto para calcular el precio mínimo de cada uno
        y selecciona hasta 3 productos destacados para renderizar `home.html`.

        Returns:
            str: HTML renderizado de la plantilla `home.html`.
        """
        from app.models.categoria import Categoria
        from app.models.producto import Producto
        import logging
        _log = logging.getLogger(__name__)

        # Consultamos categorías y productos con sus variantes; si la BD falla, degradamos a listas vacías
        try:
            categorias = Categoria.listar()
            filas = Producto.listar_con_variantes()
        except Exception as e:
            _log.error("Error al consultar la BD en la página de inicio: %s", e)
            categorias = []
            filas = []

        # Agrupar variantes por producto y calcular el precio mínimo de presentación
        productos_destacados = {}
        for fila in filas:
            id_producto = fila["id_producto"]
            if id_producto not in productos_destacados:
                # Primera variante vista para este producto: inicializamos su ficha resumen
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

        # Convertir a lista y limitar a los primeros 3 productos destacados
        productos_destacados = list(productos_destacados.values())[:3]

        return render_template("home.html", categorias=categorias, productos_destacados=productos_destacados)

    # Ruta de ofertas - Muestra promociones activas
    @app.route("/ofertas")
    def ofertas():
        """
        Página de ofertas con todas las promociones activas.

        Filtra en el modelo `Oferta` aquellas promociones marcadas como activas
        y vigentes dentro del rango de fechas actual.

        Returns:
            str: HTML renderizado de la plantilla `ofertas.html`.
        """
        from app.models.oferta import Oferta
        ofertas = Oferta.listar_activas()
        return render_template("ofertas.html", ofertas=ofertas)

    # Ruta "Nosotros" - Página informativa sobre la empresa
    @app.route("/nosotros")
    def nosotros():
        """
        Página estática de información sobre la empresa Beer House y su historia.

        Returns:
            str: HTML renderizado de la plantilla `nosotros.html`.
        """
        return render_template("nosotros.html")

    # Manejador global de errores 404 - Recurso no encontrado
    @app.errorhandler(404)
    def pagina_no_encontrada(error):
        """
        Muestra una página 404 personalizada cuando la ruta solicitada no existe.

        Args:
            error (werkzeug.exceptions.NotFound): Excepción HTTP 404 capturada por Flask.

        Returns:
            tuple[str, int]: Plantilla `errors/404.html` y código de estado 404.
        """
        return render_template("errors/404.html"), 404

    # Manejador global de errores 500 - Error interno del servidor
    @app.errorhandler(500)
    def error_interno(error):
        """
        Registra la excepción y muestra una página 500 personalizada ante fallos internos.

        Si el renderizado de la plantilla `errors/500.html` también falla (por ejemplo,
        si el context processor o la BD están caídos), devuelve un HTML mínimo de respaldo.

        Args:
            error (Exception): Excepción no controlada ocurrida durante la petición.

        Returns:
            tuple[str, int]: HTML de error y código de estado 500.
        """
        import logging
        logging.getLogger(__name__).exception("Error 500 en Flask: %s", error)
        try:
            return render_template("errors/500.html"), 500
        except Exception:
            return "<h1>500 Internal Server Error</h1><p>Error interno del servidor. Revisa los logs del servidor.</p>", 500

    return app
