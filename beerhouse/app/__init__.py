from flask import Flask, redirect, url_for, render_template
from config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    from app.routes.auth import auth_bp
    from app.routes.productos import productos_bp
    from app.routes.carrito import carrito_bp
    from app.routes.admin import admin_bp
    from app.routes.cuenta import cuenta_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(productos_bp)
    app.register_blueprint(carrito_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(cuenta_bp)

    @app.route("/")
    def inicio():
        return redirect(url_for("productos.catalogo"))

    @app.errorhandler(404)
    def pagina_no_encontrada(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def error_interno(error):
        return render_template("errors/500.html"), 500

    return app