"""
Decoradores de autorización y control de acceso basado en roles (RBAC).

Define las constantes de roles del sistema y los decoradores reutilizables
en las rutas Flask para proteger vistas que requieren sesión iniciada o
permisos específicos (Administrador / Trabajador).
"""

from functools import wraps
from flask import session, redirect, url_for, flash, abort

# Constantes con los IDs numéricos de roles definidos en la tabla `roles` de la BD
# NOTA: Permisos por rol:
# - ID_ROL_CLIENTE (1): compras en tienda, carrito, direcciones, métodos de pago y sus pedidos.
# - ID_ROL_ADMIN (2): acceso total al panel /admin y también puede entrar a /trabajador.
# - ID_ROL_TRABAJADOR (4): acceso al panel /trabajador (pedidos, inventario, consulta de clientes).
ID_ROL_CLIENTE = 1
ID_ROL_ADMIN = 2
ID_ROL_TRABAJADOR = 4


def requiere_login(mensaje="Inicia sesión para acceder a esta página", tipo="warning"):
    """
    Decorador para verificar que el usuario esté autenticado.

    Comprueba la existencia de `"id_usuario"` en la sesión de Flask. Si no hay
    sesión activa, muestra un mensaje flash y redirige a la vista de inicio de sesión.

    Args:
        mensaje (str): Mensaje flash a mostrar al usuario no autenticado.
        tipo (str): Categoría Bootstrap/Flask del mensaje flash (ej. "warning", "danger").

    Returns:
        Callable: Decorador que envuelve la función de vista original.
    """
    def decorator(f):
        # `@wraps(f)` preserva el nombre y docstring de la vista original (clave para Flask)
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Si no existe `id_usuario` en `session`, el usuario no ha iniciado sesión
            if "id_usuario" not in session:
                flash(mensaje, tipo)
                return redirect(url_for("auth.login"))
            # Usuario autenticado: ejecutamos la vista normalmente
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def requiere_admin(mensaje="Acceso denegado: Se requieren permisos de administrador"):
    """
    Decorador para verificar que el usuario tenga rol de administrador.

    Si el `id_rol` almacenado en sesión no coincide con `ID_ROL_ADMIN`, muestra
    un mensaje flash de error y redirige al catálogo de productos.

    Args:
        mensaje (str): Mensaje flash de acceso denegado.

    Returns:
        Callable: Decorador que envuelve la función de vista original.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Verificamos estrictamente que el rol en sesión sea Administrador
            if session.get("id_rol") != ID_ROL_ADMIN:
                flash(mensaje, "danger")
                return redirect(url_for("productos.catalogo"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def requiere_trabajador_o_admin(mensaje="Acceso denegado: Se requieren permisos de trabajador o administrador"):
    """
    Decorador para verificar que el usuario tenga rol de trabajador o administrador.

    Útil para vistas operativas compartidas entre empleados y administradores
    (por ejemplo, gestión de pedidos o inventario).

    Args:
        mensaje (str): Mensaje flash de acceso denegado.

    Returns:
        Callable: Decorador que envuelve la función de vista original.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Obtenemos el rol actual de la sesión y validamos pertenencia a roles autorizados
            rol = session.get("id_rol")
            if rol not in [ID_ROL_TRABAJADOR, ID_ROL_ADMIN]:
                flash(mensaje, "danger")
                return redirect(url_for("productos.catalogo"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def requiere_auth(mensaje="Acceso denegado: Debes iniciar sesión"):
    """
    Decorador para verificar que el usuario esté autenticado (cualquier rol).

    A diferencia de `requiere_login`, utiliza por defecto la categoría `"danger"`
    para el mensaje flash.

    Args:
        mensaje (str): Mensaje flash a mostrar si el usuario no tiene sesión activa.

    Returns:
        Callable: Decorador que envuelve la función de vista original.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Comprobamos presencia de `id_usuario` en la cookie de sesión
            if "id_usuario" not in session:
                flash(mensaje, "danger")
                return redirect(url_for("auth.login"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator
