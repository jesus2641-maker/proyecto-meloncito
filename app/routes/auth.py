from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from app.models.usuario import Usuario
from app.utils.validaciones import (
    validar_email, validar_password, MIN_PASSWORD_LENGTH,
    validar_fecha_nacimiento, fecha_maxima_nacimiento
)
from app.utils.email_service import send_welcome_email
from app.utils.login_attempts import check_login_attempt, record_failed_attempt, reset_login_attempts, get_remaining_time
from app.routes.edad import marcar_mayor_edad

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
        ip = request.remote_addr

        if not validar_email(email):
            flash("Ingresa un correo electrónico válido", "danger")
            return render_template("auth/login.html")

        # Verificar límite de intentos
        if not check_login_attempt(ip, email):
            remaining_time = get_remaining_time(ip, email)
            flash(f"Demasiados intentos. Intenta de nuevo en {remaining_time // 60} minutos.", "danger")
            return render_template("auth/login.html")

        usuario = Usuario.obtener_por_email(email)

        if usuario and check_password_hash(usuario["password_hash"], password):
            # Login exitoso: limpiar sesión, reiniciar intentos y configurar sesión permanente
            session.clear()
            session.permanent = True
            session["id_usuario"] = usuario["id_usuario"]
            session["nombre"] = usuario["nombre"]
            session["id_rol"] = usuario["id_rol"]
            reset_login_attempts(ip, email)
            flash("Sesión iniciada correctamente", "success")

            # Redirigir según el rol
            if usuario["id_rol"] == ID_ROL_ADMIN:
                return redirect(url_for("admin.dashboard"))
            elif usuario["id_rol"] == ID_ROL_TRABAJADOR:
                return redirect(url_for("trabajador.dashboard"))
            else:  # Cliente
                return redirect(url_for("productos.catalogo"))

        # Login fallido: registrar intento
        record_failed_attempt(ip, email)
        flash("Correo o contraseña incorrectos", "danger")

    return render_template("auth/login.html")


@auth_bp.route("/registro", methods=["GET", "POST"])
def registro():
    # Fecha de nacimiento más reciente permitida (hoy menos 18 años) para el input date
    fecha_max = fecha_maxima_nacimiento()

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        apellido = request.form.get("apellido", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        telefono = request.form.get("telefono", "").strip() or None
        fecha_nacimiento_texto = request.form.get("fecha_nacimiento", "")

        if not nombre or not apellido:
            flash("El nombre y apellido son obligatorios", "danger")
            return render_template("auth/registro.html", min_password=MIN_PASSWORD_LENGTH, fecha_max=fecha_max)

        if not validar_email(email):
            flash("Ingresa un correo electrónico válido (ej. usuario@dominio.com)", "danger")
            return render_template("auth/registro.html", min_password=MIN_PASSWORD_LENGTH, fecha_max=fecha_max)

        # Verificación de mayoría de edad (18+)
        fecha_valida, mensaje_fecha, fecha_nacimiento = validar_fecha_nacimiento(fecha_nacimiento_texto)
        if not fecha_valida:
            flash(mensaje_fecha, "danger")
            return render_template("auth/registro.html", min_password=MIN_PASSWORD_LENGTH, fecha_max=fecha_max)

        password_valida, mensaje_password = validar_password(password)
        if not password_valida:
            flash(mensaje_password, "danger")
            return render_template("auth/registro.html", min_password=MIN_PASSWORD_LENGTH, fecha_max=fecha_max)

        if Usuario.obtener_por_email(email):
            flash("Ese correo ya está registrado", "warning")
            return render_template("auth/registro.html", min_password=MIN_PASSWORD_LENGTH, fecha_max=fecha_max)

        password_hash = generate_password_hash(password)
        Usuario.crear(nombre, apellido, email, password_hash, telefono, fecha_nacimiento=fecha_nacimiento)

        # Enviar correo de bienvenida (no debe fallar el registro si falla el correo)
        try:
            send_welcome_email(email, nombre)
        except Exception as e:
            print(f"Error al enviar correo de bienvenida: {e}")

        flash("Cuenta creada, ya puedes iniciar sesión", "success")
        # Ya declaró su fecha de nacimiento: no se le vuelve a preguntar la edad
        return marcar_mayor_edad(redirect(url_for("auth.login")))

    return render_template("auth/registro.html", min_password=MIN_PASSWORD_LENGTH, fecha_max=fecha_max)


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
