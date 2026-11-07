"""
Pruebas de app/utils/reportes_utils.py (sin base de datos).

Ejecutar:  python -m unittest tests.test_reportes

Se fija `hoy` en cada prueba para que no dependan del día en que se corran.
"""

import os
import unittest
from datetime import date, timedelta
from decimal import Decimal

# config.py exige SECRET_KEY al importarse; se define un valor de prueba si no hay .env
os.environ.setdefault("SECRET_KEY", "clave-de-prueba-solo-para-tests-0123456789")

from app.utils.reportes_utils import (
    elegir_agrupacion,
    generar_csv,
    parsear_rango_fechas,
)

HOY = date(2026, 6, 15)


class TestParsearRangoFechas(unittest.TestCase):
    def test_rango_por_defecto(self):
        """Sin datos: primer día del mes actual hasta hoy."""
        desde, hasta, error = parsear_rango_fechas("", "", hoy=HOY)
        self.assertEqual(desde, date(2026, 6, 1))
        self.assertEqual(hasta, HOY)
        self.assertIsNone(error)

        desde, hasta, error = parsear_rango_fechas(None, None, hoy=HOY)
        self.assertEqual((desde, hasta, error), (date(2026, 6, 1), HOY, None))

    def test_primer_dia_del_mes_el_dia_uno(self):
        desde, hasta, error = parsear_rango_fechas("", "", hoy=date(2026, 3, 1))
        self.assertEqual((desde, hasta, error), (date(2026, 3, 1), date(2026, 3, 1), None))

    def test_rango_valido(self):
        desde, hasta, error = parsear_rango_fechas("2026-05-01", "2026-05-31", hoy=HOY)
        self.assertEqual(desde, date(2026, 5, 1))
        self.assertEqual(hasta, date(2026, 5, 31))
        self.assertIsNone(error)

    def test_un_solo_dia(self):
        desde, hasta, error = parsear_rango_fechas("2026-05-10", "2026-05-10", hoy=HOY)
        self.assertEqual((desde, hasta, error), (date(2026, 5, 10), date(2026, 5, 10), None))

    def test_solo_desde_usa_hoy_como_hasta(self):
        desde, hasta, error = parsear_rango_fechas("2026-06-10", "", hoy=HOY)
        self.assertEqual((desde, hasta, error), (date(2026, 6, 10), HOY, None))

    def test_formato_invalido_usa_defaults_y_da_error(self):
        for desde_str, hasta_str in [
            ("15/05/2026", "2026-05-31"),
            ("2026-05-01", "mañana"),
            ("2026-13-01", "2026-05-31"),
            ("2026-02-30", "2026-05-31"),
            ("2026-5-1", "2026-05-31"),
        ]:
            with self.subTest(desde=desde_str, hasta=hasta_str):
                desde, hasta, error = parsear_rango_fechas(desde_str, hasta_str, hoy=HOY)
                self.assertEqual((desde, hasta), (date(2026, 6, 1), HOY))
                self.assertIn("formato", error)

    def test_desde_mayor_que_hasta(self):
        desde, hasta, error = parsear_rango_fechas("2026-06-10", "2026-06-01", hoy=HOY)
        self.assertEqual((desde, hasta), (date(2026, 6, 1), HOY))
        self.assertIn("posterior", error)

    def test_rango_maximo_366_dias(self):
        # Exactamente 366 días (contando ambos extremos): permitido
        inicio = date(2025, 6, 15)
        fin = inicio + timedelta(days=365)
        desde, hasta, error = parsear_rango_fechas(inicio.isoformat(), fin.isoformat(), hoy=HOY)
        self.assertEqual((desde, hasta, error), (inicio, fin, None))

        # 367 días: rechazado, vuelve a los valores por defecto
        fin = inicio + timedelta(days=366)
        desde, hasta, error = parsear_rango_fechas(inicio.isoformat(), fin.isoformat(), hoy=HOY)
        self.assertEqual((desde, hasta), (date(2026, 6, 1), HOY))
        self.assertIn("366", error)

    def test_rango_de_varios_anios_es_rechazado(self):
        _, _, error = parsear_rango_fechas("2020-01-01", "2026-06-15", hoy=HOY)
        self.assertIsNotNone(error)


