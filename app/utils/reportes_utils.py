"""
Utilidades puras (sin acceso a base de datos) para el módulo de Reportes:
validación y parseo de rangos de fechas, selección automática de agrupación
para gráficas y exportación segura a CSV (con prevención de CSV Injection).
"""

import csv
import io
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

# Rango máximo permitido en un reporte (días, contando desde y hasta inclusive)
MAX_DIAS_RANGO = 366
# Hasta este número de días el reporte se agrupa por día; más que eso, por mes
MAX_DIAS_AGRUPACION_DIARIA = 62

# Expresión regular estricta para validar fechas en formato ISO (AAAA-MM-DD)
FECHA_REGEX = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
# Caracteres iniciales con los que Excel/LibreOffice interpretan una celda como fórmula
PREFIJOS_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def dias_en_rango(desde, hasta):
    """
    Calcula la cantidad de días calendario comprendidos en un rango cerrado.

    Cuenta tanto la fecha inicial como la final (por ejemplo, si `desde == hasta`,
    el resultado es `1`).

    Args:
        desde (datetime.date): Fecha de inicio del rango.
        hasta (datetime.date): Fecha de fin del rango.

    Returns:
        int: Número total de días incluidos en el intervalo.
    """
    return (hasta - desde).days + 1


def _leer_fecha(texto):
    """
    Convierte una cadena `'YYYY-MM-DD'` en un objeto `datetime.date`.

    Valida primero con expresión regular y luego con `datetime.strptime` para
    descartar fechas inexistentes (ej. `'2024-02-30'`).

    Args:
        texto (str): Cadena de fecha a parsear.

    Returns:
        datetime.date: Fecha convertida.

    Raises:
        ValueError: Si el formato no coincide con `YYYY-MM-DD` o la fecha no existe.
    """
    texto = texto.strip()
    if not FECHA_REGEX.match(texto):
        raise ValueError("formato inválido")
    return datetime.strptime(texto, "%Y-%m-%d").date()


def parsear_rango_fechas(desde_str, hasta_str, hoy=None):
    """
    Convierte las fechas recibidas del formulario (`YYYY-MM-DD`) en un rango válido.

    Si no se envían fechas, usa por defecto desde el primer día del mes actual
    hasta `hoy`. Ante cualquier error de formato, orden invertido o exceso de días,
    devuelve el rango por defecto acompañado de un mensaje descriptivo de error.

    Args:
        desde_str (str | None): Texto de fecha inicial del filtro.
        hasta_str (str | None): Texto de fecha final del filtro.
        hoy (datetime.date | None): Fecha de referencia (opcional, útil en tests).

    Returns:
        tuple[datetime.date, datetime.date, str | None]: Tupla `(desde, hasta, error)`.
            `error` es `None` cuando el rango es válido.
    """
    # Usamos la fecha actual si no se inyectó una fecha de referencia
    hoy = hoy or date.today()
    # Rango por defecto: desde el día 1 del mes en curso hasta hoy
    desde_defecto = hoy.replace(day=1)
    hasta_defecto = hoy

    # Intentamos parsear ambas fechas; si alguna viene vacía, aplicamos su valor por defecto
    try:
        desde = _leer_fecha(desde_str) if desde_str and desde_str.strip() else desde_defecto
        hasta = _leer_fecha(hasta_str) if hasta_str and hasta_str.strip() else hasta_defecto
    except ValueError:
        return desde_defecto, hasta_defecto, "Las fechas deben tener el formato AAAA-MM-DD"

    # Validamos coherencia cronológica (inicio no puede ser mayor que fin)
    if desde > hasta:
        return desde_defecto, hasta_defecto, "La fecha inicial no puede ser posterior a la fecha final"

    # Limitamos la amplitud máxima del reporte para proteger rendimiento de consultas
    if dias_en_rango(desde, hasta) > MAX_DIAS_RANGO:
        return desde_defecto, hasta_defecto, f"El rango máximo es de {MAX_DIAS_RANGO} días"

    return desde, hasta, None


def elegir_agrupacion(desde, hasta):
    """
    Determina la granularidad temporal ideal para graficar un rango de fechas.

    Args:
        desde (datetime.date): Fecha inicial del rango.
        hasta (datetime.date): Fecha final del rango.

    Returns:
        str: `"dia"` si el rango tiene hasta 62 días (inclusive), o `"mes"` si es mayor.
    """
    if dias_en_rango(desde, hasta) <= MAX_DIAS_AGRUPACION_DIARIA:
        return "dia"
    return "mes"


def _celda_csv(valor):
    """
    Sanitiza y prepara el valor de una celda antes de escribirla en el CSV.

    Previene ataques de inyección de fórmulas (CSV Injection): los textos que
    comienzan con `=`, `+`, `-`, `@`, `\\t` o `\\r` reciben un apóstrofo (`'`) al
    inicio para que Excel los trate como texto plano y no los ejecute.
    Los tipos numéricos (`int`, `float`, `Decimal`) se conservan sin alterar.

    Args:
        valor (Any): Valor original de la celda.

    Returns:
        str | int | float | Decimal: Valor seguro listo para `csv.writer`.
    """
    if valor is None:
        return ""
    if isinstance(valor, str):
        # Neutralizamos prefijos peligrosos anteponiendo una comilla simple
        if valor.startswith(PREFIJOS_FORMULA):
            return "'" + valor
        return valor
    if isinstance(valor, (int, float, Decimal)):
        return valor
    # Fechas y otros tipos se convierten a texto
    return str(valor)


def generar_csv(encabezados, filas):
    """
    Genera el contenido de un archivo CSV en memoria usando `";"` como delimitador.

    El punto y coma es el separador estándar esperado por Excel configurado en español.
    Nota: para que Excel muestre correctamente tildes y caracteres especiales, al enviar
    la respuesta HTTP debe codificarse en UTF-8 con BOM (`"utf-8-sig"`).

    Args:
        encabezados (Iterable[Any]): Lista o tupla con los títulos de las columnas.
        filas (Iterable[Iterable[Any]]): Filas de datos a exportar.

    Returns:
        str: Contenido completo del archivo CSV con saltos de línea CRLF (`\\r\\n`).
    """
    # Escribimos en un buffer de texto en memoria (`StringIO`) en lugar de disco
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    # Escribimos la fila de encabezados sanitizada
    escritor.writerow([_celda_csv(h) for h in encabezados])
    # Escribimos cada fila de datos aplicando la sanitización celda por celda
    for fila in filas:
        escritor.writerow([_celda_csv(celda) for celda in fila])
    return salida.getvalue()
