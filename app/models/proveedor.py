from app.utils.db import get_connection


class Proveedor:
    """
    Modelo para la gestión de proveedores.
    Contiene únicamente los datos indispensables de identificación.
    No incluye observaciones, email, teléfono ni dirección.
    """

    @staticmethod
    def listar(activos_solo=False, busqueda=None):
        """Devuelve la lista de proveedores con conteo de compras asociadas."""
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT p.id_proveedor, p.nombre, p.identificacion, p.activo, p.fecha_registro,
                   COUNT(c.id_compra) AS total_compras,
                   COALESCE(SUM(c.total), 0) AS total_monto_compras
            FROM proveedores p
            LEFT JOIN compras c ON p.id_proveedor = c.id_proveedor
            WHERE 1=1
        """
        params = []
        if activos_solo:
            query += " AND p.activo = TRUE"
        if busqueda:
            query += " AND (p.nombre LIKE %s OR p.identificacion LIKE %s)"
            b_param = f"%{busqueda}%"
            params.extend([b_param, b_param])

        query += """
            GROUP BY p.id_proveedor, p.nombre, p.identificacion, p.activo, p.fecha_registro
            ORDER BY p.nombre ASC
        """
        cursor.execute(query, params)
        proveedores = cursor.fetchall()
        cursor.close()
        conn.close()
        return proveedores

    @staticmethod
    def obtener_por_id(id_proveedor):
        """Obtiene un proveedor por su ID con estadísticas de compras."""
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT p.id_proveedor, p.nombre, p.identificacion, p.activo, p.fecha_registro,
                   COUNT(c.id_compra) AS total_compras,
                   COALESCE(SUM(c.total), 0) AS total_monto_compras
            FROM proveedores p
            LEFT JOIN compras c ON p.id_proveedor = c.id_proveedor
            WHERE p.id_proveedor = %s
            GROUP BY p.id_proveedor, p.nombre, p.identificacion, p.activo, p.fecha_registro
        """, (id_proveedor,))
        proveedor = cursor.fetchone()
        cursor.close()
        conn.close()
        return proveedor

    @staticmethod
    def crear(nombre, identificacion=None):
        """Registra un nuevo proveedor."""
        nombre = (nombre or "").strip()
        identificacion = (identificacion or "").strip() or None

        if not nombre:
            raise ValueError("El nombre del proveedor es obligatorio")

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO proveedores (nombre, identificacion)
               VALUES (%s, %s)""",
            (nombre, identificacion)
        )
        conn.commit()
        nuevo_id = cursor.lastrowid
        cursor.close()
        conn.close()
        return nuevo_id

    @staticmethod
    def actualizar(id_proveedor, nombre, identificacion=None, activo=True):
        """Actualiza los datos de un proveedor existente."""
        nombre = (nombre or "").strip()
        identificacion = (identificacion or "").strip() or None

        if not nombre:
            raise ValueError("El nombre del proveedor es obligatorio")

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE proveedores
            SET nombre = %s, identificacion = %s, activo = %s
            WHERE id_proveedor = %s
        """, (nombre, identificacion, 1 if activo else 0, id_proveedor))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def toggle_activo(id_proveedor):
        """Activa o desactiva un proveedor."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE proveedores SET activo = NOT activo WHERE id_proveedor = %s", (id_proveedor,))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def eliminar(id_proveedor):
        """
        Elimina un proveedor si no tiene compras registradas.
        Si tiene compras, lanza ValueError para preservar la integridad referencial.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT COUNT(*) AS total FROM compras WHERE id_proveedor = %s", (id_proveedor,))
            res = cursor.fetchone()
            total_compras = res["total"] if res else 0

            if total_compras > 0:
                raise ValueError(
                    f"No se puede eliminar el proveedor porque tiene {total_compras} compra(s) registrada(s). "
                    "Para preservar el historial contable, desactívalo en su lugar."
                )

            cursor.execute("DELETE FROM proveedores WHERE id_proveedor = %s", (id_proveedor,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            cursor.close()
            conn.close()
