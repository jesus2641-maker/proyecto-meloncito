"""
Helper para controlar intentos fallidos de inicio de sesión (protección contra fuerza bruta).

Mantiene un registro en memoria por proceso usando la tupla `(ip, email)` como clave.
Nota educativa: al estar en memoria, el contador es local al worker/proceso actual
y se reinicia si el servidor se reinicia.
"""

import math
import time
from collections import defaultdict

# Almacenamiento en memoria: {(ip, email): {'intentos': count, 'ultimo_intento': timestamp}}
_login_attempts = defaultdict(dict)

# Número máximo de intentos fallidos consecutivos antes de activar el bloqueo temporal
MAX_ATTEMPTS = 5
# Duración del bloqueo temporal en segundos (300 s = 5 minutos)
BLOCK_TIME = 300  # 5 minutos en segundos


def check_login_attempt(ip, email):
    """
    Verifica si la combinación IP+email está bloqueada por demasiados intentos fallidos.

    Si el tiempo de bloqueo (`BLOCK_TIME`) ya transcurrió desde el último intento,
    limpia automáticamente el registro y permite intentar de nuevo.

    Args:
        ip (str): Dirección IP del cliente que intenta autenticarse.
        email (str): Correo electrónico ingresado en el formulario de login.

    Returns:
        bool: `True` si puede intentar iniciar sesión, `False` si está bloqueado.
    """
    # Clave compuesta para aislar intentos por origen (IP) y cuenta objetivo (email)
    key = (ip, email)
    now = time.time()
    
    if key in _login_attempts:
        attempts_data = _login_attempts[key]
        
        # Si ya expiró la ventana de bloqueo, eliminamos el registro y permitimos el intento
        if now - attempts_data['ultimo_intento'] > BLOCK_TIME:
            del _login_attempts[key]
            return True
        
        # Si alcanzó o superó el máximo de intentos dentro de la ventana, denegamos el acceso
        if attempts_data['intentos'] >= MAX_ATTEMPTS:
            return False
    
    return True


def record_failed_attempt(ip, email):
    """
    Registra un intento fallido de inicio de sesión para la combinación IP+email.

    Si la ventana anterior ya expiró, reinicia el contador en 1; de lo contrario,
    incrementa el contador y actualiza la marca de tiempo del último intento.

    Args:
        ip (str): Dirección IP del cliente.
        email (str): Correo electrónico utilizado en el intento fallido.
    """
    key = (ip, email)
    now = time.time()
    
    if key in _login_attempts:
        # Si ya pasó el tiempo de bloqueo previo, comenzamos un nuevo ciclo con 1 intento
        if now - _login_attempts[key]['ultimo_intento'] > BLOCK_TIME:
            _login_attempts[key] = {'intentos': 1, 'ultimo_intento': now}
        else:
            # Dentro de la ventana activa: incrementamos el contador y refrescamos timestamp
            _login_attempts[key]['intentos'] += 1
            _login_attempts[key]['ultimo_intento'] = now
    else:
        # Primer intento fallido registrado para esta clave
        _login_attempts[key] = {'intentos': 1, 'ultimo_intento': now}


def reset_login_attempts(ip, email):
    """
    Reinicia (elimina) el contador de intentos fallidos cuando el login es exitoso.

    Args:
        ip (str): Dirección IP del cliente.
        email (str): Correo electrónico autenticado correctamente.
    """
    key = (ip, email)
    if key in _login_attempts:
        del _login_attempts[key]


def get_remaining_time(ip, email):
    """
    Obtiene el tiempo restante de bloqueo en segundos para una combinación IP+email.

    Args:
        ip (str): Dirección IP del cliente.
        email (str): Correo electrónico bloqueado.

    Returns:
        int: Segundos restantes redondeados hacia arriba (`0` si no está bloqueado).
    """
    key = (ip, email)
    if key in _login_attempts:
        attempts_data = _login_attempts[key]
        # Solo calculamos tiempo restante si efectivamente alcanzó el umbral de bloqueo
        if attempts_data['intentos'] >= MAX_ATTEMPTS:
            elapsed = time.time() - attempts_data['ultimo_intento']
            remaining = BLOCK_TIME - elapsed
            # `math.ceil` evita mostrar "0 segundos" cuando aún quedan fracciones de segundo
            return max(0, math.ceil(remaining))
    return 0
