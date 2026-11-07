"""
Modelo de Reportes - Consultas de solo lectura para el módulo de reportes del administrador.

Reglas generales:
- Las ventas EXCLUYEN los pedidos cancelados (se une con estados_pedido por nombre).
- El rango de fechas es inclusivo: fecha >= desde AND fecha < hasta + 1 día.
- Los montos se devuelven como float redondeado a 2 decimales (listos para gráficas y CSV).
"""

from datetime import timedelta

from app.utils.db import get_connection

# Nombre del estado que se excluye de las ventas (tabla estados_pedido)
ESTADO_CANCELADO = "cancelado"


def _a_float(valor):
    """Convierte un Decimal/None de MySQL a float con 2 decimales."""
    return round(float(valor or 0), 2)


def _limites(desde, hasta):
    """Límites de la consulta: (desde, hasta + 1 día) para que `hasta` quede incluido."""
    return desde, hasta + timedelta(days=1)


class Reporte:
    @staticmethod
    def resumen_ventas(desde, hasta):
        """Total vendido, número de pedidos y ticket promedio del rango (sin cancelados)."""
        inicio, fin = _limites(desde, hasta)
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT COALESCE(SUM(pe.total), 0) AS total_vendido,
                   COUNT(pe.id_pedido) AS num_pedidos,
                   COALESCE(AVG(pe.total), 0) AS ticket_promedio
            FROM pedidos pe
            JOIN estados_pedido es ON pe.id_estado = es.id_estado
            WHERE es.nombre_estado <> %s
              AND pe.fecha_pedido >= %s AND pe.fecha_pedido < %s
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
        Ventas agrupadas por "dia" o "mes": lista de {periodo, total, pedidos}.
        En modo "dia" se rellenan con 0 los días sin ventas para que la gráfica sea continua.
        """
        if agrupar not in ("dia", "mes"):
            raise ValueError('agrupar debe ser "dia" o "mes"')

        # El formato del periodo viene de esta lista fija, nunca del usuario
        formato = "%Y-%m-%d" if agrupar == "dia" else "%Y-%m"
        inicio, fin = _limites(desde, hasta)

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(f"""
            SELECT DATE_FORMAT(pe.fecha_pedido, '{formato}') AS periodo,
                   COALESCE(SUM(pe.total), 0) AS total,
                   COUNT(pe.id_pedido) AS pedidos
            FROM pedidos pe
            JOIN estados_pedido es ON pe.id_estado = es.id_estado
            WHERE es.nombre_estado <> %s
              AND pe.fecha_pedido >= %s AND pe.fecha_pedido < %s
            GROUP BY DATE_FORMAT(pe.fecha_pedido, '{formato}')
            ORDER BY periodo ASC
        """, (ESTADO_CANCELADO, inicio, fin))
        filas = cursor.fetchall()
        cursor.close()
        conn.close()

        por_periodo = {
            fila["periodo"]: {"periodo": fila["periodo"], "total": _a_float(fila["total"]), "pedidos": int(fila["pedidos"])}
            for fila in filas
        }

        if agrupar == "mes":
            return list(por_periodo.values())

        # Modo día: un registro por cada día del rango, aunque no haya ventas
        resultado = []
        dia = desde
        while dia <= hasta:
            clave = dia.strftime("%Y-%m-%d")
            resultado.append(por_periodo.get(clave, {"periodo": clave, "total": 0.0, "pedidos": 0}))
            dia += timedelta(days=1)
        return resultado

    @staticmethod
    def productos_mas_vendidos(desde, hasta, limite=10):
        """Top de productos (suma de todas sus presentaciones) por unidades vendidas."""
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
            GROUP BY p.id_producto, p.nombre_producto
            ORDER BY unidades DESC, ingresos DESC, producto ASC
            LIMIT %s
        """, (ESTADO_CANCELADO, inicio, fin, int(limite)))
        filas = cursor.fetchall()
        cursor.close()
        conn.close()

        return [
            {"producto": f["producto"], "unidades": int(f["unidades"]), "ingresos": _a_float(f["ingresos"])}
            for f in filas
        ]

    @staticmethod
    def inventario_critico():
        """Variantes de productos activos con stock <= stock mínimo, de menor a mayor stock."""
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
        """Valor del inventario: suma de stock * precio de las variantes de productos activos."""
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
        """Ventas (sin cancelados) frente a compras a proveedores (por fecha_compra) del rango."""
        inicio, fin = _limites(desde, hasta)
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
