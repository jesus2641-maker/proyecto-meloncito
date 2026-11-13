"""
Pruebas unitarias para PayPal Orders v2 (paypal_service y paypal_bp).
Usa mocks para simular las peticiones HTTP a PayPal y las operaciones de base de datos.
"""

import unittest
from unittest.mock import patch, MagicMock
from decimal import Decimal

from app import create_app
from app.routes.edad import COOKIE_MAYOR_EDAD
import app.services.paypal_service as ps


class TestPayPalService(unittest.TestCase):
    def setUp(self):
        # Reiniciar caché de tokens
        ps._TOKEN_CACHE["access_token"] = None
        ps._TOKEN_CACHE["expires_at"] = 0

    @patch("app.services.paypal_service.requests.post")
    @patch.dict("os.environ", {"PAYPAL_CLIENT_ID": "test_client", "PAYPAL_CLIENT_SECRET": "test_secret", "PAYPAL_MODE": "sandbox"})
    def test_get_access_token_success_and_cache(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "TOKEN_123", "expires_in": 3600}
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        # Primera llamada: pide a PayPal
        token1 = ps.get_access_token()
        self.assertEqual(token1, "TOKEN_123")
        self.assertEqual(mock_post.call_count, 1)

        # Segunda llamada: usa caché
        token2 = ps.get_access_token()
        self.assertEqual(token2, "TOKEN_123")
        self.assertEqual(mock_post.call_count, 1)

    @patch("app.services.paypal_service.get_access_token", return_value="MOCK_TOKEN")
    @patch("app.services.paypal_service.requests.post")
    @patch.dict("os.environ", {"PAYPAL_MODE": "sandbox"})
    def test_create_order(self, mock_post, mock_token):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "ORDER_ABC_123", "status": "CREATED"}
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        res = ps.create_order(total=Decimal("45.99"), currency="USD", reference_id="99")
        self.assertEqual(res["id"], "ORDER_ABC_123")
        self.assertEqual(mock_post.call_count, 1)

        args, kwargs = mock_post.call_args
        body = kwargs["json"]
        self.assertEqual(body["intent"], "CAPTURE")
        self.assertEqual(body["purchase_units"][0]["amount"]["value"], "45.99")
        self.assertEqual(body["purchase_units"][0]["amount"]["currency_code"], "USD")
        self.assertEqual(body["purchase_units"][0]["reference_id"], "99")

    @patch("app.services.paypal_service.get_access_token", return_value="MOCK_TOKEN")
    @patch("app.services.paypal_service.requests.post")
    @patch.dict("os.environ", {"PAYPAL_MODE": "sandbox"})
    def test_capture_order(self, mock_post, mock_token):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "id": "ORDER_ABC_123",
            "status": "COMPLETED",
            "purchase_units": [
                {"payments": {"captures": [{"id": "CAPTURE_XYZ_999", "status": "COMPLETED"}]}}
            ]
        }
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        res = ps.capture_order("ORDER_ABC_123")
        self.assertEqual(res["status"], "COMPLETED")
        self.assertIn("ORDER_ABC_123/capture", mock_post.call_args[0][0])

    @patch("app.services.paypal_service.get_access_token", return_value="MOCK_TOKEN")
    @patch("app.services.paypal_service.requests.post")
    @patch.dict("os.environ", {"PAYPAL_MODE": "sandbox"})
    def test_refund_capture(self, mock_post, mock_token):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "REFUND_111", "status": "COMPLETED"}
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        res = ps.refund_capture("CAPTURE_XYZ_999", note="Test refund")
        self.assertEqual(res["status"], "COMPLETED")
        self.assertIn("CAPTURE_XYZ_999/refund", mock_post.call_args[0][0])


