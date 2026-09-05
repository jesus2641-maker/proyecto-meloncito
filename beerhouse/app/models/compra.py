from datetime import datetime
from decimal import Decimal
from app.utils.db import get_connection


class Compra:
    """
    Modelo para la gestión de compras a proveedores.
    Controla el registro de compras, transacciones atómicas y aumento de stock en variantes de producto.
    """

    @staticmethod
    def crear_con_transaccion(id_proveedor, id_usuario, fecha_compra, items):
        """
        Registra una compra completa y sus detalles en una sola transacción atómica.
        Actualiza automáticamente el stock sumando las cantidades compradas.
        Si cualquier paso falla, se revierte toda la transacción (rollback).

        Args:
            id_proveedor (int): ID del proveedor.
            id_usuario (int): ID del usuario que registra la compra.
            fecha_compra (str|datetime): Fecha en que se realizó la compra.
            items (list): Lista de diccionarios [{'id_variante': int, 'cantidad': int, 'precio_unitario': Decimal/float}]

        Returns:
            int: ID de la compra creada.

        Raises:
            ValueError: Si alguna validación de datos o de existencia falla.
            Exception: Si ocurre un error de base de datos durante la transacción.
        """
        # 1. Validaciones básicas de entrada
        if not id_proveedor:
            raise ValueError("Debes seleccionar un proveedor válido.")

        if not id_usuario:
            raise ValueError("No se pudo identificar el usuario que registra la compra.")

        # Si no se especifica fecha, se asigna automáticamente el momento actual
        if not fecha_compra:
            fecha_compra = datetime.now()

        if not items or len(items) == 0:
            raise ValueError("La compra debe incluir al menos un producto.")

        # 2. Validar cada item antes de abrir la transacción
        items_procesados = []
        for index, item in enumerate(items, start=1):
            try:
                id_variante = int(item.get("id_variante"))
            except (TypeError, ValueError):
                raise ValueError(f"Fila {index}: Debes seleccionar un producto válido.")

            try:
                cantidad = int(item.get("cantidad"))
            except (TypeError, ValueError):
                raise ValueError(f"Fila {index}: La cantidad debe ser un número entero.")

            if cantidad <= 0:
                raise ValueError(f"Fila {index}: La cantidad debe ser mayor a 0.")

            try:
                precio_unitario = Decimal(str(item.get("precio_unitario"))).quantize(Decimal("0.01"))
            except Exception:
                raise ValueError(f"Fila {index}: El precio de compra debe ser un valor numérico válido.")

            if precio_unitario <= 0:
                raise ValueError(f"Fila {index}: El precio de compra unitario debe ser mayor a 0.")

            subtotal = (Decimal(cantidad) * precio_unitario).quantize(Decimal("0.01"))
            items_procesados.append({
                "id_variante": id_variante,
                "cantidad": cantidad,
                "precio_unitario": precio_unitario,
                "subtotal": subtotal
            })

        total_compra = sum(it["subtotal"] for it in items_procesados)

        # 3. Transacción atómica en la base de datos
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            # A. Verificar existencia del proveedor
            cursor.execute("SELECT id_proveedor, nombre, activo FROM proveedores WHERE id_proveedor = %s", (id_proveedor,))
            proveedor = cursor.fetchone()
            if not proveedor:
                raise ValueError("El proveedor seleccionado no existe en el sistema.")

            # B. Verificar existencia de cada variante de producto bloqueando filas con FOR UPDATE
            for it in items_procesados:
                cursor.execute(
                    """SELECT v.id_variante, v.id_producto, v.stock, p.nombre_producto, v.presentacion
                       FROM variantes_producto v
                       JOIN productos p ON v.id_producto = p.id_producto
                       WHERE v.id_variante = %s FOR UPDATE""",
                    (it["id_variante"],)
                )
                variante = cursor.fetchone()
                if not variante:
                    raise ValueError(f"El producto con ID de variante {it['id_variante']} no existe.")

            # C. Insertar cabecera de compra
            cursor.execute("""
                INSERT INTO compras (id_proveedor, id_usuario, fecha_compra, total)
                VALUES (%s, %s, %s, %s)
            """, (id_proveedor, id_usuario, fecha_compra, total_compra))
            id_compra = cursor.lastrowid

            # D. Insertar detalles y actualizar stock sumando las cantidades
            for it in items_procesados:
                # Insertar detalle de compra
                cursor.execute("""
                    INSERT INTO compra_detalle (id_compra, id_variante, cantidad, precio_unitario, subtotal)
                    VALUES (%s, %s, %s, %s, %s)
                """, (id_compra, it["id_variante"], it["cantidad"], it["precio_unitario"], it["subtotal"]))

                # Actualizar automáticamente el stock en variantes_producto
                cursor.execute("""
                    UPDATE variantes_producto
                    SET stock = stock + %s
                    WHERE id_variante = %s
                """, (it["cantidad"], it["id_variante"]))

                if cursor.rowcount == 0:
                    raise RuntimeError(f"No fue posible actualizar el stock de la variante {it['id_variante']}.")

            # Confirmar transacción
            conn.commit()
            return id_compra

        except Exception as e:
            # Revertir todos los cambios ante cualquier error
            conn.rollback()
            raise e
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def listar_todas():
        """Lista todas las compras registradas con información de proveedor y totales."""
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT c.id_compra, c.fecha_compra, c.total, c.fecha_registro,
                   p.id_proveedor, p.nombre AS nombre_proveedor, p.identificacion AS identificacion_proveedor,
                   u.id_usuario, u.nombre AS nombre_usuario, u.apellido AS apellido_usuario,
                   COUNT(cd.id_detalle_compra) AS total_items,
                   COALESCE(SUM(cd.cantidad), 0) AS total_unidades
            FROM compras c
            JOIN proveedores p ON c.id_proveedor = p.id_proveedor
            JOIN usuarios u ON c.id_usuario = u.id_usuario
            LEFT JOIN compra_detalle cd ON c.id_compra = cd.id_compra
            GROUP BY c.id_compra, c.fecha_compra, c.total, c.fecha_registro,
                     p.id_proveedor, p.nombre, p.identificacion,
                     u.id_usuario, u.nombre, u.apellido
            ORDER BY c.fecha_compra DESC, c.id_compra DESC
        """)
        compras = cursor.fetchall()
        cursor.close()
        conn.close()
        return compras

    @staticmethod
    def obtener_por_id(id_compra):
        """Obtiene la cabecera de una compra por su ID."""
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT c.id_compra, c.fecha_compra, c.total, c.fecha_registro,
                   p.id_proveedor, p.nombre AS nombre_proveedor, p.identificacion AS identificacion_proveedor,
                   u.id_usuario, u.nombre AS nombre_usuario, u.apellido AS apellido_usuario, u.email AS email_usuario
            FROM compras c
            JOIN proveedores p ON c.id_proveedor = p.id_proveedor
            JOIN usuarios u ON c.id_usuario = u.id_usuario
            WHERE c.id_compra = %s
        """, (id_compra,))
        compra = cursor.fetchone()
        cursor.close()
        conn.close()
        return compra

    @staticmethod
    def obtener_metricas():
        """Obtiene métricas resumidas de compras para widgets del panel."""
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Métricas globales
        cursor.execute("""
            SELECT 
                COALESCE(SUM(total), 0) AS gasto_total,
                COUNT(id_compra) AS total_compras,
                COALESCE(SUM(CASE 
                    WHEN MONTH(fecha_compra) = MONTH(CURRENT_DATE()) 
                     AND YEAR(fecha_compra) = YEAR(CURRENT_DATE()) 
                    THEN total ELSE 0 END), 0) AS gasto_mes_actual,
                COUNT(CASE 
                    WHEN MONTH(fecha_compra) = MONTH(CURRENT_DATE()) 
                     AND YEAR(fecha_compra) = YEAR(CURRENT_DATE()) 
                    THEN 1 END) AS compras_mes_actual
            FROM compras
        """)
        metricas = cursor.fetchone() or {
            "gasto_total": Decimal("0.00"),
            "total_compras": 0,
            "gasto_mes_actual": Decimal("0.00"),
            "compras_mes_actual": 0
        }
        
        cursor.close()
        conn.close()
        return metricas


class CompraDetalle:
    """Modelo para los detalles de una compra (líneas de productos adquiridos)."""

    @staticmethod
    def listar_por_compra(id_compra):
        """Lista todos los productos adquiridos en una compra."""
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT cd.id_detalle_compra, cd.id_compra, cd.id_variante,
                   cd.cantidad, cd.precio_unitario, cd.subtotal,
                   v.presentacion, v.sku, v.stock AS stock_actual, v.precio AS precio_venta,
                   p.id_producto, p.nombre_producto, p.marca, p.imagen_url,
                   c.nombre_categoria
            FROM compra_detalle cd
            JOIN variantes_producto v ON cd.id_variante = v.id_variante
            JOIN productos p ON v.id_producto = p.id_producto
            LEFT JOIN categorias c ON p.id_categoria = c.id_categoria
            WHERE cd.id_compra = %s
            ORDER BY cd.id_detalle_compra ASC
        """, (id_compra,))
        detalles = cursor.fetchall()
        cursor.close()
        conn.close()
        return detalles
