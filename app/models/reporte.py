"""
Modelo de Reportes - Consultas de solo lectura para el módulo de reportes del administrador.

Reglas generales:
- Las ventas EXCLUYEN los pedidos cancelados (se une con estados_pedido por nombre).
- Las ventas EXCLUYEN pedidos cuyo pago asociado en `pagos` no esté 'completado'.
- El rango de fechas es inclusivo: fecha >= desde AND fecha < hasta + 1 día.
- Los montos se devuelven como float redondeado a 2 decimales (listos para gráficas y CSV).
"""

# Utilidad de fechas para calcular el límite superior exclusivo (+1 día)
from datetime import timedelta

# Función para obtener una conexión activa a MySQL
from app.utils.db import get_connection

# Nombre del estado que se excluye de las ventas (tabla estados_pedido)
ESTADO_CANCELADO = "cancelado"


def _a_float(valor):
    """
    Convierte un Decimal o None proveniente de MySQL a float redondeado a 2 decimales.

    Args:
        valor (Decimal | float | int | None): Valor numérico retornado por SQL.

    Returns:
        float: Valor convertido y redondeado a 2 cifras decimales (0.0 si es None).
    """
    return round(float(valor or 0), 2)


def _limites(desde, hasta):
    """
    Calcula los límites de fecha semiabiertos para consultas SQL: `[desde, hasta + 1 día)`.
    De este modo se incluyen todas las horas del día `hasta`.

    Args:
        desde (date | datetime): Fecha inicial del rango.
        hasta (date | datetime): Fecha final del rango (inclusive).

    Returns:
        tuple: Par `(inicio, fin)` listo para usarse en cláusulas `>= %s AND < %s`.
    """
    return desde, hasta + timedelta(days=1)


