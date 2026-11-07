"""
Genera datos de demostración (pedidos y compras) para probar los reportes.

Ejecutar desde la raíz del proyecto:
    python -m scripts.generar_datos_demo

- Si la tabla `pedidos` ya tiene registros, NO inserta nada.
- Usa random.seed(42), así que el resultado es reproducible.
- NO modifica el stock de las variantes.
"""

import random
from datetime import datetime, timedelta
from decimal import Decimal

from app.utils.db import get_connection

EMAIL_CLIENTE = "cliente@beerhouse.com"
DIAS_PERIODO = 60

# Cantidad de pedidos por estado (en total 30). Los nombres son los de estados_pedido.
PEDIDOS_POR_ESTADO = {
    "entregado": 17,
    "confirmado": 4,
    "en camino": 3,
    "pendiente": 3,
    "cancelado": 3,
}

# Hasta cuántos días atrás puede estar un pedido según su estado
# (los pedidos pendientes o en camino tienen sentido solo si son recientes)
DIAS_MAXIMOS_POR_ESTADO = {
    "pendiente": 3,
    "en camino": 5,
    "confirmado": 10,
    "entregado": DIAS_PERIODO - 1,
    "cancelado": DIAS_PERIODO - 1,
}


def fecha_aleatoria(ahora, dias_maximos):
    """Fecha y hora aleatoria entre hace `dias_maximos` días y hoy (en horario comercial)."""
    dias_atras = random.randint(0, dias_maximos)
    fecha = ahora - timedelta(days=dias_atras)
    fecha = fecha.replace(hour=random.randint(9, 21), minute=random.randint(0, 59), second=random.randint(0, 59))
    # Un pedido no puede quedar en el futuro (pasa si hoy se genera antes de las 9 am)
    return min(fecha, ahora)


def obtener_o_crear_direccion(cursor, id_usuario):
    """Reutiliza una dirección del cliente; si no tiene, crea una."""
    cursor.execute(
        "SELECT id_direccion FROM direcciones WHERE id_usuario = %s ORDER BY es_principal DESC, id_direccion LIMIT 1",
        (id_usuario,)
    )
    fila = cursor.fetchone()
    if fila:
        return fila["id_direccion"]
    cursor.execute(
        """INSERT INTO direcciones (id_usuario, alias, linea_direccion, ciudad, departamento, es_principal)
           VALUES (%s, 'Casa', 'Calle 10 # 20-30', 'Bogotá', 'Cundinamarca', TRUE)""",
        (id_usuario,)
    )
    return cursor.lastrowid


def obtener_o_crear_metodo_pago(cursor, id_usuario):
    """Reutiliza un método de pago del cliente; si no tiene, crea uno."""
    cursor.execute(
        "SELECT id_metodo_pago FROM metodos_pago WHERE id_usuario = %s ORDER BY es_predeterminado DESC, id_metodo_pago LIMIT 1",
        (id_usuario,)
    )
    fila = cursor.fetchone()
    if fila:
        return fila["id_metodo_pago"]
    cursor.execute(
        "INSERT INTO metodos_pago (id_usuario, tipo, detalle, es_predeterminado) VALUES (%s, 'Efectivo', 'Pago contra entrega', TRUE)",
        (id_usuario,)
    )
    return cursor.lastrowid


def obtener_usuario_para_compras(cursor, id_cliente):
    """Usuario que registra las compras: un administrador (si no hay, el cliente)."""
    cursor.execute(
        """SELECT u.id_usuario FROM usuarios u
           JOIN roles r ON u.id_rol = r.id_rol
           WHERE r.nombre_rol = 'administrador'
           ORDER BY u.id_usuario LIMIT 1"""
    )
    fila = cursor.fetchone()
    return fila["id_usuario"] if fila else id_cliente


