from app.utils.db import get_connection


class Usuario:
    def __init__(self, id_usuario, nombre, apellido, email, password_hash,
                 telefono, id_rol, activo, fecha_registro):
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
    def crear(nombre, apellido, email, password_hash, telefono, id_rol=1):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO usuarios (nombre, apellido, email, password_hash, telefono, id_rol)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (nombre, apellido, email, password_hash, telefono, id_rol)
        )
        conn.commit()
        nuevo_id = cursor.lastrowid
        cursor.close()
        conn.close()
        return nuevo_id

    @staticmethod
    def obtener_por_email(email):
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM usuarios WHERE email = %s", (email,))
        usuario = cursor.fetchone()
        cursor.close()
        conn.close()
        return usuario

    @staticmethod
    def obtener_por_id(id_usuario):
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
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
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
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE usuarios SET id_rol = %s WHERE id_usuario = %s", (id_rol, id_usuario))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def toggle_activo(id_usuario):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE usuarios SET activo = NOT activo WHERE id_usuario = %s", (id_usuario,))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def obtener_roles():
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM roles ORDER BY id_rol ASC")
        roles = cursor.fetchall()
        cursor.close()
        conn.close()
        return roles

    @staticmethod
    def actualizar(id_usuario, nombre, apellido, telefono, email, contraseña=None):
        conn = get_connection()
        cursor = conn.cursor()
        
        if contraseña:
            # Generar hash de la nueva contraseña
            import hashlib
            password_hash = hashlib.sha256(contraseña.encode()).hexdigest()
            cursor.execute("""
                UPDATE usuarios
                SET nombre = %s, apellido = %s, telefono = %s, email = %s, password_hash = %s
                WHERE id_usuario = %s
            """, (nombre, apellido, telefono, email, password_hash, id_usuario))
        else:
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
        """Verifica si la contraseña ingresada coincide con el hash almacenado."""
        import hashlib
        hash_ingresado = hashlib.sha256(contraseña_ingresada.encode()).hexdigest()
        return hash_ingresado == password_hash
