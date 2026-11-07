"""
Utilidades puras (sin base de datos) para el módulo de Reportes:
rango de fechas, agrupación de gráficas y exportación a CSV.
"""

import csv
import io
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

# Rango máximo permitido en un reporte (días, contando desde y hasta)
MAX_DIAS_RANGO = 366
# Hasta este número de días el reporte se agrupa por día; más que eso, por mes
MAX_DIAS_AGRUPACION_DIARIA = 62

FECHA_REGEX = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
# Caracteres con los que Excel interpreta una celda como fórmula
PREFIJOS_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def dias_en_rango(desde, hasta):
    """Cantidad de días del rango, contando desde y hasta (mismo día = 1)."""
    return (hasta - desde).days + 1


def _leer_fecha(texto):
    """Convierte 'YYYY-MM-DD' en date. Lanza ValueError si el formato es inválido."""
    texto = texto.strip()
    if not FECHA_REGEX.match(texto):
        raise ValueError("formato inválido")
    return datetime.strptime(texto, "%Y-%m-%d").date()


def parsear_rango_fechas(desde_str, hasta_str, hoy=None):
    """
    Convierte las fechas del formulario (YYYY-MM-DD) en un rango válido.

    Por defecto: primer día del mes actual hasta hoy.
    Si hay un error, devuelve el rango por defecto junto con el mensaje.

    Returns:
        Tuple (desde, hasta, error): date, date y str o None
    """
    hoy = hoy or date.today()
    desde_defecto = hoy.replace(day=1)
    hasta_defecto = hoy

    try:
        desde = _leer_fecha(desde_str) if desde_str and desde_str.strip() else desde_defecto
        hasta = _leer_fecha(hasta_str) if hasta_str and hasta_str.strip() else hasta_defecto
    except ValueError:
        return desde_defecto, hasta_defecto, "Las fechas deben tener el formato AAAA-MM-DD"

    if desde > hasta:
        return desde_defecto, hasta_defecto, "La fecha inicial no puede ser posterior a la fecha final"

    if dias_en_rango(desde, hasta) > MAX_DIAS_RANGO:
        return desde_defecto, hasta_defecto, f"El rango máximo es de {MAX_DIAS_RANGO} días"

    return desde, hasta, None


def elegir_agrupacion(desde, hasta):
    """Devuelve "dia" si el rango es de hasta 62 días y "mes" si es mayor."""
    if dias_en_rango(desde, hasta) <= MAX_DIAS_AGRUPACION_DIARIA:
        return "dia"
    return "mes"


def _celda_csv(valor):
    """
    Prepara una celda para el CSV.
    Los textos que empiezan con = + - @ llevan un apóstrofo al inicio para que
    Excel no los ejecute como fórmula. Los números no se tocan.
    """
    if valor is None:
        return ""
    if isinstance(valor, str):
        if valor.startswith(PREFIJOS_FORMULA):
            return "'" + valor
        return valor
    if isinstance(valor, (int, float, Decimal)):
        return valor
    # Fechas y otros tipos se convierten a texto
    return str(valor)


def generar_csv(encabezados, filas):
    """
    Devuelve un string CSV con delimitador ";" (Excel en español separa así las columnas).

    Nota: para que Excel muestre bien las tildes, al responder el archivo hay que
    codificarlo como UTF-8 con BOM ("utf-8-sig").
    """
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    escritor.writerow([_celda_csv(h) for h in encabezados])
    for fila in filas:
        escritor.writerow([_celda_csv(celda) for celda in fila])
    return salida.getvalue()