class TestElegirAgrupacion(unittest.TestCase):
    def test_un_dia_es_dia(self):
        self.assertEqual(elegir_agrupacion(HOY, HOY), "dia")

    def test_limite_62_dias_es_dia(self):
        desde = date(2026, 1, 1)
        self.assertEqual(elegir_agrupacion(desde, desde + timedelta(days=61)), "dia")   # 62 días

    def test_63_dias_es_mes(self):
        desde = date(2026, 1, 1)
        self.assertEqual(elegir_agrupacion(desde, desde + timedelta(days=62)), "mes")   # 63 días

    def test_rango_largo_es_mes(self):
        self.assertEqual(elegir_agrupacion(date(2025, 6, 15), date(2026, 6, 15)), "mes")


class TestGenerarCsv(unittest.TestCase):
    def test_delimitador_punto_y_coma_y_tildes(self):
        csv_texto = generar_csv(
            ["Producto", "Presentación", "Unidades"],
            [["Ron Zacapa", "750ml", 3], ["Piña colada", "1L", 12]],
        )
        lineas = csv_texto.strip().split("\r\n")
        self.assertEqual(lineas[0], "Producto;Presentación;Unidades")
        self.assertEqual(lineas[1], "Ron Zacapa;750ml;3")
        self.assertEqual(lineas[2], "Piña colada;1L;12")

    def test_numeros_no_se_tocan(self):
        csv_texto = generar_csv(["a", "b", "c", "d"], [[-5, 3.5, Decimal("-2.50"), 0]])
        self.assertEqual(csv_texto.strip().split("\r\n")[1], "-5;3.5;-2.50;0")

    def test_proteccion_contra_formulas(self):
        peligrosos = ["=SUMA(A1:A2)", "+57300123456", "-1+1", "@cmd", '=HYPERLINK("http://x")']
        csv_texto = generar_csv(["col"], [[p] for p in peligrosos])
        lineas = csv_texto.strip().split("\r\n")[1:]
        self.assertEqual(lineas[0], "'=SUMA(A1:A2)")
        self.assertEqual(lineas[1], "'+57300123456")
        self.assertEqual(lineas[2], "'-1+1")
        self.assertEqual(lineas[3], "'@cmd")
        # El texto con comillas y ';' lo entrecomilla el módulo csv, pero conserva el apóstrofo inicial
        self.assertTrue(lineas[4].lstrip('"').startswith("'="))

    def test_proteccion_tambien_en_encabezados(self):
        csv_texto = generar_csv(["=malo", "bueno"], [])
        self.assertEqual(csv_texto.strip(), "'=malo;bueno")

    def test_texto_normal_no_lleva_apostrofo(self):
        csv_texto = generar_csv(["col"], [["Whisky-12"], ["a=b"]])
        lineas = csv_texto.strip().split("\r\n")[1:]
        self.assertEqual(lineas, ["Whisky-12", "a=b"])

    def test_celda_con_delimitador_se_entrecomilla(self):
        csv_texto = generar_csv(["col"], [["uno; dos"]])
        self.assertEqual(csv_texto.strip().split("\r\n")[1], '"uno; dos"')

    def test_none_y_fechas(self):
        csv_texto = generar_csv(["a", "b"], [[None, date(2026, 6, 15)]])
        self.assertEqual(csv_texto.strip().split("\r\n")[1], ";2026-06-15")

    def test_sin_filas_solo_encabezados(self):
        self.assertEqual(generar_csv(["a", "b"], []), "a;b\r\n")


if __name__ == "__main__":
    unittest.main()
