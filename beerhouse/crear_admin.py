"""
Script para crear o restablecer un usuario administrador.
Uso: python crear_admin.py
"""
from werkzeug.security import generate_password_hash
from app.utils.db import get_connection

EMAIL = "admin@beerhouse.com"
PASSWORD = "admin123"
NOMBRE = "Admin"
APELLIDO = "Beer House"
TELEFONO = None
ID_ROL_ADMIN = 2


def main():
    password_hash = generate_password_hash(PASSWORD)
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT id_usuario FROM usuarios WHERE email = %s", (EMAIL,))
    existente = cursor.fetchone()

    if existente:
        cursor.execute(
            "UPDATE usuarios SET password_hash = %s, id_rol = %s WHERE email = %s",
            (password_hash, ID_ROL_ADMIN, EMAIL),
        )
        print(f"Usuario admin actualizado: {EMAIL}")
    else:
        cursor.execute(
            """INSERT INTO usuarios (nombre, apellido, email, password_hash, telefono, id_rol)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (NOMBRE, APELLIDO, EMAIL, password_hash, TELEFONO, ID_ROL_ADMIN),
        )
        print(f"Usuario admin creado: {EMAIL}")

    conn.commit()
    cursor.close()
    conn.close()

    print(f"\nCredenciales de acceso:")
    print(f"  Email:    {EMAIL}")
    print(f"  Password: {PASSWORD}")
    print(f"\nInicia sesion en /auth/login y luego ve a /admin/dashboard")


if __name__ == "__main__":
    main()
