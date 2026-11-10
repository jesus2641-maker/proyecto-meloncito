"""
Pruebas de pagos PayPal (Parte 1: tabla pagos, cliente HTTP y lógica de negocio).
Usa unittest.mock.patch sobre las funciones de paypal_client (sin llamadas reales a internet)
y limpia exactamente todos los datos creados y restaura el stock original.

Ejecutar:  python -m unittest tests.test_pagos
"""

import io
import json
import unittest
import urllib.error
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app import create_app
from app.routes.edad import COOKIE_MAYOR_EDAD
from config import Config, resolver_paypal_api_base, resolver_paypal_mode
from app.models.carrito import Carrito, CarritoItem
from app.models.direccion import Direccion
from app.models.metodo_pago import MetodoPago
from app.models.pago import (
    ESTADO_PAGO_CANCELADO,
    ESTADO_PAGO_COMPLETADO,
    ESTADO_PAGO_PENDIENTE,
    ESTADO_PAGO_REEMBOLSADO,
    Pago,
)
from app.models.pedido import (
    ESTADO_CANCELADO,
    ESTADO_CONFIRMADO,
    ESTADO_PENDIENTE,
    Pedido,
)
from app.models.producto import VarianteProducto
from app.services.pagos_paypal import (
    cancelar_impagos_vencidos,
    cancelar_pedido_con_reembolso,
    capturar_pago,
    iniciar_pago,
)
from app.utils import paypal_client
from app.utils.db import get_connection
from app.utils.paypal_client import (
    PayPalError,
    formatear_monto,
    limpiar_cache_token,
    obtener_url_base,
    paypal_configurado,
)


