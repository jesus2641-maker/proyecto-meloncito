"""
Módulo de autenticación de usuarios (login, registro y cierre de sesión).

Gestiona el acceso al sistema mediante sesiones de Flask, validación de
credenciales con hash seguro (Werkzeug), protección contra fuerza bruta
(límite de intentos por IP y correo), registro de clientes mayores de edad,
envío de correo de bienvenida y redirección según el rol asignado.
"""

# Módulos estándar para logging de errores y cálculo de tiempos de bloqueo
import logging
import math
# Utilidades de Flask para blueprint, plantillas, peticiones HTTP, redirecciones, sesión y mensajes flash
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
# Funciones de Werkzeug para hashing y verificación segura de contraseñas
from werkzeug.security import generate_password_hash, check_password_hash
# Modelo de usuario para consultas y creación en base de datos
from app.models.usuario import Usuario
# Validadores de formato, contraseñas, fecha de nacimiento (18+), nombres y teléfono colombiano
from app.utils.validaciones import (
    validar_email, validar_password, MIN_PASSWORD_LENGTH,
    validar_fecha_nacimiento, fecha_maxima_nacimiento,
    NOMBRE_REGEX, validar_telefono_colombiano
)
# Servicio de envío de correo electrónico de bienvenida
from app.utils.email_service import send_welcome_email
# Control de intentos fallidos de inicio de sesión (anti-fuerza bruta)
from app.utils.login_attempts import check_login_attempt, record_failed_attempt, reset_login_attempts, get_remaining_time
# Función auxiliar para establecer la cookie de mayoría de edad tras registrarse
from app.routes.edad import marcar_mayor_edad

# Logger del módulo de autenticación
logger = logging.getLogger(__name__)

# IDs de roles definidos en la base de datos
# NOTA: Cada rol tiene permisos distintos en la aplicación:
# - Cliente (1): navega el catálogo, gestiona su carrito, realiza pedidos y paga.
# - Admin (2): control total (productos, categorías, ofertas, proveedores, compras, usuarios y reportes).
# - Trabajador/Vendedor (4): gestiona pedidos asignados, consulta inventario/clientes y ve reportes básicos.
ID_ROL_CLIENTE = 1
ID_ROL_ADMIN = 2
ID_ROL_TRABAJADOR = 4

