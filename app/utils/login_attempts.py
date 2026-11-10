"""
Helper para controlar intentos de login
Mantiene un registro en memoria de intentos fallidos por IP+email
"""

import math
import time
from collections import defaultdict

# Almacenamiento en memoria: {(ip, email): {'intentos': count, 'ultimo_intento': timestamp}}
_login_attempts = defaultdict(dict)

MAX_ATTEMPTS = 5
BLOCK_TIME = 300  # 5 minutos en segundos


def check_login_attempt(ip, email):
    """
    Verifica si la combinación IP+email está bloqueada por demasiados intentos
    
    Returns:
        True si puede intentar login, False si está bloqueado
    """
    key = (ip, email)
    now = time.time()
    
    if key in _login_attempts:
        attempts_data = _login_attempts[key]
        
        # Si ha pasado el tiempo de bloqueo, reiniciar contador
        if now - attempts_data['ultimo_intento'] > BLOCK_TIME:
            del _login_attempts[key]
            return True
        
        # Si ha alcanzado el máximo de intentos, bloquear
        if attempts_data['intentos'] >= MAX_ATTEMPTS:
            return False
    
    return True


def record_failed_attempt(ip, email):
    """Registra un intento fallido de login"""
    key = (ip, email)
    now = time.time()
    
    if key in _login_attempts:
        # Reiniciar si ha pasado el tiempo de bloqueo
        if now - _login_attempts[key]['ultimo_intento'] > BLOCK_TIME:
            _login_attempts[key] = {'intentos': 1, 'ultimo_intento': now}
        else:
            _login_attempts[key]['intentos'] += 1
            _login_attempts[key]['ultimo_intento'] = now
    else:
        _login_attempts[key] = {'intentos': 1, 'ultimo_intento': now}


def reset_login_attempts(ip, email):
    """Reinicia el contador de intentos cuando el login es exitoso"""
    key = (ip, email)
    if key in _login_attempts:
        del _login_attempts[key]


def get_remaining_time(ip, email):
    """Obtiene el tiempo restante de bloqueo en segundos"""
    key = (ip, email)
    if key in _login_attempts:
        attempts_data = _login_attempts[key]
        if attempts_data['intentos'] >= MAX_ATTEMPTS:
            elapsed = time.time() - attempts_data['ultimo_intento']
            remaining = BLOCK_TIME - elapsed
            return max(0, math.ceil(remaining))
    return 0
