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

# Opciones válidas de método de pago (deben coincidir con <select> de checkout y cuenta)
TIPOS_PAGO = (
    "Tarjeta de crédito",
    "Tarjeta de débito",
    "Transferencia Bancaria (PSE)",
    "Nequi / Daviplata",
    "Efectivo contra entrega",
    "PayPal",
)
TIPOS_PAGO_CHECKOUT = (
    "Efectivo contra entrega",
    "PayPal",
)
MAX_DETALLE_PAGO = 100

# Largos máximos de columnas en la tabla `direcciones` (database/schema.sql)
MAX_ALIAS_DIRECCION = 50
MAX_LINEA_DIRECCION = 500
MAX_CIUDAD_DIRECCION = 100
MAX_DEPARTAMENTO_DIRECCION = 100
MAX_CODIGO_POSTAL_DIRECCION = 20

# Regex para celular colombiano: exactamente 10 dígitos iniciando con 3
TELEFONO_COLOMBIANO_REGEX = re.compile(r"^3[0-9]{9}$")


def normalizar_telefono_colombiano(telefono):
    """
    Normaliza el número de teléfono eliminando espacios, guiones y prefijos (+57 o 57),
    para conservar únicamente los 10 dígitos del celular.
    """
    if not telefono:
        return None
    tel = str(telefono).strip().replace(" ", "").replace("-", "")
    if tel.startswith("+57"):
        tel = tel[3:]
    elif tel.startswith("57") and len(tel) == 12:
        tel = tel[2:]
    return tel if tel else None


def validar_telefono_colombiano(telefono, obligatorio=False):
    """
    Valida que el teléfono cumpla con el formato de celular colombiano:
    - 10 dígitos numéricos
    - Debe iniciar con 3
    
    Returns:
        Tuple (bool, str|None, str|None): (es_valido, mensaje_error, telefono_limpio)
    """
    if not telefono or not str(telefono).strip():
        if obligatorio:
            return False, "El número de teléfono es obligatorio", None
        return True, None, None

    tel_limpio = normalizar_telefono_colombiano(telefono)
    if not tel_limpio or not TELEFONO_COLOMBIANO_REGEX.match(tel_limpio):
        return False, "El teléfono debe tener 10 dígitos y comenzar con 3 (ej. 3001234567)", None

    return True, None, tel_limpio


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


def validar_tipo_pago(tipo):
    """
    Valida que el tipo de pago sea una de las opciones permitidas en TIPOS_PAGO.

    Returns:
        Tuple (bool, str|None): (True, None) si es válido, (False, mensaje_error) si no
    """
    if not tipo or not str(tipo).strip():
        return False, "Por favor selecciona un método de pago"

    tipo_limpio = str(tipo).strip()
    if tipo_limpio not in TIPOS_PAGO:
        return False, "El método de pago seleccionado no es válido"

    return True, None


def validar_tipo_pago_checkout(tipo):
    """
    Valida que el tipo de pago sea una de las opciones permitidas en el checkout (TIPOS_PAGO_CHECKOUT).

    Returns:
        Tuple (bool, str|None): (True, None) si es válido, (False, mensaje_error) si no
    """
    if not tipo or not str(tipo).strip():
        return False, "Por favor selecciona un método de pago"

    tipo_limpio = str(tipo).strip()
    if tipo_limpio not in TIPOS_PAGO_CHECKOUT:
        return False, "El método de pago no está disponible para checkout. Selecciona Efectivo contra entrega o PayPal."

    return True, None


def validar_detalle_pago(detalle):
    """
    Valida el detalle o referencia de un método de pago (opcional, máximo 100 caracteres).
    Rechaza cualquier valor que contenga 12 o más dígitos (ignorando espacios y guiones)
    para evitar que se almacenen números completos de tarjeta en texto claro.

    Returns:
        Tuple (bool, str|None): (True, None) si es válido, (False, mensaje_error) si no
    """
    if detalle is None:
        return True, None

    detalle_limpio = str(detalle).strip()
    if not detalle_limpio:
        return True, None

    if len(detalle_limpio) > MAX_DETALLE_PAGO:
        return False, f"El detalle del método de pago no puede exceder {MAX_DETALLE_PAGO} caracteres"

    sin_espacios_guiones = re.sub(r"[\s-]+", "", detalle_limpio)
    cantidad_digitos = sum(1 for c in detalle_limpio if c.isdigit())
    if cantidad_digitos >= 12 or re.search(r"\d{12,}", sin_espacios_guiones):
        return (
            False,
            "Por seguridad no ingreses el número completo de la tarjeta; escribe solo los últimos 4 dígitos (ej. Terminada en 4242)",
        )

    return True, None


def validar_direccion(linea_direccion, ciudad, departamento=None, codigo_postal=None, alias=None):
    """
    Valida los campos de una dirección y sus longitudes máximas según database/schema.sql.

    Returns:
        Tuple (bool, str|None): (True, None) si es válida, (False, mensaje_error) si no
    """
    linea = (linea_direccion or "").strip()
    ciudad_limpia = (ciudad or "").strip()
    depto = (departamento or "").strip()
    postal = (codigo_postal or "").strip()
    alias_limpio = (alias or "").strip()

    if not linea or not ciudad_limpia:
        return False, "Por favor ingresa la dirección de entrega y la ciudad"

    if len(linea) > MAX_LINEA_DIRECCION:
        return False, f"La dirección no puede exceder {MAX_LINEA_DIRECCION} caracteres"

    if len(ciudad_limpia) > MAX_CIUDAD_DIRECCION:
        return False, f"La ciudad no puede exceder {MAX_CIUDAD_DIRECCION} caracteres"

    if depto and len(depto) > MAX_DEPARTAMENTO_DIRECCION:
        return False, f"El departamento no puede exceder {MAX_DEPARTAMENTO_DIRECCION} caracteres"

    if postal and len(postal) > MAX_CODIGO_POSTAL_DIRECCION:
        return False, f"El código postal no puede exceder {MAX_CODIGO_POSTAL_DIRECCION} caracteres"

    if alias_limpio and len(alias_limpio) > MAX_ALIAS_DIRECCION:
        return False, f"El alias no puede exceder {MAX_ALIAS_DIRECCION} caracteres"

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
