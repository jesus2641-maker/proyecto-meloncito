from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from app.models.usuario import Usuario
from app.utils.validaciones import validar_email, validar_password, MIN_PASSWORD_LENGTH
from app.utils.email_service import send_welcome_email

# IDs de roles
ID_ROL_CLIENTE = 1
ID_ROL_ADMIN = 2
ID_ROL_TRABAJADOR = 4

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not validar_email(email):
            flash("Ingresa un correo electrónico válido", "danger")
            return render_template("auth/login.html")

        usuario = Usuario.obtener_por_email(email)

        if usuario and check_password_hash(usuario["password_hash"], password):
            session["id_usuario"] = usuario["id_usuario"]
            session["nombre"] = usuario["nombre"]
            session["id_rol"] = usuario["id_rol"]
            flash("Sesión iniciada correctamente", "success")
            
            # Redirigir según el rol
            if usuario["id_rol"] == ID_ROL_ADMIN:
                return redirect(url_for("admin.dashboard"))
            elif usuario["id_rol"] == ID_ROL_TRABAJADOR:
                return redirect(url_for("trabajador.dashboard"))
            else:  # Cliente
                return redirect(url_for("productos.catalogo"))

        flash("Correo o contraseña incorrectos", "danger")

    return render_template("auth/login.html")


@auth_bp.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        apellido = request.form.get("apellido", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        telefono = request.form.get("telefono", "").strip() or None

        if not nombre or not apellido:
            flash("El nombre y apellido son obligatorios", "danger")
            return render_template("auth/registro.html")

        if not validar_email(email):
            flash("Ingresa un correo electrónico válido (ej. usuario@dominio.com)", "danger")
            return render_template("auth/registro.html")

        password_valida, mensaje_password = validar_password(password)
        if not password_valida:
            flash(mensaje_password, "danger")
            return render_template("auth/registro.html")

        if Usuario.obtener_por_email(email):
            flash("Ese correo ya está registrado", "warning")
            return render_template("auth/registro.html")

        password_hash = generate_password_hash(password)
        Usuario.crear(nombre, apellido, email, password_hash, telefono)

        # Enviar correo de bienvenida (no debe fallar el registro si falla el correo)
        try:
            send_welcome_email(email, nombre)
        except Exception as e:
            print(f"Error al enviar correo de bienvenida: {e}")

        flash("Cuenta creada, ya puedes iniciar sesión", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/registro.html", min_password=MIN_PASSWORD_LENGTH)


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
