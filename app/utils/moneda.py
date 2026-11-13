"""
Utilidades para manejo de divisas y conversiones entre COP y USD.
Beer House opera principalmente en pesos colombianos (COP), mientras
que la pasarela de pagos (PayPal) liquida en dólares estadounidenses (USD).
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from config import Config


def obtener_tasa_cop_usd():
    """
    Obtiene y valida la tasa de conversión configurada.
    Lanza ValueError con mensaje claro si la tasa es 0 o no está configurada.
    """
    tasa = getattr(Config, "TASA_COP_USD", 0.0)
    try:
        tasa_dec = Decimal(str(tasa))
    except (InvalidOperation, TypeError, ValueError):
        tasa_dec = Decimal("0")

    if tasa_dec <= Decimal("0"):
        raise ValueError(
            "La tasa de conversión TASA_COP_USD no está configurada o es inválida (debe ser mayor a 0). "
            "Por favor, configúrala en el archivo .env o en las variables de entorno."
        )
    return tasa_dec


def cop_a_usd(monto_cop, tasa=None):
    """
    Convierte un monto en COP a USD con 2 decimales usando redondeo ROUND_HALF_UP.
    
    Args:
        monto_cop: Número, string o Decimal con el valor en COP.
        tasa: Opcional. Tasa de cambio (si no se especifica, toma TASA_COP_USD de Config).
        
    Returns:
        Decimal con el importe en USD redondeado a 2 decimales.
    """
    if tasa is None:
        tasa_dec = obtener_tasa_cop_usd()
    else:
        try:
            tasa_dec = Decimal(str(tasa))
        except (InvalidOperation, TypeError, ValueError):
            tasa_dec = Decimal("0")
        if tasa_dec <= Decimal("0"):
            raise ValueError("La tasa de conversión debe ser mayor a 0")

    try:
        monto_dec = Decimal(str(monto_cop))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Monto COP inválido: {monto_cop}")

    usd = (monto_dec / tasa_dec).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return usd


def formatear_cop(monto):
    """
    Devuelve un texto formateado en pesos colombianos, ej: "$120.000".
    Usa punto como separador de miles y sin decimales.
    
    Args:
        monto: Número, string o Decimal.
        
    Returns:
        str con formato "$X.XXX"
    """
    if monto is None:
        return "$0"
    try:
        # Redondear al entero más cercano antes de formatear
        monto_float = float(monto)
        monto_int = round(monto_float)
    except (ValueError, TypeError):
        return "$0"

    # Formatear con comas y reemplazar por puntos
    formato_intermedio = f"{monto_int:,}"
    formato_puntos = formato_intermedio.replace(",", ".")
    return f"${formato_puntos}"