class TestPayPalRoutes(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app.config["WTF_CSRF_ENABLED"] = False  # Para simplificar pruebas unitarias HTTP
        self.client = self.app.test_client()
        self.client.set_cookie(COOKIE_MAYOR_EDAD, "1")

    def test_checkout_requiere_login(self):
        response = self.client.get("/paypal/checkout", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    @patch("app.routes.paypal._obtener_carrito_y_total_bd")
    def test_checkout_carrito_vacio(self, mock_carrito):
        mock_carrito.return_value = ({"id_carrito": 1}, [], Decimal("0.00"))
        with self.client.session_transaction() as sess:
            sess["id_usuario"] = 1
            sess["email"] = "cliente@beerhouse.com"
            sess["id_rol"] = 1

        response = self.client.get("/paypal/checkout", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/carrito", response.headers["Location"])

    @patch("app.routes.paypal._obtener_carrito_y_total_bd")
    @patch("app.routes.paypal._obtener_direccion_principal")
    def test_checkout_sin_direccion(self, mock_dir, mock_carrito):
        mock_carrito.return_value = (
            {"id_carrito": 1},
            [{"id_variante": 1, "cantidad": 1, "precio": Decimal("45.00"), "precio_oferta": None}],
            Decimal("45.00")
        )
        mock_dir.return_value = None  # Sin dirección

        with self.client.session_transaction() as sess:
            sess["id_usuario"] = 1
            sess["email"] = "cliente@beerhouse.com"
            sess["id_rol"] = 1

        response = self.client.get("/paypal/checkout", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/cuenta/direcciones/nueva", response.headers["Location"])

    @patch("app.routes.paypal._obtener_carrito_y_total_bd")
    def test_create_order_carrito_vacio_devuelve_400(self, mock_carrito):
        mock_carrito.return_value = ({"id_carrito": 1}, [], Decimal("0.00"))
        with self.client.session_transaction() as sess:
            sess["id_usuario"] = 1
            sess["id_rol"] = 1

        response = self.client.post("/paypal/create-order")
        self.assertEqual(response.status_code, 400)
        self.assertIn("El carrito está vacío", response.get_json()["error"])

    @patch("app.routes.paypal.paypal_service.create_order")
    @patch("app.routes.paypal.get_connection")
    @patch("app.routes.paypal._obtener_carrito_y_total_bd")
    def test_create_order_exito_guarda_sesion(self, mock_carrito, mock_db, mock_create):
        mock_carrito.return_value = (
            {"id_carrito": 10},
            [{"id_variante": 5, "nombre_producto": "Whisky", "presentacion": "750ml", "cantidad": 2, "precio": Decimal("50.00"), "precio_oferta": None}],
            Decimal("100.00")
        )
        # Mock de consulta de stock
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"stock": 10, "presentacion": "750ml"}
        mock_conn.cursor.return_value = mock_cursor
        mock_db.return_value = mock_conn

        mock_create.return_value = {"id": "ORDER_PAYPAL_777"}

        with self.client.session_transaction() as sess:
            sess["id_usuario"] = 1
            sess["id_rol"] = 1

        response = self.client.post("/paypal/create-order")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["orderID"], "ORDER_PAYPAL_777")

        # Verificar que se guardó en sesión
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("paypal_order_id"), "ORDER_PAYPAL_777")

    def test_capture_order_valida_order_id_sesion(self):
        with self.client.session_transaction() as sess:
            sess["id_usuario"] = 1
            sess["id_rol"] = 1
            sess["paypal_order_id"] = "ORDEN_CORRECTA"

        # Envío con orderID distinto
        response = self.client.post("/paypal/capture-order", json={"orderID": "ORDEN_INCORRECTA"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("no coincide", response.get_json()["error"])

    @patch("app.routes.paypal.paypal_service.refund_capture")
    @patch("app.routes.paypal.paypal_service.capture_order")
    @patch("app.routes.paypal.get_connection")
    @patch("app.routes.paypal._obtener_carrito_y_total_bd")
    def test_capture_order_reembolsa_si_falla_bd(self, mock_carrito, mock_db, mock_capture, mock_refund):
        mock_carrito.return_value = (
            {"id_carrito": 1},
            [{"id_variante": 2, "cantidad": 1, "precio": Decimal("30.00"), "precio_oferta": None}],
            Decimal("30.00")
        )
        mock_capture.return_value = {
            "status": "COMPLETED",
            "purchase_units": [
                {"payments": {"captures": [{"id": "CAP_999", "status": "COMPLETED"}]}}
            ]
        }
        mock_refund.return_value = {"status": "COMPLETED"}

        # Simular fallo en BD (ej: sin dirección o fallo SQL)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None  # Provoca fallo al buscar dirección
        mock_conn.cursor.return_value = mock_cursor
        mock_db.return_value = mock_conn

        with self.client.session_transaction() as sess:
            sess["id_usuario"] = 1
            sess["id_rol"] = 1
            sess["paypal_order_id"] = "ORDER_VALID"

        response = self.client.post("/paypal/capture-order", json={"orderID": "ORDER_VALID"})
        self.assertEqual(response.status_code, 500)
        # Verificar que se llamó al reembolso automático
        mock_refund.assert_called_once_with("CAP_999", note="Reembolso automático: fallo interno al guardar el pedido en Beer House.")


if __name__ == "__main__":
    unittest.main()
