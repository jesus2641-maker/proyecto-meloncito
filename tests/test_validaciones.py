"""
Pruebas de validación de nombre comercial de proveedor (sin base de datos).

Ejecutar:  python -m unittest tests.test_validaciones
"""

import unittest

from app.utils.validaciones import (
    MAX_NOMBRE_PROVEEDOR,
    MAX_DETALLE_PAGO,
    TIPOS_PAGO,
    TIPOS_PAGO_CHECKOUT,
    validar_nombre_comercial,
    validar_tipo_pago,
    validar_tipo_pago_checkout,
    validar_detalle_pago,
    validar_direccion,
)


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


class TestValidarPagosYDirecciones(unittest.TestCase):
    def test_tipos_pago_validos(self):
        self.assertEqual(
            TIPOS_PAGO,
            (
                "Tarjeta de crédito",
                "Tarjeta de débito",
                "Transferencia Bancaria (PSE)",
                "Nequi / Daviplata",
                "Efectivo contra entrega",
                "PayPal",
            ),
        )
        for tipo in TIPOS_PAGO:
            with self.subTest(tipo=tipo):
                ok, err = validar_tipo_pago(tipo)
                self.assertTrue(ok)
                self.assertIsNone(err)

    def test_tipos_pago_invalidos(self):
        invalidos = [
            "",
            "   ",
            None,
            "Bitcoin",
            "X" * 45,  # 45 caracteres (mayor que VARCHAR(30))
        ]
        for tipo in invalidos:
            with self.subTest(tipo=tipo):
                ok, err = validar_tipo_pago(tipo)
                self.assertFalse(ok)
                self.assertIsNotNone(err)

    def test_tipos_pago_checkout_validos(self):
        self.assertEqual(
            TIPOS_PAGO_CHECKOUT,
            ("Efectivo contra entrega", "PayPal"),
        )
        for tipo in TIPOS_PAGO_CHECKOUT:
            with self.subTest(tipo=tipo):
                ok, err = validar_tipo_pago_checkout(tipo)
                self.assertTrue(ok)
                self.assertIsNone(err)

    def test_tipos_pago_checkout_invalidos(self):
        # Opciones que son válidas para cuenta pero no para checkout directo
        rechazados_checkout = [
            "Tarjeta de crédito",
            "Tarjeta de débito",
            "Transferencia Bancaria (PSE)",
            "Nequi / Daviplata",
            "Bitcoin",
            "",
            None,
        ]
        for tipo in rechazados_checkout:
            with self.subTest(tipo=tipo):
                ok, err = validar_tipo_pago_checkout(tipo)
                self.assertFalse(ok)
                self.assertIsNotNone(err)

    def test_detalle_pago_rechaza_tarjetas_completas(self):
        mensaje_esperado = (
            "Por seguridad no ingreses el número completo de la tarjeta; "
            "escribe solo los últimos 4 dígitos (ej. Terminada en 4242)"
        )
        tarjetas = [
            "4111111111111111",
            "4111 1111 1111 1111",
            "4111-1111-1111-1111",
            "Visa 4111 1111 1111 1111",
            "123456789012",  # 12 dígitos
        ]
        for detalle in tarjetas:
            with self.subTest(detalle=detalle):
                ok, err = validar_detalle_pago(detalle)
                self.assertFalse(ok)
                self.assertEqual(err, mensaje_esperado)

    def test_detalle_pago_acepta_valores_validos(self):
        validos = [
            None,
            "",
            "   ",
            "Terminada en 4242",
            "Visa terminada en 4242",
            "Celular 3001234567",  # 10 dígitos (celular Nequi/Daviplata)
            "A" * MAX_DETALLE_PAGO,
        ]
        for detalle in validos:
            with self.subTest(detalle=detalle):
                ok, err = validar_detalle_pago(detalle)
                self.assertTrue(ok, f"Debería ser válido: {detalle!r} ({err})")
                self.assertIsNone(err)

    def test_detalle_pago_rechaza_mas_de_100_caracteres(self):
        ok, err = validar_detalle_pago("A" * (MAX_DETALLE_PAGO + 1))
        self.assertFalse(ok)
        self.assertIn("100", err)

    def test_validar_direccion_limites(self):
        ok, err = validar_direccion("Calle 100 # 15-20", "Bogotá", "Cundinamarca", "110111", "Casa")
        self.assertTrue(ok)
        self.assertIsNone(err)

        # Campos obligatorios
        self.assertFalse(validar_direccion("", "Bogotá")[0])
        self.assertFalse(validar_direccion("Calle 10", "")[0])

        # Exceso de longitud según schema.sql
        self.assertFalse(validar_direccion("Calle 10", "C" * 101)[0])
        self.assertFalse(validar_direccion("Calle 10", "Bogotá", departamento="D" * 101)[0])
        self.assertFalse(validar_direccion("Calle 10", "Bogotá", codigo_postal="1" * 21)[0])
        self.assertFalse(validar_direccion("Calle 10", "Bogotá", alias="A" * 51)[0])
        self.assertFalse(validar_direccion("L" * 501, "Bogotá")[0])


if __name__ == "__main__":
    unittest.main()
