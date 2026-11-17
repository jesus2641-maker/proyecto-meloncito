"""
Verificación de mayoría de edad (18+) para visitantes.

Módulo encargado de gestionar el filtro legal de edad antes de permitir la
navegación por el catálogo de bebidas alcohólicas.

Rutas:
  GET/POST /verificar-edad    Pantalla de confirmación de edad
  GET      /acceso-restringido  Página para quien indica ser menor de edad

La confirmación se guarda en la cookie `mayor_edad`. El @app.before_request que
obliga a pasar por esta pantalla está en create_app (app/__init__.py).
"""

# Blueprint y utilidades de Flask para renderizado, peticiones HTTP, redirecciones y configuración
from flask import Blueprint, render_template, request, redirect, url_for, current_app
# Constante de edad mínima permitida y validador de URLs internas seguras (evita Open Redirect)
from app.utils.validaciones import EDAD_MINIMA, ruta_segura

# Definición del blueprint de verificación de edad (sin prefijo URL)
edad_bp = Blueprint("edad", __name__)

# Nombre de la cookie que indica que el visitante confirmó ser mayor de edad
COOKIE_MAYOR_EDAD = "mayor_edad"
# Duración de la cookie en segundos: 30 días * 24 horas * 60 minutos * 60 segundos
DURACION_COOKIE_MAYOR_EDAD = 30 * 24 * 60 * 60


def marcar_mayor_edad(respuesta):
    """
    Agrega la cookie de mayoría de edad a una respuesta HTTP (redirect, render, etc.)
    y la devuelve lista para enviarse al navegador.

    Se utiliza tanto cuando el usuario confirma su edad manualmente como cuando
    completa un registro exitoso en la plataforma.

    Args:
        respuesta (flask.Response): Objeto de respuesta HTTP de Flask al que se le
            adjuntará la cookie de verificación.

    Returns:
        flask.Response: El mismo objeto de respuesta con la cabecera Set-Cookie configurada.
    """
    # Configura la cookie con atributos de seguridad:
    # - httponly=True: impide el acceso desde JavaScript (mitiga XSS).
    # - samesite="Lax": protege contra CSRF manteniendo navegación normal desde enlaces externos.
    # - secure: solo envía la cookie por HTTPS si la configuración de la app así lo exige.
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
    """
    Pantalla donde el visitante confirma si es mayor o menor de edad.

    - En peticiones GET: muestra el formulario de verificación recordando la URL
      original (`next`) a la que el visitante intentaba acceder.
    - En peticiones POST: procesa la elección del usuario ("mayor" o "menor"),
      establece la cookie si corresponde y redirige al destino seguro o a la
      página de acceso restringido.

    Returns:
        flask.Response | str: Redirección HTTP (POST) o HTML renderizado (GET).
    """
    if request.method == "POST":
        # Obtiene la ruta de retorno desde el formulario o query string y valida que sea interna
        destino = ruta_segura(request.form.get("next") or request.args.get("next"))
        # Lee el valor del botón/opción seleccionado por el visitante
        eleccion = request.form.get("respuesta")

        # Si el visitante confirma ser mayor de edad, guarda la cookie y redirige al destino
        if eleccion == "mayor":
            return marcar_mayor_edad(redirect(destino))

        # Si indica ser menor de edad, lo envía a la pantalla informativa de restricción
        if eleccion == "menor":
            return redirect(url_for("edad.acceso_restringido"))

        # Respuesta desconocida o manipulada: volver a mostrar la pantalla conservando `next`
        return redirect(url_for("edad.verificar_edad", next=destino))

    # Petición GET: valida la ruta de destino recibida por parámetro URL (por defecto "/")
    destino = ruta_segura(request.args.get("next"))
    # Renderiza la plantilla de verificación pasando el destino y la edad mínima legal
    return render_template(
        "edad/verificar_edad.html",
        destino=destino,
        edad_minima=EDAD_MINIMA,
    )


@edad_bp.route("/acceso-restringido")
def acceso_restringido():
    """
    Página informativa que indica que el sitio es exclusivo para mayores de edad.

    No incluye botones de entrada ni establece la cookie de verificación.

    Returns:
        str: Plantilla HTML renderizada con la advertencia legal de edad mínima.
    """
    return render_template("edad/acceso_restringido.html", edad_minima=EDAD_MINIMA)