class TestPayPalClientPuro(unittest.TestCase):
    """Pruebas puras de configuración, URL base, formato de monto y cliente HTTP mockeado."""

    def tearDown(self):
        limpiar_cache_token()

    def test_01_url_base_segun_paypal_mode_y_override(self):
        """1. Obtiene la URL base correcta según PAYPAL_MODE y respeta PAYPAL_API_BASE."""
        self.assertEqual(resolver_paypal_mode("sandbox"), "sandbox")
        self.assertEqual(resolver_paypal_mode("live"), "live")
        self.assertEqual(resolver_paypal_mode("LIVE"), "live")
        self.assertEqual(resolver_paypal_mode("cualquier_otro"), "sandbox")
        self.assertEqual(resolver_paypal_mode(None), "sandbox")

        self.assertEqual(
            obtener_url_base(modo="sandbox", api_base=""),
            "https://api-m.sandbox.paypal.com",
        )
        self.assertEqual(
            obtener_url_base(modo="live", api_base=""),
            "https://api-m.paypal.com",
        )
        self.assertEqual(
            obtener_url_base(modo="production", api_base=""),
            "https://api-m.sandbox.paypal.com",
        )
        self.assertEqual(
            obtener_url_base(modo="sandbox", api_base="https://custom.paypal.local/"),
            "https://custom.paypal.local",
        )

    def test_02_formato_monto_dos_decimales(self):
        """2. Formatea montos como string con 2 decimales exactos ('12.50')."""
        self.assertEqual(formatear_monto(Decimal("12.5")), "12.50")
        self.assertEqual(formatear_monto(12.5), "12.50")
        self.assertEqual(formatear_monto("12.50"), "12.50")
        self.assertEqual(formatear_monto(100), "100.00")
        self.assertEqual(formatear_monto(Decimal("19.995")), "20.00")

        with self.assertRaises(ValueError):
            formatear_monto(0)
        with self.assertRaises(ValueError):
            formatear_monto(-5)
        with self.assertRaises(ValueError):
            formatear_monto("no-numerico")

    def test_03_paypal_configurado_sin_credenciales(self):
        """3. Si faltan CLIENT_ID o SECRET, paypal_configurado() devuelve False sin romper la app."""
        with patch.object(Config, "PAYPAL_CLIENT_ID", ""), patch.object(Config, "PAYPAL_CLIENT_SECRET", ""):
            with patch.dict("os.environ", {"PAYPAL_CLIENT_ID": "", "PAYPAL_CLIENT_SECRET": ""}, clear=False):
                self.assertFalse(paypal_configurado())

        with patch.object(Config, "PAYPAL_CLIENT_ID", "id_test"), patch.object(Config, "PAYPAL_CLIENT_SECRET", "sec_test"):
            self.assertTrue(paypal_configurado())

    @patch("urllib.request.urlopen")
    def test_04_cliente_http_headers_y_payloads_orders_v2(self, mock_urlopen):
        """4. Verifica payloads, headers PayPal-Request-ID y manejo de errores en paypal_client."""
        limpiar_cache_token()

        def crear_respuesta_http(body_dict, status=200):
            resp = MagicMock()
            resp.status = status
            resp.getcode.return_value = status
            resp.read.return_value = json.dumps(body_dict).encode("utf-8")
            resp.__enter__.return_value = resp
            resp.__exit__.return_value = False
            return resp

        mock_urlopen.side_effect = [
            crear_respuesta_http({"access_token": "tok_sandbox_123", "expires_in": 3600}),
            crear_respuesta_http({"id": "ORDER-ABC-123", "status": "CREATED"}, status=201),
            crear_respuesta_http(
                {
                    "id": "ORDER-ABC-123",
                    "status": "COMPLETED",
                    "purchase_units": [
                        {
                            "reference_id": "pedido-77",
                            "custom_id": "77",
                            "payments": {
                                "captures": [
                                    {
                                        "id": "CAP-XYZ-999",
                                        "status": "COMPLETED",
                                        "custom_id": "77",
                                        "amount": {"currency_code": "USD", "value": "45.50"},
                                    }
                                ]
                            },
                        }
                    ],
                },
                status=201,
            ),
            crear_respuesta_http({"id": "REF-555", "status": "COMPLETED"}, status=201),
        ]

        with patch.object(Config, "PAYPAL_CLIENT_ID", "cid_test"), patch.object(
            Config, "PAYPAL_CLIENT_SECRET", "csec_test"
        ):
            order_id = paypal_client.crear_orden(77, Decimal("45.5"), "USD", request_id="req-crear-77")
            self.assertEqual(order_id, "ORDER-ABC-123")

            # Segunda operación reutiliza el token en caché (no vuelve a pedir OAuth2)
            cap = paypal_client.capturar_orden("ORDER-ABC-123", request_id="req-cap-77")
            self.assertEqual(
                cap,
                {
                    "estado": "COMPLETED",
                    "capture_id": "CAP-XYZ-999",
                    "monto": "45.50",
                    "moneda": "USD",
                    "custom_id": "77",
                },
            )

            ref = paypal_client.reembolsar_captura("CAP-XYZ-999", request_id="req-ref-77")
            self.assertEqual(ref, {"estado": "COMPLETED", "refund_id": "REF-555"})

        # Total de llamadas HTTP: 1 (token) + 1 (crear) + 1 (capturar) + 1 (reembolsar) = 4
        self.assertEqual(mock_urlopen.call_count, 4)

        # Revisar payload de crear_orden (segunda llamada a urlopen)
        req_crear = mock_urlopen.call_args_list[1].args[0]
        self.assertEqual(req_crear.get_header("Paypal-request-id"), "req-crear-77")
        payload_crear = json.loads(req_crear.data.decode("utf-8"))
        self.assertEqual(payload_crear["intent"], "CAPTURE")
        pu = payload_crear["purchase_units"][0]
        self.assertEqual(pu["reference_id"], "pedido-77")
        self.assertEqual(pu["custom_id"], "77")
        self.assertEqual(pu["description"], "Pedido #77 Beer House")
        self.assertEqual(pu["amount"], {"currency_code": "USD", "value": "45.50"})
        self.assertEqual(
            payload_crear["payment_source"]["paypal"]["experience_context"]["shipping_preference"],
            "NO_SHIPPING",
        )
        self.assertNotIn("application_context", payload_crear)

    @patch("urllib.request.urlopen")
    def test_05_cliente_http_extrae_codigo_paypal_error(self, mock_urlopen):
        """5. Cuando PayPal devuelve HTTP 422 con INSTRUMENT_DECLINED, lanza PayPalError con ese código."""
        limpiar_cache_token()
        with patch.object(paypal_client, "obtener_token", return_value="tok_test"):
            error_body = json.dumps(
                {
                    "name": "UNPROCESSABLE_ENTITY",
                    "message": "The requested action could not be performed.",
                    "details": [
                        {
                            "issue": "INSTRUMENT_DECLINED",
                            "description": "The instrument presented was either declined by the processor or bank.",
                        }
                    ],
                }
            ).encode("utf-8")
            http_err = urllib.error.HTTPError(
                url="https://api-m.sandbox.paypal.com/v2/checkout/orders/ORD-1/capture",
                code=422,
                msg="Unprocessable Entity",
                hdrs={},
                fp=io.BytesIO(error_body),
            )
            mock_urlopen.side_effect = http_err

            with self.assertRaises(PayPalError) as ctx:
                paypal_client.capturar_orden("ORD-1", request_id="req-err-1")
            self.assertEqual(ctx.exception.codigo, "INSTRUMENT_DECLINED")
            self.assertEqual(ctx.exception.status_code, 422)

    @patch.object(paypal_client, "obtener_token", return_value="tok_test")
    @patch.object(paypal_client, "_ejecutar_peticion")
    def test_06_crear_orden_reintento_exitoso_tras_400_o_422(self, mock_ejecutar, mock_token):
        """6. Si el primer intento de crear_orden falla con HTTP 400 o 422, reintenta con payload mínimo."""
        mock_ejecutar.side_effect = [
            PayPalError("Validation error", codigo="INVALID_REQUEST", status_code=400),
            {"id": "ORD-RETRY-OK", "status": "CREATED"},
        ]
        order_id = paypal_client.crear_orden(88, Decimal("10.00"), "USD", request_id="req-retry-88")
        self.assertEqual(order_id, "ORD-RETRY-OK")
        self.assertEqual(mock_ejecutar.call_count, 2)

        # Primer intento: payload con payment_source
        raw_1 = mock_ejecutar.call_args_list[0].kwargs["raw_data"]
        primer_payload = json.loads(raw_1.decode("utf-8"))
        self.assertIn("payment_source", primer_payload)
        self.assertNotIn("application_context", primer_payload)

        # Segundo intento: payload mínimo (solo intent y purchase_units)
        raw_2 = mock_ejecutar.call_args_list[1].kwargs["raw_data"]
        segundo_payload = json.loads(raw_2.decode("utf-8"))
        self.assertNotIn("payment_source", segundo_payload)
        self.assertNotIn("application_context", segundo_payload)
        self.assertIn("intent", segundo_payload)
        self.assertIn("purchase_units", segundo_payload)

    @patch.object(paypal_client, "obtener_token", return_value="tok_test")
    @patch.object(paypal_client, "_ejecutar_peticion")
    def test_07_crear_orden_no_reintenta_error_401(self, mock_ejecutar, mock_token):
        """7. Si crear_orden recibe un error 401 (autenticación), NO reintenta."""
        mock_ejecutar.side_effect = PayPalError("Unauthorized", codigo="AUTHENTICATION_FAILURE", status_code=401)
        with self.assertRaises(PayPalError) as ctx:
            paypal_client.crear_orden(88, Decimal("10.00"), "USD", request_id="req-err-401")
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(mock_ejecutar.call_count, 1)

    @patch.object(paypal_client, "obtener_token", return_value="tok_test")
    @patch.object(paypal_client, "_ejecutar_peticion")
    def test_08_crear_orden_no_reintenta_error_de_red(self, mock_ejecutar, mock_token):
        """8. Si crear_orden sufre un error de red o timeout, NO reintenta con payload alternativo."""
        mock_ejecutar.side_effect = PayPalError("Connection refused", codigo="NETWORK_ERROR", status_code=None)
        with self.assertRaises(PayPalError) as ctx:
            paypal_client.crear_orden(88, Decimal("10.00"), "USD", request_id="req-err-net")
        self.assertEqual(ctx.exception.codigo, "NETWORK_ERROR")
        self.assertEqual(mock_ejecutar.call_count, 1)


