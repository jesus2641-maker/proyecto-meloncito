"""
Diagnóstico de stock real en la base de datos de Beer House.
Ejecuta la consulta de variantes y productos e imprime una tabla legible y un resumen.
"""

import sys
import os
from pathlib import Path

# Asegurar que el directorio raíz esté en sys.path
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app.utils.db import get_connection
from config import Config


def diagnosticar_stock():
    print("=" * 75)
    print("DIAGNÓSTICO DE STOCK DE VARIANTES - BEER HOUSE")
    print(f"Base de datos configurada (Config.DATABASE_NAME): {Config.DATABASE_NAME}")
    print("=" * 75)

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT DATABASE()")
        db_actual = cursor.fetchone()
        nombre_bd = list(db_actual.values())[0] if db_actual else "Desconocida"
        print(f"Conectado a BD: {nombre_bd}\n")

        query = """
            SELECT v.id_variante, p.nombre_producto, v.presentacion, v.stock
            FROM variantes_producto v
            JOIN productos p ON p.id_producto = v.id_producto
            ORDER BY v.id_variante ASC;
        """
        cursor.execute(query)
        filas = cursor.fetchall()
        cursor.close()
        conn.close()

        total = len(filas)
        con_stock = 0
        stock_cero = 0
        stock_null = 0

        # Formato de tabla legible en consola
        print(f"{'ID':<6} | {'Producto':<32} | {'Presentación':<16} | {'Stock':<10}")
        print("-" * 75)

        for f in filas:
            stock = f["stock"]
            if stock is None:
                stock_null += 1
                stock_str = "NULL"
            else:
                try:
                    s_int = int(stock)
                    if s_int > 0:
                        con_stock += 1
                        stock_str = str(s_int)
                    else:
                        stock_cero += 1
                        stock_str = str(s_int)
                except (ValueError, TypeError):
                    stock_cero += 1
                    stock_str = str(stock)

            prod_nombre = (f["nombre_producto"][:30] + "..") if len(f["nombre_producto"]) > 32 else f["nombre_producto"]
            print(f"{f['id_variante']:<6} | {prod_nombre:<32} | {f['presentacion']:<16} | {stock_str:<10}")

        print("-" * 75)
        print("RESUMEN DE STOCK:")
        print(f"  • Total de variantes analizadas: {total}")
        print(f"  • Variantes con stock > 0:       {con_stock}")
        print(f"  • Variantes con stock = 0:       {stock_cero}")
        print(f"  • Variantes con stock NULL:      {stock_null}")
        print("=" * 75)

        return {
            "total": total,
            "con_stock": con_stock,
            "stock_cero": stock_cero,
            "stock_null": stock_null,
            "database": nombre_bd
        }

    except Exception as e:
        print(f"Error al conectar o consultar la base de datos: {e}")
        raise


if __name__ == "__main__":
    diagnosticar_stock()
