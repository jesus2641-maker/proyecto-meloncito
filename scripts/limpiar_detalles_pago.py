"""
Script de limpieza de detalles de métodos de pago en la base de datos.

Busca en `metodos_pago.detalle` todos los valores que contengan 12 o más dígitos
(por ejemplo, números completos de tarjeta guardados en texto claro), pide
confirmación por consola mediante `input()` y los reemplaza por:
    "Terminada en " + últimos 4 dígitos

Ejecutar desde la raíz del proyecto:
    python -m scripts.limpiar_detalles_pago
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.utils.db import get_connection


def extraer_digitos(texto):
    """Extrae todos los caracteres numéricos de una cadena."""
    if not texto:
        return ""
    return "".join(c for c in str(texto) if c.isdigit())


def limpiar_detalles_pago():
    """
    Reemplaza en `metodos_pago.detalle` todo valor con 12 o más dígitos por
    'Terminada en <últimos 4 dígitos>' previa confirmación del usuario.
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            "SELECT id_metodo_pago, id_usuario, tipo, detalle "
            "FROM metodos_pago WHERE detalle IS NOT NULL"
        )
        filas = cursor.fetchall()

        candidatos = []
        for fila in filas:
            digitos = extraer_digitos(fila.get("detalle"))
            if len(digitos) >= 12:
                nuevo_detalle = "Terminada en " + digitos[-4:]
                candidatos.append((fila, nuevo_detalle))

        if not candidatos:
            print("No se encontraron métodos de pago con 12 o más dígitos en detalle. Filas cambiadas: 0")
            return 0

        print(f"Se encontraron {len(candidatos)} registro(s) con 12 o más dígitos en metodos_pago.detalle.")
        respuesta = input("¿Deseas reemplazarlos por 'Terminada en <últimos 4 dígitos>'? (s/N): ").strip().lower()
        if respuesta not in ("s", "si", "sí", "y", "yes"):
            print("Operación cancelada por el usuario. Filas cambiadas: 0")
            return 0

        cambiadas = 0
        for fila, nuevo_detalle in candidatos:
            cursor.execute(
                "UPDATE metodos_pago SET detalle = %s WHERE id_metodo_pago = %s",
                (nuevo_detalle, fila["id_metodo_pago"]),
            )
            cambiadas += cursor.rowcount

        conn.commit()
        print(f"Limpieza completada. Filas cambiadas: {cambiadas}")
        return cambiadas
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    limpiar_detalles_pago()
