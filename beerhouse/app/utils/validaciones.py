import re

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
MIN_PASSWORD_LENGTH = 6


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


def validar_stock_carrito(items):
    """Verifica que cada item del carrito tenga stock suficiente y esté disponible."""
    from app.models.producto import VarianteProducto, Producto

    errores = []
    for item in items:
        variante = VarianteProducto.obtener_por_id(item["id_variante"])
        nombre = item.get("nombre_producto", "Producto")
        presentacion = item.get("presentacion", "")

        if not variante:
            errores.append(f"'{nombre}' ({presentacion}) ya no está disponible.")
            continue

        producto = Producto.obtener_por_id(variante["id_producto"])
        if not producto or not producto.get("activo"):
            errores.append(f"'{nombre}' ({presentacion}) ya no está disponible.")
            continue

        if variante["stock"] <= 0:
            errores.append(f"'{nombre}' ({presentacion}) está agotado.")
        elif item["cantidad"] > variante["stock"]:
            errores.append(
                f"'{nombre}' ({presentacion}): solo hay {variante['stock']} disponible(s), "
                f"pero tienes {item['cantidad']} en el carrito."
            )

    return errores
