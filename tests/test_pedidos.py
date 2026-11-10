"""
Pruebas de integridad de pedidos y validación de pagos/direcciones.

Ejecutar:  python -m unittest tests.test_pedidos
"""

import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from app import create_app
from app.models.carrito import Carrito, CarritoItem
from app.models.direccion import Direccion
from app.models.metodo_pago import MetodoPago
from app.models.pedido import (
    ESTADO_CANCELADO,
    ESTADO_CONFIRMADO,
    ESTADO_EN_CAMINO,
    ESTADO_ENTREGADO,
    ESTADO_PENDIENTE,
    Pedido,
    PedidoDetalle,
)
from app.models.producto import VarianteProducto
from app.models.usuario import Usuario
from app.routes.edad import COOKIE_MAYOR_EDAD
from app.utils.db import get_connection


class TestIntegridadPedidos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pedidos_creados = []
        cls.direcciones_creadas = []
        cls.metodos_pago_creados = []
        cls.carritos_creados = []
        cls.usuarios_creados = []
        cls.stock_original = {}

        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        try:
            # Guardar el stock original de las variantes que las pruebas usarán
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
                # Garantizar stock suficiente durante la ejecución de las pruebas;
                # tearDownClass restaurará el valor original exacto.
                if v["stock"] < 20:
                    cur.execute(
                        "UPDATE variantes_producto SET stock = 50 WHERE id_variante = %s",
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
                    ("ClientePrueba", "Uno", f"test_pedidos_u1_{ts}@beerhouse.test", "test_hash_123", "3001112233", 1),
                )
                cls.id_usuario_1 = cur_u.lastrowid
                cls.usuarios_creados.append(cls.id_usuario_1)

                cur_u.execute(
                    "INSERT INTO usuarios (nombre, apellido, email, password_hash, telefono, id_rol) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    ("ClientePrueba", "Dos", f"test_pedidos_u2_{ts}@beerhouse.test", "test_hash_123", "3004445566", 1),
                )
                cls.id_usuario_2 = cur_u.lastrowid
                cls.usuarios_creados.append(cls.id_usuario_2)
                conn_u.commit()
            finally:
                cur_u.close()
                conn_u.close()

            cls.id_direccion_1 = Direccion.crear(
                id_usuario=cls.id_usuario_1,
                linea_direccion="Calle 100 # 15-20 Apto 301",
                ciudad="Bogotá",
                departamento="Cundinamarca",
                codigo_postal="110111",
                alias="Casa Test",
                es_principal=1,
            )
            cls.direcciones_creadas.append(cls.id_direccion_1)

            cls.id_metodo_pago_1 = MetodoPago.crear(
                id_usuario=cls.id_usuario_1,
                tipo="Efectivo contra entrega",
                detalle="Pago contra entrega",
                es_predeterminado=1,
            )
            cls.metodos_pago_creados.append(cls.id_metodo_pago_1)

            cls.id_metodo_pago_tarjeta = MetodoPago.crear(
                id_usuario=cls.id_usuario_1,
                tipo="Tarjeta de crédito",
                detalle="Terminada en 4242",
                es_predeterminado=0,
            )
            cls.metodos_pago_creados.append(cls.id_metodo_pago_tarjeta)
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

            # También incluir cualquier pedido asociado a los usuarios de prueba
            if usuarios_ids:
                u_ph = ", ".join(["%s"] * len(usuarios_ids))
                cur.execute(
                    f"SELECT id_pedido FROM pedidos WHERE id_usuario IN ({u_ph})",
                    tuple(usuarios_ids),
                )
                for (pid,) in cur.fetchall():
                    if pid not in pedidos_ids:
                        pedidos_ids.append(pid)

            # 1. Borrar pedido_detalle y pedidos creados
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

            # 2. Borrar carrito_items y carritos de los usuarios de prueba
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

            # 3. Borrar direcciones creadas
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

            # 4. Borrar métodos de pago creados
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

            # 5. Borrar usuarios de prueba
            if usuarios_ids:
                u_ph = ", ".join(["%s"] * len(usuarios_ids))
                cur.execute(
                    f"DELETE FROM usuarios WHERE id_usuario IN ({u_ph})",
                    tuple(usuarios_ids),
                )

            # 6. Restaurar EXACTAMENTE el stock original de las variantes
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
            self.skipTest("No existen variantes de producto en la base de datos para probar pedidos.")
        self.app = create_app()
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()
        self.client.set_cookie(COOKIE_MAYOR_EDAD, "1")
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def _preparar_carrito(self, id_usuario, id_variante, cantidad):
        carrito = Carrito.obtener_o_crear(id_usuario)
        self.carritos_creados.append(carrito["id_carrito"])
        Carrito.vaciar(carrito["id_carrito"])
        CarritoItem.agregar(carrito["id_carrito"], id_variante, cantidad)
        return Carrito.obtener_items(carrito["id_carrito"])

    @patch("app.routes.carrito.send_order_confirmation_email", return_value=True)
    def test_01_compra_normal_baja_stock_y_calcula_total_en_servidor(self, _mock_email):
        """1. Compra normal: descuenta stock y el total lo calcula el servidor."""
        id_var = self.variantes_disponibles[0]
        var_antes = VarianteProducto.obtener_por_id(id_var)
        stock_antes = var_antes["stock"]
        cantidad = 2

        items = self._preparar_carrito(self.id_usuario_1, id_var, cantidad)
        precio_efectivo = items[0]["precio_oferta"] if items[0].get("precio_oferta") else items[0]["precio"]
        total_esperado = Decimal(str(precio_efectivo)) * Decimal(cantidad)

        with self.client.session_transaction() as sess:
            sess["id_usuario"] = self.id_usuario_1
            sess["id_rol"] = 1
            sess["edad_verificada"] = True

        # Incluso si el cliente envía un campo "total" manipulado en el POST, el servidor calcula el total real
        res = self.client.post(
            "/carrito/checkout",
            data={
                "opcion_direccion": "guardada",
                "id_direccion": str(self.id_direccion_1),
                "opcion_pago": "guardado",
                "id_metodo_pago": str(self.id_metodo_pago_1),
                "total": "1.00",
            },
            follow_redirects=False,
        )
        self.assertEqual(res.status_code, 302)
        self.assertIn("/carrito/confirmacion/", res.headers.get("Location", ""))

        id_pedido = int(res.headers["Location"].rstrip("/").split("/")[-1])
        self.pedidos_creados.append(id_pedido)

        pedido = Pedido.obtener_por_id(id_pedido)
        self.assertIsNotNone(pedido)
        self.assertEqual(Decimal(str(pedido["total"])), total_esperado)
        self.assertEqual(pedido["id_estado"], ESTADO_PENDIENTE)

        var_despues = VarianteProducto.obtener_por_id(id_var)
        self.assertEqual(var_despues["stock"], stock_antes - cantidad)

    def test_02_stock_insuficiente(self):
        """2. Stock insuficiente: no crea el pedido ni descuenta stock."""
        id_var = self.variantes_disponibles[0]
        var_antes = VarianteProducto.obtener_por_id(id_var)
        stock_antes = var_antes["stock"]
        cantidad_excesiva = stock_antes + 50

        resultado = Pedido.crear_con_transaccion(
            id_usuario=self.id_usuario_1,
            id_direccion=self.id_direccion_1,
            id_metodo_pago=self.id_metodo_pago_1,
            total=Decimal("999999.00"),
            items=[
                {
                    "id_variante": id_var,
                    "cantidad": cantidad_excesiva,
                    "precio": var_antes["precio"],
                    "precio_oferta": None,
                    "nombre_producto": "Producto Test",
                    "presentacion": var_antes["presentacion"],
                }
            ],
        )
        self.assertIsInstance(resultado, dict)
        self.assertEqual(resultado.get("error"), "stock_insuficiente")

        var_despues = VarianteProducto.obtener_por_id(id_var)
        self.assertEqual(var_despues["stock"], stock_antes)

    def test_03_doble_cancelacion_devuelve_stock_solo_una_vez(self):
        """3. Doble cancelación: la primera devuelve el stock y la segunda lanza ValueError sin tocar stock."""
        id_var = self.variantes_disponibles[0]
        items = self._preparar_carrito(self.id_usuario_1, id_var, 3)
        var_antes_compra = VarianteProducto.obtener_por_id(id_var)["stock"]

        id_pedido = Pedido.crear_con_transaccion(
            id_usuario=self.id_usuario_1,
            id_direccion=self.id_direccion_1,
            id_metodo_pago=self.id_metodo_pago_1,
            total=Decimal("10000.00"),
            items=items,
        )
        self.assertIsInstance(id_pedido, int)
        self.pedidos_creados.append(id_pedido)

        # Tras comprar 3 unidades, el stock bajó en 3
        self.assertEqual(VarianteProducto.obtener_por_id(id_var)["stock"], var_antes_compra - 3)

        # Primera cancelación: devuelve las 3 unidades
        Pedido.actualizar_estado(id_pedido, ESTADO_CANCELADO)
        stock_tras_primera_cancelacion = VarianteProducto.obtener_por_id(id_var)["stock"]
        self.assertEqual(stock_tras_primera_cancelacion, var_antes_compra)

        # Segunda cancelación: lanza ValueError("El pedido ya está en ese estado") y NO toca el stock
        with self.assertRaises(ValueError) as ctx:
            Pedido.actualizar_estado(id_pedido, ESTADO_CANCELADO)
        self.assertEqual(str(ctx.exception), "El pedido ya está en ese estado")
        self.assertEqual(VarianteProducto.obtener_por_id(id_var)["stock"], stock_tras_primera_cancelacion)

    def test_04_pedido_cancelado_no_se_puede_reabrir(self):
        """4. Un pedido cancelado no se puede reabrir a ningún otro estado."""
        id_var = self.variantes_disponibles[0]
        items = self._preparar_carrito(self.id_usuario_1, id_var, 2)

        id_pedido = Pedido.crear_con_transaccion(
            id_usuario=self.id_usuario_1,
            id_direccion=self.id_direccion_1,
            id_metodo_pago=self.id_metodo_pago_1,
            total=Decimal("10000.00"),
            items=items,
        )
        self.pedidos_creados.append(id_pedido)
        Pedido.actualizar_estado(id_pedido, ESTADO_CANCELADO)
        stock_tras_cancelar = VarianteProducto.obtener_por_id(id_var)["stock"]

        for estado_destino in (ESTADO_PENDIENTE, ESTADO_CONFIRMADO, ESTADO_EN_CAMINO, ESTADO_ENTREGADO):
            with self.subTest(estado_destino=estado_destino):
                with self.assertRaises(ValueError) as ctx:
                    Pedido.actualizar_estado(id_pedido, estado_destino)
                self.assertIn("No se puede cambiar un pedido de cancelado a", str(ctx.exception))
                self.assertEqual(VarianteProducto.obtener_por_id(id_var)["stock"], stock_tras_cancelar)
                self.assertEqual(Pedido.obtener_por_id(id_pedido)["id_estado"], ESTADO_CANCELADO)

    def test_05_pedido_entregado_no_se_puede_cancelar(self):
        """5. Un pedido entregado no se puede cancelar ni cambiar a otro estado."""
        id_var = self.variantes_disponibles[0]
        items = self._preparar_carrito(self.id_usuario_1, id_var, 1)

        id_pedido = Pedido.crear_con_transaccion(
            id_usuario=self.id_usuario_1,
            id_direccion=self.id_direccion_1,
            id_metodo_pago=self.id_metodo_pago_1,
            total=Decimal("10000.00"),
            items=items,
        )
        self.pedidos_creados.append(id_pedido)

        # Avanzar por el flujo válido: pendiente (1) -> confirmado (2) -> en camino (3) -> entregado (4)
        Pedido.actualizar_estado(id_pedido, ESTADO_CONFIRMADO)
        Pedido.actualizar_estado(id_pedido, ESTADO_EN_CAMINO)
        Pedido.actualizar_estado(id_pedido, ESTADO_ENTREGADO)

        stock_en_entregado = VarianteProducto.obtener_por_id(id_var)["stock"]

        with self.assertRaises(ValueError) as ctx:
            Pedido.actualizar_estado(id_pedido, ESTADO_CANCELADO)
        self.assertEqual(str(ctx.exception), "No se puede cambiar un pedido de entregado a cancelado")
        self.assertEqual(VarianteProducto.obtener_por_id(id_var)["stock"], stock_en_entregado)
        self.assertEqual(Pedido.obtener_por_id(id_pedido)["id_estado"], ESTADO_ENTREGADO)

    def test_06_pedido_de_otro_usuario_devuelve_404(self):
        """6. Consultar el pedido de otro usuario en cuenta o confirmación devuelve HTTP 404."""
        id_var = self.variantes_disponibles[0]
        items = self._preparar_carrito(self.id_usuario_1, id_var, 1)

        id_pedido_u1 = Pedido.crear_con_transaccion(
            id_usuario=self.id_usuario_1,
            id_direccion=self.id_direccion_1,
            id_metodo_pago=self.id_metodo_pago_1,
            total=Decimal("10000.00"),
            items=items,
        )
        self.pedidos_creados.append(id_pedido_u1)

        # Iniciar sesión como usuario 2 e intentar ver el pedido del usuario 1
        with self.client.session_transaction() as sess:
            sess["id_usuario"] = self.id_usuario_2
            sess["id_rol"] = 1
            sess["edad_verificada"] = True

        res_cuenta = self.client.get(f"/cuenta/pedidos/{id_pedido_u1}")
        self.assertEqual(res_cuenta.status_code, 404)

        res_confirmacion = self.client.get(f"/carrito/confirmacion/{id_pedido_u1}")
        self.assertEqual(res_confirmacion.status_code, 404)

    def test_07_tipo_pago_invalido_y_tarjeta_en_claro_no_devuelven_500(self):
        """7. Un tipo_pago de 45 caracteres o un número de tarjeta de 16 dígitos son rechazados sin HTTP 500."""
        id_var = self.variantes_disponibles[0]
        self._preparar_carrito(self.id_usuario_1, id_var, 1)

        with self.client.session_transaction() as sess:
            sess["id_usuario"] = self.id_usuario_1
            sess["id_rol"] = 1
            sess["edad_verificada"] = True

        tipo_largo = "T" * 45  # 45 caracteres (excede VARCHAR(30))

        # En checkout
        res_checkout_tipo = self.client.post(
            "/carrito/checkout",
            data={
                "opcion_direccion": "guardada",
                "id_direccion": str(self.id_direccion_1),
                "opcion_pago": "nuevo",
                "tipo_pago": tipo_largo,
                "detalle_pago": "Terminada en 4242",
            },
        )
        self.assertNotEqual(res_checkout_tipo.status_code, 500)
        self.assertEqual(res_checkout_tipo.status_code, 200)
        self.assertIn("no está disponible para checkout".encode("utf-8"), res_checkout_tipo.data)

        # En checkout con número de tarjeta de 16 dígitos en detalle_pago
        res_checkout_tarjeta = self.client.post(
            "/carrito/checkout",
            data={
                "opcion_direccion": "guardada",
                "id_direccion": str(self.id_direccion_1),
                "opcion_pago": "nuevo",
                "tipo_pago": "Efectivo contra entrega",
                "detalle_pago": "4111 1111 1111 1111",
            },
        )
        self.assertNotEqual(res_checkout_tarjeta.status_code, 500)
        self.assertEqual(res_checkout_tarjeta.status_code, 200)
        self.assertIn(b"escribe solo los", res_checkout_tarjeta.data)

        # En /cuenta/metodos-pago/nuevo con tipo_pago de 45 caracteres
        res_cuenta_tipo = self.client.post(
            "/cuenta/metodos-pago/nuevo",
            data={
                "tipo": tipo_largo,
                "detalle": "Terminada en 4242",
            },
        )
        self.assertNotEqual(res_cuenta_tipo.status_code, 500)
        self.assertEqual(res_cuenta_tipo.status_code, 200)

        # Vaciar el carrito temporal antes de terminar
        carrito = Carrito.obtener_o_crear(self.id_usuario_1)
        Carrito.vaciar(carrito["id_carrito"])

    def test_08_checkout_rechaza_tipo_pago_no_permitido(self):
        """8. El checkout rechaza tipos de pago no permitidos (ej. Tarjeta de crédito) y no crea pedido."""
        id_var = self.variantes_disponibles[0]
        var_antes = VarianteProducto.obtener_por_id(id_var)
        stock_antes = var_antes["stock"]

        self._preparar_carrito(self.id_usuario_1, id_var, 1)

        with self.client.session_transaction() as sess:
            sess["id_usuario"] = self.id_usuario_1
            sess["id_rol"] = 1
            sess["edad_verificada"] = True

        # Intento con nuevo método de pago: "Tarjeta de crédito"
        res_nuevo = self.client.post(
            "/carrito/checkout",
            data={
                "opcion_direccion": "guardada",
                "id_direccion": str(self.id_direccion_1),
                "opcion_pago": "nuevo",
                "tipo_pago": "Tarjeta de crédito",
                "detalle_pago": "Terminada en 1234",
            },
            follow_redirects=False,
        )
        self.assertEqual(res_nuevo.status_code, 200)
        self.assertIn("no está disponible para checkout".encode("utf-8"), res_nuevo.data)

        # Intento con método guardado que no es de checkout (Tarjeta de crédito)
        res_guardado = self.client.post(
            "/carrito/checkout",
            data={
                "opcion_direccion": "guardada",
                "id_direccion": str(self.id_direccion_1),
                "opcion_pago": "guardado",
                "id_metodo_pago": str(self.id_metodo_pago_tarjeta),
            },
            follow_redirects=False,
        )
        self.assertEqual(res_guardado.status_code, 302)
        self.assertIn("/carrito/checkout", res_guardado.headers.get("Location", ""))

        # Verificar que el stock no fue descontado
        var_despues = VarianteProducto.obtener_por_id(id_var)
        self.assertEqual(var_despues["stock"], stock_antes)

        # Vaciar carrito de prueba
        carrito = Carrito.obtener_o_crear(self.id_usuario_1)
        Carrito.vaciar(carrito["id_carrito"])


if __name__ == "__main__":
    unittest.main()
