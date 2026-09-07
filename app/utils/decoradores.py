from functools import wraps
from flask import session, redirect, url_for, flash, abort

# IDs de roles
ID_ROL_CLIENTE = 1
ID_ROL_ADMIN = 2
ID_ROL_TRABAJADOR = 4


def requiere_login(mensaje="Inicia sesión para acceder a esta página", tipo="warning"):
    """
    Decorador para verificar que el usuario esté autenticado.
    Redirige al login si no hay sesión activa.
    
    Args:
        mensaje: Mensaje flash a mostrar (default: "Inicia sesión para acceder a esta página")
        tipo: Tipo de mensaje flash (default: "warning")
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "id_usuario" not in session:
                flash(mensaje, tipo)
                return redirect(url_for("auth.login"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def requiere_admin(mensaje="Acceso denegado: Se requieren permisos de administrador"):
    """
    Decorador para verificar que el usuario tenga rol de administrador.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if session.get("id_rol") != ID_ROL_ADMIN:
                flash(mensaje, "danger")
                return redirect(url_for("productos.catalogo"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def requiere_trabajador_o_admin(mensaje="Acceso denegado: Se requieren permisos de trabajador o administrador"):
    """
    Decorador para verificar que el usuario tenga rol de trabajador o administrador.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
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
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "id_usuario" not in session:
                flash(mensaje, "danger")
                return redirect(url_for("auth.login"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator
