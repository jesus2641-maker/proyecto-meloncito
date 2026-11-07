"""
Pruebas de validación de nombre comercial de proveedor (sin base de datos).

Ejecutar:  python -m unittest tests.test_validaciones
"""

import unittest

from app.utils.validaciones import MAX_NOMBRE_PROVEEDOR, validar_nombre_comercial


class TestValidarNombreComercial(unittest.TestCase):
    def test_nombres_comerciales_validos(self):
        nombres_validos = [
            "Bavaria S.A.",
            "Licores 24 Horas",
            "Distribuidora J&M",
            "Ñandú & Hijos Ltda.",
            "Importadora O'Hara - Sucursal Norte (Calle 10 / Local 2), S.A.S.",
            "AB",
            "A" * MAX_NOMBRE_PROVEEDOR,
        ]
        for nombre in nombres_validos:
            with self.subTest(nombre=nombre):
                valido, mensaje = validar_nombre_comercial(nombre)
                self.assertTrue(valido, f"Debería ser válido: {nombre!r} ({mensaje})")
                self.assertIsNone(mensaje)

    def test_vacio_es_invalido(self):
        for vacio in ("", "   ", None):
            with self.subTest(vacio=vacio):
                valido, mensaje = validar_nombre_comercial(vacio)
                self.assertFalse(valido)
                self.assertIsNotNone(mensaje)

    def test_un_solo_caracter_es_invalido(self):
        for corto in ("A", "1", " X "):
            with self.subTest(corto=corto):
                valido, mensaje = validar_nombre_comercial(corto)
                self.assertFalse(valido)
                self.assertIn("2", mensaje)

    def test_nombre_con_script_o_caracteres_peligrosos_es_invalido(self):
        invalidos = [
            "<script>alert(1)</script>",
            "Proveedor <script>",
            "Empresa $100",
            "Proveedor @correo",
            "Nombre; DROP TABLE proveedores;",
        ]
        for nombre in invalidos:
            with self.subTest(nombre=nombre):
                valido, mensaje = validar_nombre_comercial(nombre)
                self.assertFalse(valido)
                self.assertIsNotNone(mensaje)

    def test_nombre_mas_largo_que_la_columna_es_invalido(self):
        self.assertEqual(MAX_NOMBRE_PROVEEDOR, 150)
        demasiado_largo = "A" * (MAX_NOMBRE_PROVEEDOR + 1)
        valido, mensaje = validar_nombre_comercial(demasiado_largo)
        self.assertFalse(valido)
        self.assertIn("150", mensaje)


if __name__ == "__main__":
    unittest.main()
