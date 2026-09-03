from flask import Flask, redirect, url_for, render_template, session, g
from flask_wtf.csrf import CSRFProtect
from config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # CSRF Protection
    csrf = CSRFProtect(app)

    from app.routes.auth import auth_bp
    from app.routes.productos import productos_bp
    from app.routes.carrito import carrito_bp
    from app.routes.admin import admin_bp
    from app.routes.cuenta import cuenta_bp
    from app.routes.trabajador import trabajador_bp
    from app.routes.categorias import categorias_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(productos_bp)
    app.register_blueprint(carrito_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(cuenta_bp)
    app.register_blueprint(trabajador_bp)
    app.register_blueprint(categorias_bp)

    # Context processor para el contador del carrito
    @app.context_processor
    def inject_cart_count():
        from app.models.carrito import CarritoItem
        cart_count = 0
        if session.get('id_usuario'):
            cart_count = CarritoItem.contar_items(session['id_usuario'])
        return {'cart_count': cart_count}

    @app.route("/")
    def inicio():
        from app.models.categoria import Categoria
        from app.models.producto import Producto
        categorias = Categoria.listar()
        
        # Obtener productos con variantes
        filas = Producto.listar_con_variantes()
        
        # Agrupar por producto y obtener el precio mínimo
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
                    "precio_minimo": fila["precio"]
                }
            else:
                # Actualizar precio mínimo si es menor
                if fila["precio"] < productos_destacados[id_producto]["precio_minimo"]:
                    productos_destacados[id_producto]["precio_minimo"] = fila["precio"]
        
        # Convertir a lista y tomar máximo 3
        productos_destacados = list(productos_destacados.values())[:3]
        
        return render_template("home.html", categorias=categorias, productos_destacados=productos_destacados)
    
    @app.route("/ofertas")
    def ofertas():
        from app.models.oferta import Oferta
        ofertas = Oferta.listar_activas()
        return render_template("ofertas.html", ofertas=ofertas)
    
    @app.route("/nosotros")
    def nosotros():
        return render_template("nosotros.html")

    @app.errorhandler(404)
    def pagina_no_encontrada(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def error_interno(error):
        return render_template("errors/500.html"), 500

    return app
