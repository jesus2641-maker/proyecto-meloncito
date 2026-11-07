"""
Pruebas de la verificación de mayoría de edad (sin base de datos).

Ejecutar:  python -m unittest tests.test_edad

Se fija la fecha de referencia con el parámetro `hoy` para que las pruebas
no dependan del día en que se corran.
"""

import os
import unittest
from datetime import date

# config.py exige SECRET_KEY al importarse; se define un valor de prueba si no hay .env
os.environ.setdefault("SECRET_KEY", "clave-de-prueba-solo-para-tests-0123456789")

from app.utils.validaciones import (
    EDAD_MINIMA,
    calcular_edad,
    fecha_maxima_nacimiento,
    validar_fecha_nacimiento,
)
from app.routes.edad import ruta_segura

MENSAJE_MENOR = "Debes ser mayor de 18 años para registrarte"

# Fecha fija de referencia para todas las pruebas
HOY = date(2026, 6, 15)


class TestCalcularEdad(unittest.TestCase):
    def test_cumple_hoy(self):
        """Quien cumple 18 hoy ya tiene 18 años."""
        self.assertEqual(calcular_edad(date(2008, 6, 15), HOY), 18)

    def test_cumple_manana(self):
        """Quien cumple 18 mañana todavía tiene 17."""
        self.assertEqual(calcular_edad(date(2008, 6, 16), HOY), 17)

    def test_cumple_ayer(self):
        """El cumpleaños ya pasó este año."""
        self.assertEqual(calcular_edad(date(2008, 6, 14), HOY), 18)

    def test_cumple_mes_anterior_y_posterior(self):
        self.assertEqual(calcular_edad(date(1990, 1, 1), HOY), 36)
        self.assertEqual(calcular_edad(date(1990, 12, 31), HOY), 35)

    def test_recien_nacido(self):
        self.assertEqual(calcular_edad(HOY, HOY), 0)

    def test_nacido_29_febrero(self):
        """Quien nace un 29 de febrero cumple años el 1 de marzo en años no bisiestos."""
        nacimiento = date(2000, 2, 29)
        self.assertEqual(calcular_edad(nacimiento, date(2018, 2, 28)), 17)
        self.assertEqual(calcular_edad(nacimiento, date(2018, 3, 1)), 18)
        # En año bisiesto el cumpleaños es el 29 de febrero
        self.assertEqual(calcular_edad(nacimiento, date(2020, 2, 29)), 20)

    def test_usa_fecha_actual_por_defecto(self):
        """Sin parámetro hoy no falla y devuelve un entero."""
        self.assertIsInstance(calcular_edad(date(1990, 1, 1)), int)


