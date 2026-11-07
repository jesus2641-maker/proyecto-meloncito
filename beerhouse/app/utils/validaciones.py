import re
from datetime import date, datetime

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
MIN_PASSWORD_LENGTH = 6
# Edad mínima para registrarse y comprar (mayoría de edad)
EDAD_MINIMA = 18
# Edad máxima aceptada: descarta fechas de nacimiento absurdas
EDAD_MAXIMA = 120
# Formato estricto que envía <input type="date">: YYYY-MM-DD
FECHA_NACIMIENTO_REGEX = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
# Regex para nombres: solo letras (incluyendo acentos y espacios)
NOMBRE_REGEX = re.compile(r"^[a-zA-ZáéíóúÁÉÍÓÚñÑüÜ\s]+$")
# Regex para nombres comerciales de proveedores: letras, dígitos, espacios y . , & - ' ( ) /
NOMBRE_COMERCIAL_REGEX = re.compile(r"^[a-zA-Z0-9áéíóúÁÉÍÓÚñÑüÜ\s.,&'()/ -]+$")
# Largo máximo de la columna `nombre` en la tabla `proveedores` (VARCHAR(150))
MAX_NOMBRE_PROVEEDOR = 150


def validar_email(email):
    if not email or not email.strip():
        return False
    return bool(EMAIL_REGEX.match(email.strip()))


def validar_password(password, min_length=MIN_PASSWORD_LENGTH):
    if not password:
        return False, f"La contraseña debe tener al menos {min_length} caracteres"
    if len(password) < min_length:
        return False, f"La contraseña debe tener al menos {min_length} caracteres"
    return True, None


def calcular_edad(fecha_nacimiento, hoy=None):
    """
    Calcula la edad en años cumplidos a una fecha dada.

    Args:
        fecha_nacimiento: date con la fecha de nacimiento
        hoy: date de referencia (por defecto, la fecha actual). Útil para pruebas.

    Returns:
        int: años cumplidos (considera si ya pasó el cumpleaños este año)
    """
    hoy = hoy or date.today()
    edad = hoy.year - fecha_nacimiento.year
    # Si el cumpleaños de este año todavía no llega, aún no cumple el año
    if (hoy.month, hoy.day) < (fecha_nacimiento.month, fecha_nacimiento.day):
        edad -= 1
    return edad


def fecha_maxima_nacimiento(edad_minima=EDAD_MINIMA, hoy=None):
    """
    Fecha de nacimiento más reciente permitida (hoy menos edad_minima años).
    Se usa como atributo max del <input type="date"> del registro.

    Si hoy es 29 de febrero y el año destino no es bisiesto, devuelve el 28 de
    febrero (coherente con calcular_edad: quien nace el 29/02 cumple el 1 de marzo).
    """
    hoy = hoy or date.today()
    try:
        return hoy.replace(year=hoy.year - edad_minima)
    except ValueError:
        return hoy.replace(year=hoy.year - edad_minima, day=28)


def validar_fecha_nacimiento(texto, edad_minima=EDAD_MINIMA, hoy=None):
    """
    Valida la fecha de nacimiento enviada por el formulario (formato YYYY-MM-DD).

    Rechaza: vacío, formato inválido, fecha futura, edad mayor a 120 años y
    edad menor a la mínima. Quien cumple la edad mínima hoy SÍ es válido.

    Returns:
        Tuple (bool, str|None, date|None): (True, None, fecha) si es válida,
        (False, mensaje_error, None) si no.
    """
    hoy = hoy or date.today()
    texto = (texto or "").strip()

    if not texto:
        return False, "La fecha de nacimiento es obligatoria", None

    if not FECHA_NACIMIENTO_REGEX.match(texto):
        return False, "La fecha de nacimiento no tiene un formato válido", None

    try:
        fecha = datetime.strptime(texto, "%Y-%m-%d").date()
    except ValueError:
        # Formato correcto pero fecha inexistente (ej. 2023-02-30)
        return False, "La fecha de nacimiento no tiene un formato válido", None

    if fecha > hoy:
        return False, "La fecha de nacimiento no puede ser futura", None

    edad = calcular_edad(fecha, hoy)

    if edad > EDAD_MAXIMA:
        return False, "La fecha de nacimiento no es válida", None

    if edad < edad_minima:
        return False, f"Debes ser mayor de {edad_minima} años para registrarte", None

    return True, None, fecha


def validar_nombre(nombre):
    """
    Valida que un nombre contenga solo letras (incluyendo acentos y espacios).

    Args:
        nombre: String a validar

    Returns:
        Tuple (bool, str): (True, None) si es válido, (False, mensaje_error) si no
    """
    if not nombre or not nombre.strip():
        return False, "El nombre es obligatorio"

    nombre_limpio = nombre.strip()

    if not NOMBRE_REGEX.match(nombre_limpio):
        return False, "El nombre solo puede contener letras y espacios (sin números ni caracteres especiales)"

    if len(nombre_limpio) < 2:
        return False, "El nombre debe tener al menos 2 caracteres"

    if len(nombre_limpio) > 100:
        return False, "El nombre no puede exceder 100 caracteres"

    return True, None


def validar_nombre_comercial(nombre):
    """
    Valida el nombre comercial de un proveedor.
    Acepta letras (con tildes y ñ), dígitos, espacios y los signos . , & - ' ( ) /
    con mínimo 2 caracteres y máximo 150 (VARCHAR(150) en proveedores.nombre).

    Returns:
        Tuple (bool, str|None): (True, None) si es válido, (False, mensaje_error) si no
    """
    if not nombre or not nombre.strip():
        return False, "El nombre es obligatorio"

    nombre_limpio = nombre.strip()

    if len(nombre_limpio) < 2:
        return False, "El nombre debe tener al menos 2 caracteres"

    if len(nombre_limpio) > MAX_NOMBRE_PROVEEDOR:
        return False, f"El nombre no puede exceder {MAX_NOMBRE_PROVEEDOR} caracteres"

    if not NOMBRE_COMERCIAL_REGEX.match(nombre_limpio):
        return (
            False,
            "El nombre comercial solo puede contener letras, números, espacios y los signos . , & - ' ( ) /",
        )

    return True, None


def validar_stock_carrito(items):
    """Verifica que cada item del carrito tenga stock suficiente y esté disponible."""
    from app.models.producto import VarianteProducto, Producto

    errores = []
    for item in items:
        id_variante = item.get("id_variante")
        variante = VarianteProducto.obtener_por_id(id_variante)
        nombre = item.get("nombre_producto", "Producto")
        presentacion = item.get("presentacion", "")

        # Validar que la variante exista
        if not variante:
            errores.append(f"'{nombre}' ({presentacion}) ya no está disponible.")
            continue

        # Validar que el producto exista y esté activo
        producto = Producto.obtener_por_id(variante["id_producto"])
        if not producto or not producto.get("activo"):
            errores.append(f"'{nombre}' ({presentacion}) ya no está disponible.")
            continue

        # Validar stock positivo
        if variante["stock"] <= 0:
            errores.append(f"'{nombre}' ({presentacion}) está agotado.")
        # Validar que la cantidad solicitada no exceda el stock disponible
        elif item["cantidad"] > variante["stock"]:
            errores.append(
                f"'{nombre}' ({presentacion}): solo hay {variante['stock']} disponible(s), "
                f"pero tienes {item['cantidad']} en el carrito."
            )
        # Validar que el precio sea válido
        elif not variante.get("precio") or variante["precio"] <= 0:
            errores.append(f"'{nombre}' ({presentacion}) tiene un precio inválido.")

    return errores
