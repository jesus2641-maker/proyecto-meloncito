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

    # CSRF Protection - Protege contra ataques Cross-Site Request Forgery
    csrf = CSRFProtect(app)

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
        if request.endpoint == "static" or request.blueprint in ("edad", "auth", "api"):
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
        if session.get('id_usuario'):
            cart_count = CarritoItem.contar_items(session['id_usuario'])
        return {'cart_count': cart_count}

    # Ruta principal - Página de inicio
    @app.route("/")
    def inicio():
        """
        Página de inicio con categorías y productos destacados.
        Muestra las primeras 4 categorías y 3 productos destacados con sus variantes.
        """
        from app.models.categoria import Categoria
        from app.models.producto import Producto
        categorias = Categoria.listar()

        # Obtener productos con todas sus variantes
        filas = Producto.listar_con_variantes()

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
        return render_template("errors/500.html"), 500

    return app