class TestValidarFechaNacimiento(unittest.TestCase):
    def test_justo_18_hoy_es_valido(self):
        valido, mensaje, fecha = validar_fecha_nacimiento("2008-06-15", hoy=HOY)
        self.assertTrue(valido)
        self.assertIsNone(mensaje)
        self.assertEqual(fecha, date(2008, 6, 15))

    def test_cumple_18_manana_es_rechazado(self):
        valido, mensaje, fecha = validar_fecha_nacimiento("2008-06-16", hoy=HOY)
        self.assertFalse(valido)
        self.assertEqual(mensaje, MENSAJE_MENOR)
        self.assertIsNone(fecha)

    def test_17_anios_es_rechazado(self):
        valido, mensaje, fecha = validar_fecha_nacimiento("2009-06-15", hoy=HOY)
        self.assertFalse(valido)
        self.assertEqual(mensaje, MENSAJE_MENOR)
        self.assertIsNone(fecha)

    def test_mayor_de_edad_es_valido(self):
        valido, mensaje, fecha = validar_fecha_nacimiento("1990-05-15", hoy=HOY)
        self.assertTrue(valido)
        self.assertIsNone(mensaje)
        self.assertEqual(fecha, date(1990, 5, 15))

    def test_nacido_hoy_es_rechazado_como_menor(self):
        """Nacer hoy no es fecha futura, pero sí es menor de edad."""
        valido, mensaje, fecha = validar_fecha_nacimiento("2026-06-15", hoy=HOY)
        self.assertFalse(valido)
        self.assertEqual(mensaje, MENSAJE_MENOR)
        self.assertIsNone(fecha)

    def test_fecha_futura_es_rechazada(self):
        valido, mensaje, fecha = validar_fecha_nacimiento("2026-06-16", hoy=HOY)
        self.assertFalse(valido)
        self.assertIn("futura", mensaje)
        self.assertIsNone(fecha)

        valido, mensaje, fecha = validar_fecha_nacimiento("2099-01-01", hoy=HOY)
        self.assertFalse(valido)
        self.assertIsNone(fecha)

    def test_formato_invalido_es_rechazado(self):
        invalidos = [
            "15/05/1990",    # día/mes/año
            "1990/05/15",    # separador incorrecto
            "1990-5-15",     # sin ceros
            "no es fecha",
            "19900515",
            "1990-13-01",    # mes inexistente
            "2023-02-30",    # día inexistente
            "1990-05-15 ",   # se limpia el espacio, así que este SÍ es válido (ver abajo)
        ]
        # Todos menos el último (espacio al final, que se recorta) deben fallar
        for texto in invalidos[:-1]:
            with self.subTest(texto=texto):
                valido, mensaje, fecha = validar_fecha_nacimiento(texto, hoy=HOY)
                self.assertFalse(valido)
                self.assertIn("formato", mensaje)
                self.assertIsNone(fecha)

        valido, _, _ = validar_fecha_nacimiento(invalidos[-1], hoy=HOY)
        self.assertTrue(valido)

    def test_vacio_es_rechazado(self):
        for texto in ("", "   ", None):
            with self.subTest(texto=texto):
                valido, mensaje, fecha = validar_fecha_nacimiento(texto, hoy=HOY)
                self.assertFalse(valido)
                self.assertIn("obligatoria", mensaje)
                self.assertIsNone(fecha)

    def test_nacido_29_febrero(self):
        """Nacido el 29/02/2000: cumple 18 el 1 de marzo de 2018 (año no bisiesto)."""
        valido, mensaje, _ = validar_fecha_nacimiento("2000-02-29", hoy=date(2018, 2, 28))
        self.assertFalse(valido)
        self.assertEqual(mensaje, MENSAJE_MENOR)

        valido, mensaje, fecha = validar_fecha_nacimiento("2000-02-29", hoy=date(2018, 3, 1))
        self.assertTrue(valido)
        self.assertEqual(fecha, date(2000, 2, 29))

    def test_29_febrero_inexistente_es_rechazado(self):
        """El 29/02/2001 no existe (2001 no es bisiesto)."""
        valido, mensaje, fecha = validar_fecha_nacimiento("2001-02-29", hoy=HOY)
        self.assertFalse(valido)
        self.assertIn("formato", mensaje)
        self.assertIsNone(fecha)

    def test_mayor_de_120_anios_es_rechazado(self):
        # 121 años cumplidos
        valido, mensaje, fecha = validar_fecha_nacimiento("1905-06-14", hoy=HOY)
        self.assertFalse(valido)
        self.assertIn("no es válida", mensaje)
        self.assertIsNone(fecha)

        valido, _, _ = validar_fecha_nacimiento("1800-01-01", hoy=HOY)
        self.assertFalse(valido)

    def test_exactamente_120_anios_es_valido(self):
        valido, mensaje, fecha = validar_fecha_nacimiento("1906-06-15", hoy=HOY)
        self.assertTrue(valido)
        self.assertIsNone(mensaje)
        self.assertEqual(fecha, date(1906, 6, 15))

    def test_edad_minima_configurable(self):
        valido, mensaje, _ = validar_fecha_nacimiento("2008-06-15", edad_minima=21, hoy=HOY)
        self.assertFalse(valido)
        self.assertEqual(mensaje, "Debes ser mayor de 21 años para registrarte")

    def test_edad_minima_por_defecto_es_18(self):
        self.assertEqual(EDAD_MINIMA, 18)


class TestFechaMaximaNacimiento(unittest.TestCase):
    def test_hoy_menos_18_anios(self):
        self.assertEqual(fecha_maxima_nacimiento(hoy=HOY), date(2008, 6, 15))

    def test_29_febrero_cae_en_28_febrero(self):
        """El 29/02/2028 menos 18 años (2010, no bisiesto) no existe: se usa el 28/02."""
        self.assertEqual(fecha_maxima_nacimiento(hoy=date(2028, 2, 29)), date(2010, 2, 28))

    def test_es_coherente_con_validar(self):
        """La fecha máxima es válida y el día siguiente ya no lo es."""
        for hoy in (HOY, date(2028, 2, 29), date(2026, 2, 28), date(2026, 3, 1)):
            with self.subTest(hoy=hoy):
                maxima = fecha_maxima_nacimiento(hoy=hoy)
                valido, _, _ = validar_fecha_nacimiento(maxima.isoformat(), hoy=hoy)
                self.assertTrue(valido)

                siguiente = date.fromordinal(maxima.toordinal() + 1)
                valido, _, _ = validar_fecha_nacimiento(siguiente.isoformat(), hoy=hoy)
                self.assertFalse(valido)


class TestRutaSegura(unittest.TestCase):
    """Protección contra open redirect del parámetro `next` de /verificar-edad."""

    def test_rutas_internas_validas(self):
        for destino in ("/", "/productos/", "/productos/3?cat=2", "/ofertas"):
            with self.subTest(destino=destino):
                self.assertEqual(ruta_segura(destino), destino)

    def test_rutas_peligrosas_se_reemplazan_por_inicio(self):
        peligrosas = [
            None,
            "",
            "https://sitio-malo.com",
            "//sitio-malo.com",
            "/\\sitio-malo.com",
            "\\\\sitio-malo.com",
            "productos",
            "javascript:alert(1)",
            "/\t/sitio-malo.com",   # el navegador ignora el tabulador y queda //sitio-malo.com
            "/\n/sitio-malo.com",
        ]
        for destino in peligrosas:
            with self.subTest(destino=destino):
                self.assertEqual(ruta_segura(destino), "/")


if __name__ == "__main__":
    unittest.main()
