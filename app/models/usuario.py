"""
Modelo de Usuarios.

Este módulo gestiona la tabla `usuarios` y su relación con `roles`,
cubriendo registro, autenticación por hash de contraseña (Werkzeug),
consulta de perfil, listado administrativo y cambio de rol/estado.
"""

# Función para obtener una conexión activa a MySQL
from app.utils.db import get_connection


class Usuario:
    """
    Modelo que representa a un usuario del sistema (cliente o administrador).
    """

    def __init__(self, id_usuario, nombre, apellido, email, password_hash,
                 telefono, id_rol, activo, fecha_registro):
        """
        Inicializa una instancia en memoria de Usuario con sus atributos principales.

        Args:
            id_usuario (int): Identificador único del usuario.
            nombre (str): Nombre del usuario.
            apellido (str): Apellido del usuario.
            email (str): Correo electrónico único.
            password_hash (str): Contraseña encriptada (hash).
            telefono (str): Teléfono de contacto.
            id_rol (int): ID del rol asignado.
            activo (bool | int): Indica si la cuenta está habilitada.
            fecha_registro (datetime): Fecha y hora de creación de la cuenta.
        """
        self.id_usuario = id_usuario
        self.nombre = nombre
        self.apellido = apellido
        self.email = email
        self.password_hash = password_hash
        self.telefono = telefono
        self.id_rol = id_rol
        self.activo = activo
        self.fecha_registro = fecha_registro

    @staticmethod
    def crear(nombre, apellido, email, password_hash, telefono, id_rol=1, fecha_nacimiento=None):
        """
        Inserta un nuevo usuario en la base de datos.

        Incluye compatibilidad con esquemas antiguos que no tengan la columna
        `fecha_nacimiento` capturando el código de error MySQL 1054 (Unknown column).

        Args:
            nombre (str): Nombre del usuario.
            apellido (str): Apellido del usuario.
            email (str): Correo electrónico.
            password_hash (str): Hash seguro de la contraseña.
            telefono (str): Número telefónico.
            id_rol (int, optional): Rol inicial (por defecto 1 = cliente).
            fecha_nacimiento (date | str, optional): Fecha de nacimiento para verificación de edad.

        Returns:
            int: ID autogenerado del usuario creado.
        """
        import mysql.connector
        conn = get_connection()
        cursor = conn.cursor()
        try:
            try:
                # Intentar inserción completa incluyendo fecha_nacimiento
                cursor.execute(
                    """INSERT INTO usuarios (nombre, apellido, email, password_hash, telefono, id_rol, fecha_nacimiento)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (nombre, apellido, email, password_hash, telefono, id_rol, fecha_nacimiento)
                )
            except mysql.connector.Error as err:
                # Si la columna fecha_nacimiento no existe en una base de datos antigua (errno 1054)
                if err.errno == 1054:
                    cursor.execute(
                        """INSERT INTO usuarios (nombre, apellido, email, password_hash, telefono, id_rol)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (nombre, apellido, email, password_hash, telefono, id_rol)
                    )
                else:
                    # Propagar cualquier otro error de MySQL (ej. correo duplicado)
                    raise
            conn.commit()
            nuevo_id = cursor.lastrowid
            return nuevo_id
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def obtener_por_email(email):
        """
        Busca un usuario por su correo electrónico (usado en login y validación de registro).

        Args:
            email (str): Correo electrónico a buscar.

        Returns:
            dict | None: Diccionario con todas las columnas del usuario o None si no existe.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM usuarios WHERE email = %s", (email,))
        usuario = cursor.fetchone()
        cursor.close()
        conn.close()
        return usuario

    @staticmethod
    def obtener_por_id(id_usuario):
        """
        Obtiene los datos de un usuario por su ID junto con el nombre de su rol.

        Args:
            id_usuario (int): Identificador único del usuario.

        Returns:
            dict | None: Diccionario con los datos del usuario y `nombre_rol`, o None.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT u.*, r.nombre_rol
            FROM usuarios u
            JOIN roles r ON u.id_rol = r.id_rol
            WHERE u.id_usuario = %s
        """, (id_usuario,))
        usuario = cursor.fetchone()
        cursor.close()
        conn.close()
        return usuario

    @staticmethod
    def listar_todos():
        """
        Lista todos los usuarios para el panel administrativo, incluyendo su rol
        y el total de pedidos que han realizado.

        Returns:
            list[dict]: Lista de usuarios ordenados del más reciente al más antiguo.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        # Subconsulta correlacionada para contar pedidos por usuario sin alterar el agrupamiento
        cursor.execute("""
            SELECT u.id_usuario, u.nombre, u.apellido, u.email, u.telefono,
                   u.id_rol, u.activo, u.fecha_registro,
                   r.nombre_rol,
                   (SELECT COUNT(*) FROM pedidos p WHERE p.id_usuario = u.id_usuario) AS total_pedidos
            FROM usuarios u
            JOIN roles r ON u.id_rol = r.id_rol
            ORDER BY u.id_usuario DESC
        """)
        usuarios = cursor.fetchall()
        cursor.close()
        conn.close()
        return usuarios

    @staticmethod
    def actualizar_rol(id_usuario, id_rol):
        """
        Cambia el rol asignado a un usuario.

        Args:
            id_usuario (int): ID del usuario.
            id_rol (int): Nuevo ID de rol a asignar.
        """
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE usuarios SET id_rol = %s WHERE id_usuario = %s", (id_rol, id_usuario))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def toggle_activo(id_usuario):
        """
        Habilita o deshabilita la cuenta de un usuario invirtiendo el campo `activo`.

        Args:
            id_usuario (int): ID del usuario a conmutar.
        """
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE usuarios SET activo = NOT activo WHERE id_usuario = %s", (id_usuario,))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def obtener_roles():
        """
        Obtiene el catálogo completo de roles disponibles ordenados por ID.

        Returns:
            list[dict]: Lista de diccionarios con los roles del sistema.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM roles ORDER BY id_rol ASC")
        roles = cursor.fetchall()
        cursor.close()
        conn.close()
        return roles

    @staticmethod
    def actualizar(id_usuario, nombre, apellido, telefono, email, contraseña=None):
        """
        Actualiza los datos de perfil de un usuario y, opcionalmente, su contraseña.

        Si se provee `contraseña`, se genera un nuevo hash seguro con Werkzeug
        antes de persistirlo en la base de datos.

        Args:
            id_usuario (int): ID del usuario a actualizar.
            nombre (str): Nuevo nombre.
            apellido (str): Nuevo apellido.
            telefono (str): Nuevo teléfono.
            email (str): Nuevo correo electrónico.
            contraseña (str, optional): Nueva contraseña en texto plano para hashear.
        """
        from werkzeug.security import generate_password_hash
        conn = get_connection()
        cursor = conn.cursor()

        if contraseña:
            # Generar hash de la nueva contraseña con werkzeug (nunca guardar texto plano)
            password_hash = generate_password_hash(contraseña)
            cursor.execute("""
                UPDATE usuarios
                SET nombre = %s, apellido = %s, telefono = %s, email = %s, password_hash = %s
                WHERE id_usuario = %s
            """, (nombre, apellido, telefono, email, password_hash, id_usuario))
        else:
            # Actualizar solo los datos de perfil conservando el password_hash actual
            cursor.execute("""
                UPDATE usuarios
                SET nombre = %s, apellido = %s, telefono = %s, email = %s
                WHERE id_usuario = %s
            """, (nombre, apellido, telefono, email, id_usuario))

        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def verificar_contraseña(contraseña_ingresada, password_hash):
        """
        Verifica si la contraseña ingresada coincide con el hash almacenado.

        Args:
            contraseña_ingresada (str): Contraseña en texto plano enviada por el usuario.
            password_hash (str): Hash almacenado en la base de datos.

        Returns:
            bool: True si la contraseña coincide, False en caso contrario.
        """
        from werkzeug.security import check_password_hash
        return check_password_hash(password_hash, contraseña_ingresada)
