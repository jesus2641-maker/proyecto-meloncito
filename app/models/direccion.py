"""
Modelo de Direcciones de envío.

Este módulo gestiona las direcciones registradas por los clientes en la tabla
`direcciones`, permitiendo crear, listar, consultar y eliminar direcciones,
asegurando una única dirección principal por usuario cuando corresponda.
"""

# Función para obtener una conexión activa a MySQL
from app.utils.db import get_connection


class Direccion:
    """
    Modelo para administrar las direcciones de entrega de los usuarios.
    """

    @staticmethod
    def crear(id_usuario, linea_direccion, ciudad, departamento=None, codigo_postal=None, alias=None, es_principal=0):
        """
        Crea una nueva dirección de envío para un usuario.

        Si `es_principal` es verdadero, desmarca previamente las demás direcciones
        del mismo usuario para mantener la unicidad de la dirección principal.

        Args:
            id_usuario (int): ID del usuario propietario.
            linea_direccion (str): Dirección física (calle, número, apartamento, etc.).
            ciudad (str): Ciudad de entrega.
            departamento (str, optional): Departamento o estado.
            codigo_postal (str, optional): Código postal.
            alias (str, optional): Nombre corto identificativo (ej. "Casa", "Oficina").
            es_principal (int | bool, optional): Indica si es la dirección predeterminada.

        Returns:
            int: ID autogenerado de la nueva dirección.
        """
        conn = get_connection()
        cursor = conn.cursor()

        # Si se marca como principal, desmarcar las demás direcciones del usuario
        if es_principal:
            cursor.execute(
                "UPDATE direcciones SET es_principal = 0 WHERE id_usuario = %s",
                (id_usuario,)
            )

        # Insertar la nueva dirección normalizando `es_principal` a 1 o 0
        cursor.execute("""
            INSERT INTO direcciones (id_usuario, alias, linea_direccion, ciudad, departamento, codigo_postal, es_principal)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (id_usuario, alias, linea_direccion, ciudad, departamento, codigo_postal, 1 if es_principal else 0))
        conn.commit()
        id_direccion = cursor.lastrowid
        cursor.close()
        conn.close()
        return id_direccion

    @staticmethod
    def listar_por_usuario(id_usuario):
        """
        Lista todas las direcciones de un usuario, priorizando la principal
        y luego las más recientes.

        Args:
            id_usuario (int): ID del usuario.

        Returns:
            list[dict]: Lista de diccionarios con las direcciones del usuario.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        # Ordenar primero por es_principal DESC para que la predeterminada aparezca primero
        cursor.execute("""
            SELECT * FROM direcciones
            WHERE id_usuario = %s
            ORDER BY es_principal DESC, id_direccion DESC
        """, (id_usuario,))
        direcciones = cursor.fetchall()
        cursor.close()
        conn.close()
        return direcciones

    @staticmethod
    def obtener_por_id(id_direccion):
        """
        Obtiene una dirección específica por su ID.

        Args:
            id_direccion (int): ID de la dirección.

        Returns:
            dict | None: Diccionario con los datos de la dirección o None si no existe.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM direcciones WHERE id_direccion = %s", (id_direccion,))
        direccion = cursor.fetchone()
        cursor.close()
        conn.close()
        return direccion

    @staticmethod
    def eliminar(id_direccion, id_usuario):
        """
        Elimina una dirección verificando que pertenezca al usuario indicado.

        Args:
            id_direccion (int): ID de la dirección a eliminar.
            id_usuario (int): ID del usuario propietario (control de autorización).

        Returns:
            bool: True si se eliminó algún registro, False en caso contrario.
        """
        conn = get_connection()
        cursor = conn.cursor()
        # Filtrar por id_direccion e id_usuario evita que un usuario borre direcciones ajenas
        cursor.execute(
            "DELETE FROM direcciones WHERE id_direccion = %s AND id_usuario = %s",
            (id_direccion, id_usuario)
        )
        conn.commit()
        eliminado = cursor.rowcount > 0
        cursor.close()
        conn.close()
        return eliminado