# Blueprint de autenticación bajo el prefijo /auth
auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    Vista de inicio de sesión de usuarios (`/auth/login`).

    - GET: muestra el formulario de acceso.
    - POST: valida formato de correo, verifica bloqueo por intentos fallidos,
      consulta el usuario en BD, verifica contraseña y estado activo, configura
      la sesión permanente y redirige al panel correspondiente al rol.

    Returns:
        flask.Response | str: Redirección al panel de rol o HTML de login.
    """
    if request.method == "POST":
        # Extrae credenciales del formulario y la IP del cliente para control de intentos
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        ip = request.remote_addr

        # Valida formato básico del correo antes de consultar la BD
        if not validar_email(email):
            flash("Ingresa un correo electrónico válido", "danger")
            return render_template("auth/login.html")

        # Verificar límite de intentos (protección contra ataques de fuerza bruta)
        if not check_login_attempt(ip, email):
            remaining_time = get_remaining_time(ip, email)
            # Formatea el tiempo restante de bloqueo en un texto legible
            if remaining_time < 60:
                tiempo_texto = "menos de 1 minuto"
            else:
                minutos = math.ceil(remaining_time / 60)
                tiempo_texto = f"{minutos} minuto" if minutos == 1 else f"{minutos} minutos"
            flash(f"Demasiados intentos. Intenta de nuevo en {tiempo_texto}.", "danger")
            return render_template("auth/login.html")

        # Busca el usuario por correo manejando posibles errores de conexión a la BD
        try:
            usuario = Usuario.obtener_por_email(email)
        except Exception as e:
            logger.error("Error al obtener usuario en login: %s", e)
            flash("Error de conexión al servidor. Intenta de nuevo más tarde.", "danger")
            return render_template("auth/login.html")

        # Verifica existencia del usuario y coincidencia del hash de contraseña
        if usuario and check_password_hash(usuario["password_hash"], password):
            # Impide el acceso si la cuenta fue desactivada por un administrador
            if not usuario.get("activo"):
                flash("Tu cuenta está desactivada. Contacta al administrador.", "danger")
                return render_template("auth/login.html")

            # Login exitoso: limpiar sesión previa (evita session fixation), reiniciar intentos y configurar sesión permanente
            session.clear()
            session.permanent = True
            session["id_usuario"] = usuario["id_usuario"]
            session["nombre"] = usuario["nombre"]
            session["id_rol"] = usuario["id_rol"]
            reset_login_attempts(ip, email)
            flash("Sesión iniciada correctamente", "success")

            # Redirigir al usuario según su rol en el sistema
            if usuario["id_rol"] == ID_ROL_ADMIN:
                return redirect(url_for("admin.dashboard"))
            elif usuario["id_rol"] == ID_ROL_TRABAJADOR:
                return redirect(url_for("trabajador.dashboard"))
            else:  # Cliente
                return redirect(url_for("productos.catalogo"))

        # Login fallido: registrar intento fallido para el par (IP, email)
        record_failed_attempt(ip, email)
        flash("Correo o contraseña incorrectos", "danger")

    return render_template("auth/login.html")


def validar_nombre_apellido(valor, campo="nombre"):
    """
    Valida nombre o apellido según las reglas del formulario de registro:
    - Obligatorio (no vacío)
    - Mínimo 2 y máximo 50 caracteres
    - Sin espacios al inicio o al final
    - Solo letras y espacios intermedios (según `NOMBRE_REGEX`)

    Args:
        valor (str): Texto ingresado por el usuario.
        campo (str): Nombre del campo ("nombre" o "apellido") para personalizar mensajes.

    Returns:
        tuple[bool, str | None]: `(True, None)` si es válido, o `(False, mensaje_error)`.
    """
    etiqueta = "El nombre" if campo == "nombre" else "El apellido"
    if not valor or not valor.strip():
        return False, f"{etiqueta} es obligatorio"
    if valor.startswith(" ") or valor.endswith(" "):
        return False, f"{etiqueta} no debe tener espacios al inicio ni al final"
    if len(valor) < 2:
        return False, f"{etiqueta} debe tener al menos 2 caracteres"
    if len(valor) > 50:
        return False, f"{etiqueta} no puede tener más de 50 caracteres"
    if not NOMBRE_REGEX.match(valor):
        return False, f"{etiqueta} solo puede contener letras y espacios"
    return True, None


@auth_bp.route("/registro", methods=["GET", "POST"])
def registro():
    """
    Vista de registro de nuevos clientes (`/auth/registro`).

    - GET: muestra el formulario con la fecha máxima permitida (18 años atrás).
    - POST: valida todos los campos (nombre, apellido, teléfono opcional, correo,
      fecha de nacimiento >= 18 años y contraseña), verifica unicidad del correo,
      persiste el usuario con contraseña hasheada, envía correo de bienvenida y
      marca la cookie de mayoría de edad antes de redirigir al login.

    Returns:
        flask.Response | str: Redirección al login o formulario con errores.
    """
    # Fecha de nacimiento más reciente permitida (hoy menos 18 años) para el input date
    fecha_max = fecha_maxima_nacimiento()

    if request.method == "POST":
        # Captura de campos del formulario (sin hacer strip a nombre/apellido aún para detectar espacios laterales)
        nombre_raw = request.form.get("nombre", "")
        apellido_raw = request.form.get("apellido", "")
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        telefono_raw = request.form.get("telefono", "").strip()
        fecha_nacimiento_texto = request.form.get("fecha_nacimiento", "")

        # Diccionario para acumular mensajes de error por nombre de campo
        errores = {}

        # Validación de nombre (mínimo 2, máximo 50, sin espacios al inicio o final)
        valido_nombre, msg_nombre = validar_nombre_apellido(nombre_raw, "nombre")
        if not valido_nombre:
            errores["nombre"] = msg_nombre

        # Validación de apellido (mínimo 2, máximo 50, sin espacios al inicio o final)
        valido_apellido, msg_apellido = validar_nombre_apellido(apellido_raw, "apellido")
        if not valido_apellido:
            errores["apellido"] = msg_apellido

        # Validación de teléfono celular colombiano (10 dígitos iniciando con 3) si fue proporcionado
        if telefono_raw:
            valido_tel, msg_tel, tel_normalizado = validar_telefono_colombiano(telefono_raw)
            if not valido_tel:
                errores["telefono"] = msg_tel
            else:
                telefono = tel_normalizado
        else:
            telefono = None

        # Validación de correo electrónico obligatorio y con formato válido
        if not email:
            errores["email"] = "El correo electrónico es obligatorio"
        elif not validar_email(email):
            errores["email"] = "Ingresa un correo electrónico válido (ej. usuario@dominio.com)"

        # Verificación de mayoría de edad (18+) a partir de la fecha de nacimiento
        fecha_valida, mensaje_fecha, fecha_nacimiento = validar_fecha_nacimiento(fecha_nacimiento_texto)
        if not fecha_valida:
            errores["fecha_nacimiento"] = mensaje_fecha

        # Validación de fortaleza de la contraseña
        password_valida, mensaje_password = validar_password(password)
        if not password_valida:
            errores["password"] = mensaje_password

        # Si hay errores de validación, retornar el formulario conservando datos y errores por campo
        if errores:
            return render_template(
                "auth/registro.html",
                min_password=MIN_PASSWORD_LENGTH,
                fecha_max=fecha_max,
                form_data=request.form,
                errores=errores
            )

        nombre = nombre_raw.strip()
        apellido = apellido_raw.strip()

        # Verifica unicidad del correo y crea el registro en base de datos
        try:
            if Usuario.obtener_por_email(email):
                errores["email"] = "Ese correo ya está registrado"
                return render_template(
                    "auth/registro.html",
                    min_password=MIN_PASSWORD_LENGTH,
                    fecha_max=fecha_max,
                    form_data=request.form,
                    errores=errores
                )

            # Genera hash seguro de la contraseña antes de almacenarla
            password_hash = generate_password_hash(password)
            Usuario.crear(nombre, apellido, email, password_hash, telefono, fecha_nacimiento=fecha_nacimiento)
        except Exception as err:
            # Manejo diferenciado de errores de duplicidad, conexión o fallos generales de BD
            logger.exception("Error al registrar usuario: %s", err)
            err_str = str(err).lower()
            if "duplicate" in err_str or "1062" in err_str:
                errores["email"] = "Ese correo electrónico ya se encuentra registrado"
            elif "connect" in err_str or "2003" in err_str or "access denied" in err_str:
                flash("No fue posible conectar con la base de datos para registrar la cuenta. Verifica que el servidor de base de datos esté activo.", "danger")
            else:
                flash("Ocurrió un error al procesar el registro. Intenta nuevamente.", "danger")
            return render_template(
                "auth/registro.html",
                min_password=MIN_PASSWORD_LENGTH,
                fecha_max=fecha_max,
                form_data=request.form,
                errores=errores
            )

        # Enviar correo de bienvenida (no debe fallar el registro si falla el envío SMTP)
        try:
            send_welcome_email(email, nombre)
        except Exception:
            logger.exception("Error al enviar correo de bienvenida")

        flash("Cuenta creada, ya puedes iniciar sesión", "success")
        # Ya declaró su fecha de nacimiento: se establece cookie para no volver a preguntar la edad
        return marcar_mayor_edad(redirect(url_for("auth.login")))

    return render_template("auth/registro.html", min_password=MIN_PASSWORD_LENGTH, fecha_max=fecha_max)


@auth_bp.route("/logout")
def logout():
    """
    Cierra la sesión actual del usuario limpiando todos los datos de `session`
    y redirige al formulario de inicio de sesión.

    Returns:
        flask.Response: Redirección a `auth.login`.
    """
    session.clear()
    return redirect(url_for("auth.login"))