def crear_pedidos(cursor, id_cliente, variantes, estados, ahora):
    """Inserta ~30 pedidos con sus detalles. Devuelve cuántos insertó."""
    id_direccion = obtener_o_crear_direccion(cursor, id_cliente)
    id_metodo_pago = obtener_o_crear_metodo_pago(cursor, id_cliente)

    # Lista de estados (uno por pedido) mezclada con la semilla fija
    estados_a_crear = []
    for nombre_estado, cantidad in PEDIDOS_POR_ESTADO.items():
        estados_a_crear.extend([nombre_estado] * cantidad)
    random.shuffle(estados_a_crear)

    for nombre_estado in estados_a_crear:
        fecha = fecha_aleatoria(ahora, DIAS_MAXIMOS_POR_ESTADO[nombre_estado])

        # Entre 1 y 4 productos distintos, de 1 a 3 unidades cada uno
        elegidas = random.sample(variantes, k=random.randint(1, min(4, len(variantes))))
        detalles = [(v["id_variante"], random.randint(1, 3), v["precio"]) for v in elegidas]
        total = sum(cantidad * precio for _, cantidad, precio in detalles)

        cursor.execute(
            """INSERT INTO pedidos (id_usuario, id_direccion, id_metodo_pago, id_estado, total, fecha_pedido)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (id_cliente, id_direccion, id_metodo_pago, estados[nombre_estado], total, fecha)
        )
        id_pedido = cursor.lastrowid

        for id_variante, cantidad, precio in detalles:
            cursor.execute(
                """INSERT INTO pedido_detalle (id_pedido, id_variante, cantidad, precio_unitario)
                   VALUES (%s, %s, %s, %s)""",
                (id_pedido, id_variante, cantidad, precio)
            )

    return len(estados_a_crear)


def crear_compras(cursor, id_usuario, variantes, ahora, total_compras=3):
    """Inserta compras a proveedores (si no hay proveedores, crea 2). Devuelve cuántas insertó."""
    cursor.execute("SELECT id_proveedor FROM proveedores WHERE activo = TRUE ORDER BY id_proveedor")
    proveedores = [fila["id_proveedor"] for fila in cursor.fetchall()]

    if not proveedores:
        for nombre, identificacion in (("Distribuidora Andina", "NIT 900.111.222-1"),
                                       ("Licores del Valle", "NIT 900.333.444-2")):
            cursor.execute("INSERT INTO proveedores (nombre, identificacion) VALUES (%s, %s)", (nombre, identificacion))
            proveedores.append(cursor.lastrowid)

    for _ in range(total_compras):
        fecha = fecha_aleatoria(ahora, DIAS_PERIODO - 1)
        elegidas = random.sample(variantes, k=random.randint(2, min(4, len(variantes))))

        # El costo de compra es ~60% del precio de venta
        detalles = []
        for v in elegidas:
            cantidad = random.randint(10, 50)
            costo = (v["precio"] * Decimal("0.6")).quantize(Decimal("0.01"))
            detalles.append((v["id_variante"], cantidad, costo, cantidad * costo))
        total = sum(subtotal for *_, subtotal in detalles)

        cursor.execute(
            "INSERT INTO compras (id_proveedor, id_usuario, fecha_compra, total) VALUES (%s, %s, %s, %s)",
            (random.choice(proveedores), id_usuario, fecha, total)
        )
        id_compra = cursor.lastrowid

        for id_variante, cantidad, costo, subtotal in detalles:
            cursor.execute(
                """INSERT INTO compra_detalle (id_compra, id_variante, cantidad, precio_unitario, subtotal)
                   VALUES (%s, %s, %s, %s, %s)""",
                (id_compra, id_variante, cantidad, costo, subtotal)
            )

    return total_compras


def main():
    random.seed(42)
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT COUNT(*) AS total FROM pedidos")
        if cursor.fetchone()["total"] > 0:
            print("Ya existen pedidos en la base de datos. No se insertó nada.")
            return

        cursor.execute("SELECT id_usuario FROM usuarios WHERE email = %s", (EMAIL_CLIENTE,))
        cliente = cursor.fetchone()
        if not cliente:
            print(f"No existe el usuario {EMAIL_CLIENTE}. Cárgalo con database/seed_data.sql. No se insertó nada.")
            return

        cursor.execute(
            """SELECT v.id_variante, v.precio
               FROM variantes_producto v
               JOIN productos p ON v.id_producto = p.id_producto
               WHERE p.activo = TRUE
               ORDER BY v.id_variante"""
        )
        variantes = cursor.fetchall()
        if not variantes:
            print("No hay variantes de productos activos. No se insertó nada.")
            return

        cursor.execute("SELECT id_estado, nombre_estado FROM estados_pedido")
        estados = {fila["nombre_estado"]: fila["id_estado"] for fila in cursor.fetchall()}
        faltantes = [nombre for nombre in PEDIDOS_POR_ESTADO if nombre not in estados]
        if faltantes:
            print(f"Faltan estados en estados_pedido: {', '.join(faltantes)}. No se insertó nada.")
            return

        ahora = datetime.now()
        id_cliente = cliente["id_usuario"]

        # Todo en una sola transacción: o se insertan pedidos y compras, o nada
        pedidos = crear_pedidos(cursor, id_cliente, variantes, estados, ahora)
        compras = crear_compras(cursor, obtener_usuario_para_compras(cursor, id_cliente), variantes, ahora)
        conn.commit()

        print(f"Datos de demostración creados: {pedidos} pedidos y {compras} compras.")
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