class Reporte:
    """
    Modelo analítico de solo lectura que agrupa las consultas estadísticas de
    ventas, productos más vendidos, inventario crítico y balance compras vs ventas.
    """

    @staticmethod
    def resumen_ventas(desde, hasta):
        """
        Calcula total vendido, número de pedidos y ticket promedio del rango
        (excluyendo pedidos cancelados y pedidos con pagos incompletos).

        Args:
            desde (date | datetime): Fecha de inicio del análisis.
            hasta (date | datetime): Fecha de fin del análisis (inclusive).

        Returns:
            dict: Diccionario con `total_vendido`, `num_pedidos` y `ticket_promedio`.
        """
        inicio, fin = _limites(desde, hasta)
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        # Se aceptan pedidos sin registro en `pagos` (ej. pago contraentrega) o con pago 'completado'
        cursor.execute("""
            SELECT COALESCE(SUM(pe.total), 0) AS total_vendido,
                   COUNT(pe.id_pedido) AS num_pedidos,
                   COALESCE(AVG(pe.total), 0) AS ticket_promedio
            FROM pedidos pe
            JOIN estados_pedido es ON pe.id_estado = es.id_estado
            WHERE es.nombre_estado <> %s
              AND pe.fecha_pedido >= %s AND pe.fecha_pedido < %s
              AND (
                NOT EXISTS (SELECT 1 FROM pagos pg WHERE pg.id_pedido = pe.id_pedido)
                OR EXISTS (SELECT 1 FROM pagos pg WHERE pg.id_pedido = pe.id_pedido AND pg.estado = 'completado')
              )
        """, (ESTADO_CANCELADO, inicio, fin))
        fila = cursor.fetchone()
        cursor.close()
        conn.close()

        return {
            "total_vendido": _a_float(fila["total_vendido"]),
            "num_pedidos": int(fila["num_pedidos"]),
            "ticket_promedio": _a_float(fila["ticket_promedio"]),
        }

    @staticmethod
    def ventas_por_periodo(desde, hasta, agrupar):
        """
        Obtiene las ventas agrupadas por `"dia"` o `"mes"`: lista de `{periodo, total, pedidos}`.
        En modo `"dia"` se rellenan con 0 los días sin ventas para que la gráfica sea continua.

        Args:
            desde (date | datetime): Fecha inicial del rango.
            hasta (date | datetime): Fecha final del rango.
            agrupar (str): Granularidad de agrupación (`"dia"` o `"mes"`).

        Returns:
            list[dict]: Serie temporal ordenada cronológicamente.

        Raises:
            ValueError: Si `agrupar` no es `"dia"` ni `"mes"`.
        """
        if agrupar not in ("dia", "mes"):
            raise ValueError('agrupar debe ser "dia" o "mes"')

        # El formato del periodo viene de esta lista fija, nunca de entrada del usuario (seguro contra SQLi)
        formato = "%Y-%m-%d" if agrupar == "dia" else "%Y-%m"
        inicio, fin = _limites(desde, hasta)

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        # Agrupar ventas válidas usando DATE_FORMAT con el patrón seleccionado
        cursor.execute(f"""
            SELECT DATE_FORMAT(pe.fecha_pedido, '{formato}') AS periodo,
                   COALESCE(SUM(pe.total), 0) AS total,
                   COUNT(pe.id_pedido) AS pedidos
            FROM pedidos pe
            JOIN estados_pedido es ON pe.id_estado = es.id_estado
            WHERE es.nombre_estado <> %s
              AND pe.fecha_pedido >= %s AND pe.fecha_pedido < %s
              AND (
                NOT EXISTS (SELECT 1 FROM pagos pg WHERE pg.id_pedido = pe.id_pedido)
                OR EXISTS (SELECT 1 FROM pagos pg WHERE pg.id_pedido = pe.id_pedido AND pg.estado = 'completado')
              )
            GROUP BY DATE_FORMAT(pe.fecha_pedido, '{formato}')
            ORDER BY periodo ASC
        """, (ESTADO_CANCELADO, inicio, fin))
        filas = cursor.fetchall()
        cursor.close()
        conn.close()

        # Indexar resultados por etiqueta de periodo para acceso O(1) al rellenar huecos
        por_periodo = {
            fila["periodo"]: {"periodo": fila["periodo"], "total": _a_float(fila["total"]), "pedidos": int(fila["pedidos"])}
            for fila in filas
        }

        if agrupar == "mes":
            return list(por_periodo.values())

        # Modo día: generar un registro por cada día del rango, aunque no haya ventas
        resultado = []
        dia = desde
        while dia <= hasta:
            clave = dia.strftime("%Y-%m-%d")
            resultado.append(por_periodo.get(clave, {"periodo": clave, "total": 0.0, "pedidos": 0}))
            dia += timedelta(days=1)
        return resultado

    @staticmethod
    def productos_mas_vendidos(desde, hasta, limite=10):
        """
        Obtiene el top de productos (sumando todas sus presentaciones/variantes)
        ordenados por unidades vendidas e ingresos generados.

        Args:
            desde (date | datetime): Fecha inicial del rango.
            hasta (date | datetime): Fecha final del rango.
            limite (int, optional): Máximo de productos a devolver. Por defecto 10.

        Returns:
            list[dict]: Lista con `{producto, unidades, ingresos}`.
        """
        inicio, fin = _limites(desde, hasta)
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT p.nombre_producto AS producto,
                   SUM(pd.cantidad) AS unidades,
                   SUM(pd.cantidad * pd.precio_unitario) AS ingresos
            FROM pedido_detalle pd
            JOIN pedidos pe ON pd.id_pedido = pe.id_pedido
            JOIN estados_pedido es ON pe.id_estado = es.id_estado
            JOIN variantes_producto v ON pd.id_variante = v.id_variante
            JOIN productos p ON v.id_producto = p.id_producto
            WHERE es.nombre_estado <> %s
              AND pe.fecha_pedido >= %s AND pe.fecha_pedido < %s
              AND (
                NOT EXISTS (SELECT 1 FROM pagos pg WHERE pg.id_pedido = pe.id_pedido)
                OR EXISTS (SELECT 1 FROM pagos pg WHERE pg.id_pedido = pe.id_pedido AND pg.estado = 'completado')
              )
            GROUP BY p.id_producto, p.nombre_producto
            ORDER BY unidades DESC, ingresos DESC, producto ASC
            LIMIT %s
        """, (ESTADO_CANCELADO, inicio, fin, int(limite)))
        filas = cursor.fetchall()
        cursor.close()
        conn.close()

        # Formatear valores numéricos para consumo directo en vistas y exportaciones
        return [
            {"producto": f["producto"], "unidades": int(f["unidades"]), "ingresos": _a_float(f["ingresos"])}
            for f in filas
        ]

    @staticmethod
    def inventario_critico():
        """
        Lista las variantes de productos activos cuyo stock es menor o igual
        al stock mínimo configurado, ordenadas de menor a mayor stock.

        Returns:
            list[dict]: Lista de variantes en riesgo con columna calculada `faltante`.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT p.nombre_producto AS producto, v.presentacion, v.sku,
                   v.stock, v.stock_minimo,
                   (v.stock_minimo - v.stock) AS faltante
            FROM variantes_producto v
            JOIN productos p ON v.id_producto = p.id_producto
            WHERE p.activo = TRUE AND v.stock <= v.stock_minimo
            ORDER BY v.stock ASC, p.nombre_producto ASC, v.presentacion ASC
        """)
        filas = cursor.fetchall()
        cursor.close()
        conn.close()
        return filas

    @staticmethod
    def valor_inventario():
        """
        Calcula el valor total del inventario activo multiplicando `stock * precio`
        de todas las variantes de productos activos.

        Returns:
            float: Valor monetario total del inventario redondeado a 2 decimales.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT COALESCE(SUM(v.stock * v.precio), 0) AS valor
            FROM variantes_producto v
            JOIN productos p ON v.id_producto = p.id_producto
            WHERE p.activo = TRUE
        """)
        fila = cursor.fetchone()
        cursor.close()
        conn.close()
        return _a_float(fila["valor"])

    @staticmethod
    def compras_vs_ventas(desde, hasta):
        """
        Compara el total de ventas válidas frente a las compras a proveedores
        registradas por `fecha_compra` dentro del rango especificado.

        Args:
            desde (date | datetime): Fecha inicial del rango.
            hasta (date | datetime): Fecha final del rango.

        Returns:
            dict: Diccionario con `ventas`, `compras`, `diferencia` y `num_compras`.
        """
        inicio, fin = _limites(desde, hasta)
        # Reutilizar la lógica de resumen_ventas para mantener consistencia en los filtros
        ventas = Reporte.resumen_ventas(desde, hasta)["total_vendido"]

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT COALESCE(SUM(total), 0) AS total, COUNT(id_compra) AS num_compras
            FROM compras
            WHERE fecha_compra >= %s AND fecha_compra < %s
        """, (inicio, fin))
        fila = cursor.fetchone()
        cursor.close()
        conn.close()

        compras = _a_float(fila["total"])
        return {
            "ventas": ventas,
            "compras": compras,
            "diferencia": round(ventas - compras, 2),
            "num_compras": int(fila["num_compras"]),
        }