class TestIntegracionPagosPayPal(unittest.TestCase):
    """Pruebas de negocio e integridad con BD para Pago y pagos_paypal."""

    @classmethod
    def setUpClass(cls):
        cls.pagos_creados = []
        cls.pedidos_creados = []
        cls.direcciones_creadas = []
        cls.metodos_pago_creados = []
        cls.carritos_creados = []
        cls.usuarios_creados = []
        cls.stock_original = {}

        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                "SELECT v.id_variante, v.stock "
                "FROM variantes_producto v "
                "JOIN productos p ON v.id_producto = p.id_producto "
                "WHERE p.activo = 1 AND v.precio > 0 "
                "ORDER BY v.id_variante LIMIT 2"
            )
            variantes = cur.fetchall()
            if not variantes:
                cur.execute("SELECT id_variante, stock FROM variantes_producto ORDER BY id_variante LIMIT 2")
                variantes = cur.fetchall()

            cls.variantes_disponibles = [v["id_variante"] for v in variantes]
            for v in variantes:
                cls.stock_original[v["id_variante"]] = v["stock"]
                if v["stock"] < 30:
                    cur.execute(
                        "UPDATE variantes_producto SET stock = 60 WHERE id_variante = %s",
                        (v["id_variante"],),
                    )
            conn.commit()
        finally:
            cur.close()
            conn.close()

        ts = int(datetime.now().timestamp() * 1000)
        try:
            conn_u = get_connection()
            cur_u = conn_u.cursor()
            try:
                cur_u.execute(
                    "INSERT INTO usuarios (nombre, apellido, email, password_hash, telefono, id_rol) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    ("ClientePayPal", "Uno", f"test_paypal_u1_{ts}@beerhouse.test", "test_hash_123", "3001112233", 1),
                )
                cls.id_usuario_1 = cur_u.lastrowid
                cls.usuarios_creados.append(cls.id_usuario_1)

                cur_u.execute(
                    "INSERT INTO usuarios (nombre, apellido, email, password_hash, telefono, id_rol) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    ("ClientePayPal", "Dos", f"test_paypal_u2_{ts}@beerhouse.test", "test_hash_123", "3004445566", 1),
                )
                cls.id_usuario_2 = cur_u.lastrowid
                cls.usuarios_creados.append(cls.id_usuario_2)
                conn_u.commit()
            finally:
                cur_u.close()
                conn_u.close()

            cls.id_direccion_1 = Direccion.crear(
                id_usuario=cls.id_usuario_1,
                linea_direccion="Av. Dorado # 70-10",
                ciudad="Bogotá",
                departamento="Cundinamarca",
                codigo_postal="110111",
                alias="Casa PayPal",
                es_principal=1,
            )
            cls.direcciones_creadas.append(cls.id_direccion_1)

            cls.id_metodo_pago_1 = MetodoPago.crear(
                id_usuario=cls.id_usuario_1,
                tipo="PayPal",
                detalle="PayPal Sandbox",
                es_predeterminado=1,
            )
            cls.metodos_pago_creados.append(cls.id_metodo_pago_1)
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        conn = get_connection()
        cur = conn.cursor()
        try:
            usuarios_ids = list(dict.fromkeys(cls.usuarios_creados))
            pedidos_ids = list(dict.fromkeys(cls.pedidos_creados))

            if usuarios_ids:
                u_ph = ", ".join(["%s"] * len(usuarios_ids))
                cur.execute(
                    f"SELECT id_pedido FROM pedidos WHERE id_usuario IN ({u_ph})",
                    tuple(usuarios_ids),
                )
                for (pid,) in cur.fetchall():
                    if pid not in pedidos_ids:
                        pedidos_ids.append(pid)

            # 1. Borrar pagos asociados a los pedidos de prueba (ON DELETE RESTRICT en pagos -> pedidos)
            if pedidos_ids:
                p_ph = ", ".join(["%s"] * len(pedidos_ids))
                cur.execute(
                    f"DELETE FROM pagos WHERE id_pedido IN ({p_ph})",
                    tuple(pedidos_ids),
                )

            pagos_ids = list(dict.fromkeys(cls.pagos_creados))
            if pagos_ids:
                pg_ph = ", ".join(["%s"] * len(pagos_ids))
                cur.execute(
                    f"DELETE FROM pagos WHERE id_pago IN ({pg_ph})",
                    tuple(pagos_ids),
                )

            # 2. Borrar pedido_detalle y pedidos creados
            if pedidos_ids:
                p_ph = ", ".join(["%s"] * len(pedidos_ids))
                cur.execute(
                    f"DELETE FROM pedido_detalle WHERE id_pedido IN ({p_ph})",
                    tuple(pedidos_ids),
                )
                cur.execute(
                    f"DELETE FROM pedidos WHERE id_pedido IN ({p_ph})",
                    tuple(pedidos_ids),
                )

            # 3. Borrar carrito_items y carritos de los usuarios de prueba
            if usuarios_ids:
                u_ph = ", ".join(["%s"] * len(usuarios_ids))
                cur.execute(
                    f"DELETE ci FROM carrito_items ci "
                    f"JOIN carritos c ON ci.id_carrito = c.id_carrito "
                    f"WHERE c.id_usuario IN ({u_ph})",
                    tuple(usuarios_ids),
                )
                cur.execute(
                    f"DELETE FROM carritos WHERE id_usuario IN ({u_ph})",
                    tuple(usuarios_ids),
                )

            # 4. Borrar direcciones creadas
            direcciones_ids = list(dict.fromkeys(cls.direcciones_creadas))
            if direcciones_ids:
                d_ph = ", ".join(["%s"] * len(direcciones_ids))
                cur.execute(
                    f"DELETE FROM direcciones WHERE id_direccion IN ({d_ph})",
                    tuple(direcciones_ids),
                )
            if usuarios_ids:
                u_ph = ", ".join(["%s"] * len(usuarios_ids))
                cur.execute(
                    f"DELETE FROM direcciones WHERE id_usuario IN ({u_ph})",
                    tuple(usuarios_ids),
                )

            # 5. Borrar métodos de pago creados
            metodos_ids = list(dict.fromkeys(cls.metodos_pago_creados))
            if metodos_ids:
                m_ph = ", ".join(["%s"] * len(metodos_ids))
                cur.execute(
                    f"DELETE FROM metodos_pago WHERE id_metodo_pago IN ({m_ph})",
                    tuple(metodos_ids),
                )
            if usuarios_ids:
                u_ph = ", ".join(["%s"] * len(usuarios_ids))
                cur.execute(
                    f"DELETE FROM metodos_pago WHERE id_usuario IN ({u_ph})",
                    tuple(usuarios_ids),
                )

            # 6. Borrar usuarios de prueba
            if usuarios_ids:
                u_ph = ", ".join(["%s"] * len(usuarios_ids))
                cur.execute(
                    f"DELETE FROM usuarios WHERE id_usuario IN ({u_ph})",
                    tuple(usuarios_ids),
                )

            # 7. Restaurar EXACTAMENTE el stock original de las variantes
            for id_variante, stock_orig in cls.stock_original.items():
                cur.execute(
                    "UPDATE variantes_producto SET stock = %s WHERE id_variante = %s",
                    (stock_orig, id_variante),
                )

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    def setUp(self):
        if not self.variantes_disponibles:
            self.skipTest("No existen variantes de producto en la base de datos para probar pagos.")
        self.app = create_app()
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()
        self.client.set_cookie(COOKIE_MAYOR_EDAD, "1")
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        if hasattr(self, "app_context"):
            self.app_context.pop()

    def _crear_pedido_con_pago_pendiente(self, cantidad=2, total=Decimal("45.00")):
        id_var = self.variantes_disponibles[0]
        carrito = Carrito.obtener_o_crear(self.id_usuario_1)
        self.carritos_creados.append(carrito["id_carrito"])
        Carrito.vaciar(carrito["id_carrito"])
        CarritoItem.agregar(carrito["id_carrito"], id_var, cantidad)
        items = Carrito.obtener_items(carrito["id_carrito"])

        id_pedido = Pedido.crear_con_transaccion(
            id_usuario=self.id_usuario_1,
            id_direccion=self.id_direccion_1,
            id_metodo_pago=self.id_metodo_pago_1,
            total=total,
            items=items,
        )
        self.assertIsInstance(id_pedido, int)
        self.pedidos_creados.append(id_pedido)

        id_pago = Pago.crear_para_pedido(id_pedido, total, "USD")
        self.pagos_creados.append(id_pago)
        return id_pedido, id_pago

    @patch("app.utils.paypal_client.capturar_orden")
    @patch("app.utils.paypal_client.crear_orden")
    def test_01_pago_exitoso_confirma_pedido(self, mock_crear_orden, mock_capturar_orden):
        """1. Pago exitoso: inicia orden con monto de la BD, captura y pasa el pedido a confirmado."""
        id_pedido, id_pago = self._crear_pedido_con_pago_pendiente(cantidad=1, total=Decimal("58.00"))

        # Verificar que crear_para_pedido reutiliza el pago pendiente si ya existe
        id_pago_reutilizado = Pago.crear_para_pedido(id_pedido, Decimal("58.00"), "USD")
        self.assertEqual(id_pago, id_pago_reutilizado)

        order_id_mock = f"ORDER-OK-{id_pedido}"
        mock_crear_orden.return_value = order_id_mock

        order_id = iniciar_pago(self.id_usuario_1, id_pedido)
        self.assertEqual(order_id, order_id_mock)
        mock_crear_orden.assert_called_once_with(
            id_pedido=id_pedido,
            monto=Decimal("58.00"),
            moneda="USD",
            request_id=f"crear-{id_pedido}-1",
        )

        mock_capturar_orden.return_value = {
            "estado": "COMPLETED",
            "capture_id": f"CAP-OK-{id_pedido}",
            "monto": "58.00",
            "moneda": "USD",
            "custom_id": str(id_pedido),
        }

        res = capturar_pago(self.id_usuario_1, id_pedido, order_id_mock)
        self.assertTrue(res["exito"])
        self.assertFalse(res["reintentar"])
        self.assertEqual(res["capture_id"], f"CAP-OK-{id_pedido}")

        pedido = Pedido.obtener_por_id(id_pedido)
        self.assertEqual(pedido["id_estado"], ESTADO_CONFIRMADO)

        pago = Pago.obtener_por_pedido(id_pedido)
        self.assertEqual(pago["estado"], ESTADO_PAGO_COMPLETADO)
        self.assertEqual(pago["paypal_order_id"], order_id_mock)
        self.assertEqual(pago["paypal_capture_id"], f"CAP-OK-{id_pedido}")

    @patch("app.utils.paypal_client.reembolsar_captura")
    @patch("app.utils.paypal_client.capturar_orden")
    def test_02_monto_distinto_al_del_pedido_se_reembolsa_y_no_confirma(
        self, mock_capturar_orden, mock_reembolsar
    ):
        """2. Si el monto capturado difiere de pedidos.total, reembolsa automáticamente, cancela el pedido y restaura stock."""
        id_var = self.variantes_disponibles[0]
        stock_antes = VarianteProducto.obtener_por_id(id_var)["stock"]

        id_pedido, _ = self._crear_pedido_con_pago_pendiente(cantidad=1, total=Decimal("75.00"))
        stock_durante = VarianteProducto.obtener_por_id(id_var)["stock"]
        self.assertEqual(stock_durante, stock_antes - 1)

        order_id = f"ORDER-MISMATCH-{id_pedido}"
        Pago.registrar_orden(id_pedido, order_id)

        mock_capturar_orden.return_value = {
            "estado": "COMPLETED",
            "capture_id": f"CAP-MISMATCH-{id_pedido}",
            "monto": "10.00",  # Diferente de 75.00
            "moneda": "USD",
            "custom_id": str(id_pedido),
        }
        mock_reembolsar.return_value = {"estado": "COMPLETED", "refund_id": f"REF-MISMATCH-{id_pedido}"}

        with self.assertRaises(ValueError) as ctx:
            capturar_pago(self.id_usuario_1, id_pedido, order_id)
        self.assertIn("no coincide con el total del pedido", str(ctx.exception))

        mock_reembolsar.assert_called_once()
        self.assertEqual(mock_reembolsar.call_args.args[0], f"CAP-MISMATCH-{id_pedido}")

        pago = Pago.obtener_por_pedido(id_pedido)
        self.assertEqual(pago["estado"], ESTADO_PAGO_REEMBOLSADO)
        self.assertEqual(pago["paypal_capture_id"], f"CAP-MISMATCH-{id_pedido}")

        # El pedido se canceló automáticamente y devolvió el stock exactamente una vez
        pedido = Pedido.obtener_por_id(id_pedido)
        self.assertEqual(pedido["id_estado"], ESTADO_CANCELADO)

        stock_despues = VarianteProducto.obtener_por_id(id_var)["stock"]
        self.assertEqual(stock_despues, stock_antes)

    @patch("app.utils.paypal_client.capturar_orden")
    @patch("app.utils.paypal_client.crear_orden")
    def test_03_pedido_de_otro_usuario_es_rechazado(self, mock_crear_orden, mock_capturar_orden):
        """3. Iniciar o capturar el pago de un pedido perteneciente a otro usuario lanza ValueError."""
        id_pedido, _ = self._crear_pedido_con_pago_pendiente(cantidad=1, total=Decimal("32.00"))
        order_id = f"ORDER-OTHER-{id_pedido}"
        Pago.registrar_orden(id_pedido, order_id)

        with self.assertRaises(ValueError) as ctx1:
            iniciar_pago(self.id_usuario_2, id_pedido)
        self.assertIn("no pertenece al usuario", str(ctx1.exception))

        with self.assertRaises(ValueError) as ctx2:
            capturar_pago(self.id_usuario_2, id_pedido, order_id)
        self.assertIn("no pertenece al usuario", str(ctx2.exception))

        mock_crear_orden.assert_not_called()
        mock_capturar_orden.assert_not_called()

    @patch("app.utils.paypal_client.capturar_orden")
    def test_04_doble_captura_no_confirma_dos_veces_ni_llama_a_paypal(self, mock_capturar_orden):
        """4. Una segunda captura sobre un pago ya completado devuelve éxito sin volver a llamar a PayPal."""
        id_pedido, _ = self._crear_pedido_con_pago_pendiente(cantidad=1, total=Decimal("40.00"))
        order_id = f"ORDER-DOUBLE-{id_pedido}"
        Pago.registrar_orden(id_pedido, order_id)

        mock_capturar_orden.return_value = {
            "estado": "COMPLETED",
            "capture_id": f"CAP-DOUBLE-{id_pedido}",
            "monto": "40.00",
            "moneda": "USD",
            "custom_id": str(id_pedido),
        }

        res1 = capturar_pago(self.id_usuario_1, id_pedido, order_id)
        self.assertTrue(res1["exito"])
        self.assertFalse(res1["ya_completado"])
        self.assertEqual(mock_capturar_orden.call_count, 1)

        # Segunda llamada: no vuelve a invocar a PayPal ni falla por transición repetida
        res2 = capturar_pago(self.id_usuario_1, id_pedido, order_id)
        self.assertTrue(res2["exito"])
        self.assertTrue(res2["ya_completado"])
        self.assertEqual(mock_capturar_orden.call_count, 1)
        self.assertEqual(Pedido.obtener_por_id(id_pedido)["id_estado"], ESTADO_CONFIRMADO)

    @patch("app.utils.paypal_client.capturar_orden")
    def test_05_capturar_pedido_ya_cancelado_no_cobra(self, mock_capturar_orden):
        """5. Intentar capturar un pedido que ya fue cancelado lanza error ANTES de llamar a PayPal."""
        id_pedido, _ = self._crear_pedido_con_pago_pendiente(cantidad=1, total=Decimal("50.00"))
        order_id = f"ORDER-CANCELED-{id_pedido}"
        Pago.registrar_orden(id_pedido, order_id)

        # Cancelar el pedido antes de capturar
        Pedido.actualizar_estado(id_pedido, ESTADO_CANCELADO)

        with self.assertRaises(ValueError) as ctx:
            capturar_pago(self.id_usuario_1, id_pedido, order_id)
        self.assertIn("no está en estado pendiente", str(ctx.exception))

        mock_capturar_orden.assert_not_called()

    @patch("app.utils.paypal_client.reembolsar_captura")
    @patch("app.utils.paypal_client.capturar_orden")
    def test_06_cancelar_pedido_pagado_reembolsa_y_devuelve_stock_una_sola_vez(
        self, mock_capturar_orden, mock_reembolsar
    ):
        """6. Cancelar un pedido pagado llama al reembolso, marca 'reembolsado' y devuelve el stock una sola vez."""
        id_var = self.variantes_disponibles[0]
        stock_inicial = VarianteProducto.obtener_por_id(id_var)["stock"]

        id_pedido, _ = self._crear_pedido_con_pago_pendiente(cantidad=3, total=Decimal("90.00"))
        order_id = f"ORDER-PAID-CANCEL-{id_pedido}"
        Pago.registrar_orden(id_pedido, order_id)

        # Tras crear el pedido, el stock bajó en 3
        self.assertEqual(VarianteProducto.obtener_por_id(id_var)["stock"], stock_inicial - 3)

        mock_capturar_orden.return_value = {
            "estado": "COMPLETED",
            "capture_id": f"CAP-PAID-CANCEL-{id_pedido}",
            "monto": "90.00",
            "moneda": "USD",
            "custom_id": str(id_pedido),
        }
        capturar_pago(self.id_usuario_1, id_pedido, order_id)
        self.assertEqual(Pedido.obtener_por_id(id_pedido)["id_estado"], ESTADO_CONFIRMADO)

        mock_reembolsar.return_value = {"estado": "COMPLETED", "refund_id": f"REF-PAID-CANCEL-{id_pedido}"}

        cancelar_pedido_con_reembolso(id_pedido)
        mock_reembolsar.assert_called_once()
        self.assertEqual(mock_reembolsar.call_args.args[0], f"CAP-PAID-CANCEL-{id_pedido}")

        self.assertEqual(Pedido.obtener_por_id(id_pedido)["id_estado"], ESTADO_CANCELADO)
        self.assertEqual(Pago.obtener_por_pedido(id_pedido)["estado"], ESTADO_PAGO_REEMBOLSADO)
        self.assertEqual(VarianteProducto.obtener_por_id(id_var)["stock"], stock_inicial)

        # Intentar cancelar una segunda vez no vuelve a reembolsar ni a sumar stock
        with self.assertRaises(ValueError):
            cancelar_pedido_con_reembolso(id_pedido)
        self.assertEqual(mock_reembolsar.call_count, 1)
        self.assertEqual(VarianteProducto.obtener_por_id(id_var)["stock"], stock_inicial)

    @patch("app.utils.paypal_client.reembolsar_captura")
    @patch("app.utils.paypal_client.capturar_orden")
    def test_07_si_reembolso_falla_pedido_no_se_cancela(self, mock_capturar_orden, mock_reembolsar):
        """7. Si reembolsar_captura falla al cancelar un pedido pagado, el pedido NO se cancela ni cambia el stock."""
        id_var = self.variantes_disponibles[0]
        id_pedido, _ = self._crear_pedido_con_pago_pendiente(cantidad=2, total=Decimal("64.00"))
        order_id = f"ORDER-FAIL-REFUND-{id_pedido}"
        Pago.registrar_orden(id_pedido, order_id)

        mock_capturar_orden.return_value = {
            "estado": "COMPLETED",
            "capture_id": f"CAP-FAIL-REFUND-{id_pedido}",
            "monto": "64.00",
            "moneda": "USD",
            "custom_id": str(id_pedido),
        }
        capturar_pago(self.id_usuario_1, id_pedido, order_id)
        stock_tras_compra = VarianteProducto.obtener_por_id(id_var)["stock"]

        mock_reembolsar.side_effect = PayPalError("Error al procesar reembolso", codigo="REFUND_FAILED_INSUFFICIENT_FUNDS")

        with self.assertRaises(PayPalError):
            cancelar_pedido_con_reembolso(id_pedido)

        # El pedido sigue confirmado, el pago sigue completado y el stock no se devolvió
        self.assertEqual(Pedido.obtener_por_id(id_pedido)["id_estado"], ESTADO_CONFIRMADO)
        self.assertEqual(Pago.obtener_por_pedido(id_pedido)["estado"], ESTADO_PAGO_COMPLETADO)
        self.assertEqual(VarianteProducto.obtener_por_id(id_var)["stock"], stock_tras_compra)

    @patch("app.utils.paypal_client.capturar_orden")
    def test_08_cancelar_impagos_vencidos_cancela_solo_vencidos_y_es_idempotente(self, mock_capturar_orden):
        """8. cancelar_impagos_vencidos cancela solo los vencidos, devuelve stock una vez y no toca los pagados."""
        id_var = self.variantes_disponibles[0]
        stock_base = VarianteProducto.obtener_por_id(id_var)["stock"]

        # Pedido 1: impago vencido (hace 45 minutos) -> debe cancelarse y devolver 2 unidades
        id_pedido_vencido, id_pago_vencido = self._crear_pedido_con_pago_pendiente(cantidad=2, total=Decimal("30.00"))
        # Pedido 2: impago reciente (recién creado) -> debe seguir pendiente
        id_pedido_reciente, _ = self._crear_pedido_con_pago_pendiente(cantidad=1, total=Decimal("15.00"))
        # Pedido 3: pagado pero con fecha antigua -> NO debe cancelarse
        id_pedido_pagado, id_pago_pagado = self._crear_pedido_con_pago_pendiente(cantidad=1, total=Decimal("20.00"))
        order_id_pagado = f"ORDER-EXP-PAID-{id_pedido_pagado}"
        Pago.registrar_orden(id_pedido_pagado, order_id_pagado)
        mock_capturar_orden.return_value = {
            "estado": "COMPLETED",
            "capture_id": f"CAP-EXP-PAID-{id_pedido_pagado}",
            "monto": "20.00",
            "moneda": "USD",
            "custom_id": str(id_pedido_pagado),
        }
        capturar_pago(self.id_usuario_1, id_pedido_pagado, order_id_pagado)

        # Envejecer fecha_creacion de id_pago_vencido e id_pago_pagado a 45 minutos atrás
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE pagos SET fecha_creacion = DATE_SUB(NOW(), INTERVAL 45 MINUTE) WHERE id_pago IN (%s, %s)",
                (id_pago_vencido, id_pago_pagado),
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()

        # Antes de cancelar vencidos: se descontaron 2 + 1 + 1 = 4 unidades
        self.assertEqual(VarianteProducto.obtener_por_id(id_var)["stock"], stock_base - 4)

        cancelados_1 = cancelar_impagos_vencidos(minutos=30)
        self.assertEqual(cancelados_1, 1)

        # El vencido pasó a cancelado y devolvió sus 2 unidades (quedan 2 descontadas de reciente + pagado)
        self.assertEqual(Pedido.obtener_por_id(id_pedido_vencido)["id_estado"], ESTADO_CANCELADO)
        self.assertEqual(Pago.obtener_por_pedido(id_pedido_vencido)["estado"], ESTADO_PAGO_CANCELADO)
        self.assertEqual(VarianteProducto.obtener_por_id(id_var)["stock"], stock_base - 2)

        # El reciente sigue pendiente y el pagado sigue confirmado
        self.assertEqual(Pedido.obtener_por_id(id_pedido_reciente)["id_estado"], ESTADO_PENDIENTE)
        self.assertEqual(Pago.obtener_por_pedido(id_pedido_reciente)["estado"], ESTADO_PAGO_PENDIENTE)
        self.assertEqual(Pedido.obtener_por_id(id_pedido_pagado)["id_estado"], ESTADO_CONFIRMADO)
        self.assertEqual(Pago.obtener_por_pedido(id_pedido_pagado)["estado"], ESTADO_PAGO_COMPLETADO)

        # Segunda llamada seguida: devuelve 0 y no altera el stock
        cancelados_2 = cancelar_impagos_vencidos(minutos=30)
        self.assertEqual(cancelados_2, 0)
        self.assertEqual(VarianteProducto.obtener_por_id(id_var)["stock"], stock_base - 2)

    @patch("app.utils.paypal_client.capturar_orden")
    def test_09_instrument_declined_no_cancela_pedido_y_permite_reintentar(self, mock_capturar_orden):
        """9. Un INSTRUMENT_DECLINED devuelve reintentar=True y deja tanto el pedido como el pago en pendiente."""
        id_pedido, _ = self._crear_pedido_con_pago_pendiente(cantidad=1, total=Decimal("28.00"))
        order_id = f"ORDER-DECLINED-{id_pedido}"
        Pago.registrar_orden(id_pedido, order_id)

        mock_capturar_orden.side_effect = PayPalError(
            "La tarjeta fue rechazada por el banco emisor",
            codigo="INSTRUMENT_DECLINED",
            status_code=422,
        )

        res = capturar_pago(self.id_usuario_1, id_pedido, order_id)
        self.assertFalse(res["exito"])
        self.assertTrue(res["reintentar"])
        self.assertEqual(res["codigo"], "INSTRUMENT_DECLINED")

        self.assertEqual(Pedido.obtener_por_id(id_pedido)["id_estado"], ESTADO_PENDIENTE)
        self.assertEqual(Pago.obtener_por_pedido(id_pedido)["estado"], ESTADO_PAGO_PENDIENTE)

    def test_10_vista_checkout_paypal(self):
        """10. GET /pagos/paypal/<id> valida autenticación, propiedad y estado del pedido."""
        id_pedido, _ = self._crear_pedido_con_pago_pendiente(cantidad=1, total=Decimal("25.00"))

        # 1. Sin sesión: redirige al login
        res_anon = self.client.get(f"/pagos/paypal/{id_pedido}")
        self.assertEqual(res_anon.status_code, 302)
        self.assertIn("/auth/login", res_anon.headers.get("Location", ""))

        # 2. Con usuario distinto al dueño: 404
        with self.client.session_transaction() as sess:
            sess["id_usuario"] = self.id_usuario_2
            sess["id_rol"] = 1
        res_otro = self.client.get(f"/pagos/paypal/{id_pedido}")
        self.assertEqual(res_otro.status_code, 404)

        # 3. Con dueño legítimo y pedido pendiente: 200 y renderiza el botón de PayPal
        with self.client.session_transaction() as sess:
            sess["id_usuario"] = self.id_usuario_1
            sess["id_rol"] = 1
        res_owner = self.client.get(f"/pagos/paypal/{id_pedido}")
        self.assertEqual(res_owner.status_code, 200)
        self.assertIn(b"paypal-button-container", res_owner.data)

        # 4. Si el pedido ya está confirmado: redirige a confirmación
        Pedido.actualizar_estado(id_pedido, ESTADO_CONFIRMADO)
        res_confirmado = self.client.get(f"/pagos/paypal/{id_pedido}")
        self.assertEqual(res_confirmado.status_code, 302)
        self.assertIn(f"/carrito/confirmacion/{id_pedido}", res_confirmado.headers.get("Location", ""))

        # 5. Si el pedido está cancelado: redirige al catálogo
        Pedido.actualizar_estado(id_pedido, ESTADO_CANCELADO)
        res_cancelado = self.client.get(f"/pagos/paypal/{id_pedido}")
        self.assertEqual(res_cancelado.status_code, 302)
        self.assertIn("/productos/", res_cancelado.headers.get("Location", ""))

    @patch("app.utils.paypal_client.crear_orden")
    def test_11_crear_orden_endpoint_json(self, mock_crear):
        """11. POST /pagos/paypal/<id>/crear devuelve {id: order_id} en JSON sin romper en 500."""
        id_pedido, _ = self._crear_pedido_con_pago_pendiente(cantidad=1, total=Decimal("30.00"))
        mock_crear.return_value = "PAYPAL-ORDER-12345"

        with self.client.session_transaction() as sess:
            sess["id_usuario"] = self.id_usuario_1
            sess["id_rol"] = 1

        res = self.client.post(
            f"/pagos/paypal/{id_pedido}/crear",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("id"), "PAYPAL-ORDER-12345")

        # Llamar para un pedido que no existe devuelve 400
        res_invalido = self.client.post(
            "/pagos/paypal/9999999/crear",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(res_invalido.status_code, 400)
        self.assertIn("error", res_invalido.get_json())

    @patch("app.utils.email_service.send_order_confirmation_email", return_value=True)
    @patch("app.utils.paypal_client.capturar_orden")
    def test_12_capturar_orden_endpoint(self, mock_capturar, mock_email):
        """12. POST /pagos/paypal/<id>/capturar maneja reintentos y capturas exitosas."""
        id_pedido, _ = self._crear_pedido_con_pago_pendiente(cantidad=1, total=Decimal("40.00"))
        order_id = f"ORDER-CAP-TEST-{id_pedido}"
        Pago.registrar_orden(id_pedido, order_id)

        with self.client.session_transaction() as sess:
            sess["id_usuario"] = self.id_usuario_1
            sess["id_rol"] = 1

        # Caso A: Rechazo INSTRUMENT_DECLINED -> 422 con reintentar=True
        mock_capturar.side_effect = PayPalError(
            "Tarjeta rechazada",
            codigo="INSTRUMENT_DECLINED",
            status_code=422,
        )
        res_declined = self.client.post(
            f"/pagos/paypal/{id_pedido}/capturar",
            json={"orderID": order_id},
        )
        self.assertEqual(res_declined.status_code, 422)
        data_declined = res_declined.get_json()
        self.assertFalse(data_declined.get("ok"))
        self.assertTrue(data_declined.get("reintentar"))

        # Caso B: Captura exitosa -> 200 con redirect a confirmación
        mock_capturar.side_effect = None
        mock_capturar.return_value = {
            "estado": "COMPLETED",
            "capture_id": f"CAP-{id_pedido}",
            "monto": Decimal("40.00"),
            "moneda": "USD",
            "custom_id": str(id_pedido),
        }
        res_ok = self.client.post(
            f"/pagos/paypal/{id_pedido}/capturar",
            json={"orderID": order_id},
        )
        self.assertEqual(res_ok.status_code, 200)
        data_ok = res_ok.get_json()
        self.assertTrue(data_ok.get("ok"))
        self.assertIn(f"/carrito/confirmacion/{id_pedido}", data_ok.get("redirect", ""))

        self.assertEqual(Pedido.obtener_por_id(id_pedido)["id_estado"], ESTADO_CONFIRMADO)
        self.assertEqual(Pago.obtener_por_pedido(id_pedido)["estado"], ESTADO_PAGO_COMPLETADO)

    def test_13_cliente_cancelar_pedido_cuenta(self):
        """13. POST /cuenta/pedidos/<id>/cancelar cancela pedido pendiente y libera stock."""
        id_var = self.variantes_disponibles[0]
        stock_antes = VarianteProducto.obtener_por_id(id_var)["stock"]

        id_pedido, _ = self._crear_pedido_con_pago_pendiente(cantidad=2, total=Decimal("50.00"))
        self.assertEqual(VarianteProducto.obtener_por_id(id_var)["stock"], stock_antes - 2)

        # Usuario 2 intenta cancelar pedido de Usuario 1 -> 404
        with self.client.session_transaction() as sess:
            sess["id_usuario"] = self.id_usuario_2
            sess["id_rol"] = 1
        res_otro = self.client.post(f"/cuenta/pedidos/{id_pedido}/cancelar")
        self.assertEqual(res_otro.status_code, 404)

        # Dueño cancela su propio pedido -> cancela pedido y pago, restaura stock
        with self.client.session_transaction() as sess:
            sess["id_usuario"] = self.id_usuario_1
            sess["id_rol"] = 1
        res_cancela = self.client.post(f"/cuenta/pedidos/{id_pedido}/cancelar", follow_redirects=True)
        self.assertEqual(res_cancela.status_code, 200)

        self.assertEqual(Pedido.obtener_por_id(id_pedido)["id_estado"], ESTADO_CANCELADO)
        self.assertEqual(Pago.obtener_por_pedido(id_pedido)["estado"], ESTADO_PAGO_CANCELADO)
        self.assertEqual(VarianteProducto.obtener_por_id(id_var)["stock"], stock_antes)

    @patch("app.utils.paypal_client.reembolsar_captura")
    def test_14_admin_cancelar_pedido_con_reembolso(self, mock_reembolsar):
        """14. Admin cancela pedido con pago completado: reembolsa en PayPal. Si falla reembolso, no cancela."""
        id_pedido, _ = self._crear_pedido_con_pago_pendiente(cantidad=1, total=Decimal("35.00"))
        Pago.confirmar_captura(
            id_pedido=id_pedido,
            order_id=f"ORD-ADMIN-{id_pedido}",
            capture_id=f"CAP-ADMIN-{id_pedido}",
            monto=Decimal("35.00"),
            moneda="USD",
        )
        Pedido.actualizar_estado(id_pedido, ESTADO_CONFIRMADO)

        # Iniciar sesión como Admin (id_rol=2)
        with self.client.session_transaction() as sess:
            sess["id_usuario"] = self.id_usuario_1
            sess["id_rol"] = 2

        # Intento 1: Falla el reembolso de PayPal -> no debe cancelar el pedido
        mock_reembolsar.side_effect = PayPalError("Error de PayPal al reembolsar", status_code=500)
        res_falla = self.client.post(
            f"/admin/pedidos/{id_pedido}/estado",
            data={"id_estado": str(ESTADO_CANCELADO)},
            follow_redirects=True,
        )
        self.assertEqual(res_falla.status_code, 200)
        self.assertEqual(Pedido.obtener_por_id(id_pedido)["id_estado"], ESTADO_CONFIRMADO)
        self.assertEqual(Pago.obtener_por_pedido(id_pedido)["estado"], ESTADO_PAGO_COMPLETADO)

        # Intento 2: Éxito en el reembolso -> pedido pasa a cancelado y pago a reembolsado
        mock_reembolsar.side_effect = None
        mock_reembolsar.return_value = {"refund_id": f"REF-{id_pedido}", "estado": "COMPLETED"}
        res_exito = self.client.post(
            f"/admin/pedidos/{id_pedido}/estado",
            data={"id_estado": str(ESTADO_CANCELADO)},
            follow_redirects=True,
        )
        self.assertEqual(res_exito.status_code, 200)
        self.assertEqual(Pedido.obtener_por_id(id_pedido)["id_estado"], ESTADO_CANCELADO)
        self.assertEqual(Pago.obtener_por_pedido(id_pedido)["estado"], ESTADO_PAGO_REEMBOLSADO)

    def test_15_csrf_requerido_en_endpoints_pagos(self):
        """15. Los endpoints POST de /pagos/paypal exigen token CSRF si WTF_CSRF_ENABLED está activo."""
        app_csrf = create_app()
        app_csrf.config["WTF_CSRF_ENABLED"] = True
        client_csrf = app_csrf.test_client()
        client_csrf.set_cookie(COOKIE_MAYOR_EDAD, "1")

        with client_csrf.session_transaction() as sess:
            sess["id_usuario"] = self.id_usuario_1
            sess["id_rol"] = 1

        id_pedido, _ = self._crear_pedido_con_pago_pendiente(cantidad=1, total=Decimal("20.00"))

        # Petición POST sin header X-CSRFToken -> 400 Bad Request
        res_sin_csrf = client_csrf.post(
            f"/pagos/paypal/{id_pedido}/crear",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(res_sin_csrf.status_code, 400)


if __name__ == "__main__":
    unittest.main()
