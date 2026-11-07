"""
Verificación de mayoría de edad (18+) para visitantes.

Rutas:
  GET/POST /verificar-edad    Pantalla de confirmación de edad
  GET      /acceso-restringido  Página para quien indica ser menor de edad

La confirmación se guarda en la cookie `mayor_edad`. El @app.before_request que
obliga a pasar por esta pantalla está en create_app (app/__init__.py).
"""

from flask import Blueprint, render_template, request, redirect, url_for, current_app
from app.utils.validaciones import EDAD_MINIMA

edad_bp = Blueprint("edad", __name__)

# Cookie que indica que el visitante confirmó ser mayor de edad
COOKIE_MAYOR_EDAD = "mayor_edad"
# Duración de la cookie: 30 días (en segundos)
DURACION_COOKIE_MAYOR_EDAD = 30 * 24 * 60 * 60


def ruta_segura(destino):
    """
    Valida el parámetro `next` para evitar open redirect.

    Solo se acepta una ruta interna: debe empezar con "/" y no con "//",
    y no puede contener "\\" ni caracteres de control (los navegadores ignoran
    tabuladores y saltos de línea, así que "/\\t/sitio.com" se convertiría en "//sitio.com").
    Si no es válida, devuelve "/".
    """
    if not destino or not destino.startswith("/"):
        return "/"
    if destino.startswith("//") or "\\" in destino:
        return "/"
    if any(ord(caracter) < 32 or ord(caracter) == 127 for caracter in destino):
        return "/"
    return destino


def marcar_mayor_edad(respuesta):
    """
    Agrega la cookie de mayoría de edad a una respuesta (redirect, render, etc.)
    y la devuelve. Se usa al confirmar la edad y al registrarse con éxito.
    """
    respuesta.set_cookie(
        COOKIE_MAYOR_EDAD,
        "1",
        max_age=DURACION_COOKIE_MAYOR_EDAD,
        httponly=True,
        samesite="Lax",
        secure=current_app.config.get("SESSION_COOKIE_SECURE", False),
    )
    return respuesta


@edad_bp.route("/verificar-edad", methods=["GET", "POST"])
def verificar_edad():
    """Pantalla donde el visitante confirma si es mayor o menor de edad."""
    if request.method == "POST":
        destino = ruta_segura(request.form.get("next") or request.args.get("next"))
        eleccion = request.form.get("respuesta")

        if eleccion == "mayor":
            return marcar_mayor_edad(redirect(destino))

        if eleccion == "menor":
            return redirect(url_for("edad.acceso_restringido"))

        # Respuesta desconocida: volver a mostrar la pantalla
        return redirect(url_for("edad.verificar_edad", next=destino))

    destino = ruta_segura(request.args.get("next"))
    return render_template(
        "edad/verificar_edad.html",
        destino=destino,
        edad_minima=EDAD_MINIMA,
    )


@edad_bp.route("/acceso-restringido")
def acceso_restringido():
    """Página informativa: el sitio es solo para mayores de edad (sin botones de entrada)."""
    return render_template("edad/acceso_restringido.html", edad_minima=EDAD_MINIMA)
