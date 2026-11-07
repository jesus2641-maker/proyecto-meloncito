"""
Script para verificar el estado del usuario administrador
"""

from app.utils.db import get_connection

def verificar_usuario_admin():
    """Verifica el rol del usuario admin@beerhouse.com"""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Verificar usuario admin
    cursor.execute("""
        SELECT id_usuario, nombre, apellido, email, id_rol, activo
        FROM usuarios 
        WHERE email = 'admin@beerhouse.com'
    """)
    usuario = cursor.fetchone()
    
    if usuario:
        print("Usuario admin encontrado:")
        print(f"  ID: {usuario['id_usuario']}")
        print(f"  Nombre: {usuario['nombre']} {usuario['apellido']}")
        print(f"  Email: {usuario['email']}")
        print(f"  Rol ID: {usuario['id_rol']}")
        print(f"  Activo: {usuario['activo']}")
        
        # Verificar qué rol corresponde al ID
        cursor.execute("SELECT * FROM roles WHERE id_rol = %s", (usuario['id_rol'],))
        rol = cursor.fetchone()
        print(f"  Nombre del rol: {rol['nombre_rol']}")
        
        if usuario['id_rol'] != 2:
            print("\n[ERROR] El usuario no tiene rol de administrador (id_rol debe ser 2)")
            print("Intentando corregir...")
            cursor.execute("UPDATE usuarios SET id_rol = 2 WHERE email = 'admin@beerhouse.com'")
            conn.commit()
            print("Rol corregido a administrador")
        else:
            print("\n[OK] El usuario tiene el rol correcto de administrador")
    else:
        print("[ERROR] No se encontró el usuario admin@beerhouse.com")
    
    # Verificar todos los usuarios
    cursor.execute("SELECT id_usuario, email, id_rol FROM usuarios")
    usuarios = cursor.fetchall()
    print("\nTodos los usuarios:")
    for u in usuarios:
        cursor.execute("SELECT nombre_rol FROM roles WHERE id_rol = %s", (u['id_rol'],))
        rol = cursor.fetchone()
        print(f"  {u['email']} - Rol: {rol['nombre_rol']} (ID: {u['id_rol']})")
    
    cursor.close()
    conn.close()

if __name__ == "__main__":
    verificar_usuario_admin()
