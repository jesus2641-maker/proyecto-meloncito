"""
Utilidades para manejo de divisas y conversiones entre COP y USD.

Beer House opera principalmente en pesos colombianos (COP), mientras que la
pasarela de pagos (PayPal) liquida en dólares estadounidenses (USD).
Se utiliza `decimal.Decimal` en todas las operaciones monetarias para evitar
errores de precisión propios de la aritmética en coma flotante (`float`).
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from config import Config


def obtener_tasa_cop_usd():
    """
    Obtiene y valida la tasa de conversión COP -> USD configurada en el sistema.

    Lee `Config.TASA_COP_USD` (cuántos COP equivalen a 1 USD) y garantiza que sea
    un `Decimal` estrictamente positivo.

    Returns:
        Decimal: Tasa de conversión válida (> 0).

    Raises:
        ValueError: Si `TASA_COP_USD` no está configurada, no es numérica o es <= 0.
    """
    # Leemos la tasa desde Config con 0.0 como respaldo si no existe el atributo
    tasa = getattr(Config, "TASA_COP_USD", 0.0)
    try:
        # Convertimos mediante `str()` para preservar la representación decimal exacta
        tasa_dec = Decimal(str(tasa))
    except (InvalidOperation, TypeError, ValueError):
        tasa_dec = Decimal("0")

    # Una tasa <= 0 impediría dividir o produciría montos negativos/inválidos
    if tasa_dec <= Decimal("0"):
        raise ValueError(
            "La tasa de conversión TASA_COP_USD no está configurada o es inválida (debe ser mayor a 0). "
            "Por favor, configúrala en el archivo .env o en las variables de entorno."
        )
    return tasa_dec


def cop_a_usd(monto_cop, tasa=None):
    """
    Convierte un monto en COP a USD con 2 decimales usando redondeo `ROUND_HALF_UP`.

    Args:
        monto_cop (int | float | str | Decimal): Valor expresado en pesos colombianos.
        tasa (int | float | str | Decimal | None): Tasa de cambio opcional (COP por 1 USD).
            Si es `None`, obtiene `TASA_COP_USD` mediante `obtener_tasa_cop_usd()`.

    Returns:
        Decimal: Importe equivalente en dólares estadounidenses redondeado a 2 decimales.

    Raises:
        ValueError: Si la tasa es <= 0 o el monto en COP no puede convertirse a `Decimal`.
    """
    # Resolvemos la tasa: desde configuración si no se pasó explícitamente, o validando la recibida
    if tasa is None:
        tasa_dec = obtener_tasa_cop_usd()
    else:
        try:
            tasa_dec = Decimal(str(tasa))
        except (InvalidOperation, TypeError, ValueError):
            tasa_dec = Decimal("0")
        if tasa_dec <= Decimal("0"):
            raise ValueError("La tasa de conversión debe ser mayor a 0")

    # Convertimos el monto en COP a Decimal de forma segura
    try:
        monto_dec = Decimal(str(monto_cop))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Monto COP inválido: {monto_cop}")

    # Dividimos COP entre la tasa y redondeamos al centavo (0.01) con redondeo comercial estándar
    usd = (monto_dec / tasa_dec).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return usd


def formatear_cop(monto):
    """
    Devuelve un texto formateado en pesos colombianos, por ejemplo: `"$120.000"`.

    Usa punto como separador de miles y omite decimales, siguiendo la convención
    visual habitual en Colombia.

    Args:
        monto (int | float | str | Decimal | None): Valor monetario a formatear.

    Returns:
        str: Cadena formateada con prefijo `"$"` y separador de miles `"."`
            (devuelve `"$0"` si el valor es `None` o no es numérico).
    """
    if monto is None:
        return "$0"
    try:
        # Redondear al entero más cercano antes de formatear (sin centavos en COP)
        monto_float = float(monto)
        monto_int = round(monto_float)
    except (ValueError, TypeError):
        return "$0"

    # Python formatea miles con coma (ej. "120,000"); la reemplazamos por punto ("120.000")
    formato_intermedio = f"{monto_int:,}"
    formato_puntos = formato_intermedio.replace(",", ".")
    return f"${formato_puntos}"
