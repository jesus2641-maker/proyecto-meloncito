"""
Modelo de Proveedores.

Este módulo gestiona el catálogo de proveedores de abastecimiento en la tabla
`proveedores`, incluyendo validaciones de nombre comercial y protección de
integridad referencial al eliminar proveedores con compras asociadas.
"""

# Función para obtener una conexión activa a MySQL
from app.utils.db import get_connection


class Proveedor:
    """
    Modelo para la gestión de proveedores.
    Permite listar, consultar, crear, actualizar, activar/desactivar y eliminar
    proveedores manteniendo la consistencia del historial de compras.
    """

    @staticmethod
    def listar(activos_solo=False, busqueda=None):
        """
        Devuelve la lista de proveedores con el conteo y monto acumulado de compras asociadas.

        Args:
            activos_solo (bool, optional): Si es True, filtra únicamente proveedores activos.
            busqueda (str, optional): Texto para buscar coincidencia parcial en nombre o identificación.

        Returns:
            list[dict]: Lista de proveedores ordenados alfabéticamente.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        # WHERE 1=1 permite concatenar filtros opcionales dinámicamente de forma limpia
        query = """
            SELECT p.id_proveedor, p.nombre, p.identificacion, p.activo, p.fecha_registro,
                   COUNT(c.id_compra) AS total_compras,
                   COALESCE(SUM(c.total), 0) AS total_monto_compras
            FROM proveedores p
            LEFT JOIN compras c ON p.id_proveedor = c.id_proveedor
            WHERE 1=1
        """
        params = []
        # Aplicar filtro de estado activo si se solicita
        if activos_solo:
            query += " AND p.activo = TRUE"
        # Aplicar filtro de búsqueda por nombre o NIT/identificación usando LIKE
        if busqueda:
            query += " AND (p.nombre LIKE %s OR p.identificacion LIKE %s)"
            b_param = f"%{busqueda}%"
            params.extend([b_param, b_param])

        # Agrupar por proveedor para calcular agregaciones COUNT y SUM
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
        """
        Obtiene un proveedor por su ID junto con sus estadísticas de compras.

        Args:
            id_proveedor (int): Identificador único del proveedor.

        Returns:
            dict | None: Diccionario con datos y totales del proveedor, o None si no existe.
        """
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
        """
        Registra un nuevo proveedor previa validación de su nombre comercial.

        Args:
            nombre (str): Nombre o razón social del proveedor.
            identificacion (str, optional): NIT, RUT o documento de identificación.

        Returns:
            int: ID autogenerado del proveedor recién creado.

        Raises:
            ValueError: Si el nombre comercial no cumple las reglas de validación.
        """
        # Importación local para evitar ciclos entre modelos y validaciones
        from app.utils.validaciones import validar_nombre_comercial

        # Normalizar entradas eliminando espacios sobrantes
        nombre = (nombre or "").strip()
        identificacion = (identificacion or "").strip() or None

        # Validar nombre comercial del proveedor
        nombre_valido, error_msg = validar_nombre_comercial(nombre)
        if not nombre_valido:
            raise ValueError(error_msg)

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
        """
        Actualiza los datos de un proveedor existente con validación del nombre comercial.

        Args:
            id_proveedor (int): ID del proveedor a modificar.
            nombre (str): Nuevo nombre comercial.
            identificacion (str, optional): Nueva identificación o NIT.
            activo (bool, optional): Estado de actividad del proveedor.

        Raises:
            ValueError: Si el nombre comercial no es válido.
        """
        from app.utils.validaciones import validar_nombre_comercial

        # Normalizar cadenas de texto antes de validar
        nombre = (nombre or "").strip()
        identificacion = (identificacion or "").strip() or None

        # Validar nombre comercial del proveedor
        nombre_valido, error_msg = validar_nombre_comercial(nombre)
        if not nombre_valido:
            raise ValueError(error_msg)

        conn = get_connection()
        cursor = conn.cursor()
        # Convertir el booleano `activo` a 1 o 0 para MySQL
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
        """
        Activa o desactiva un proveedor invirtiendo su estado actual.

        Args:
            id_proveedor (int): ID del proveedor a conmutar.
        """
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

        Args:
            id_proveedor (int): ID del proveedor a eliminar.

        Returns:
            bool: True si se eliminó el proveedor, False si no existía.

        Raises:
            ValueError: Si el proveedor tiene compras asociadas en la tabla `compras`.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            # Comprobar si existen compras vinculadas antes de intentar el DELETE
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
            # Asegurar la liberación de recursos en cualquier escenario
            cursor.close()
            conn.close()
