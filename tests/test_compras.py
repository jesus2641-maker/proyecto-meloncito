import unittest
from decimal import Decimal
from datetime import datetime
from app import create_app
from app.models import Proveedor, Compra, CompraDetalle, VarianteProducto
from app.utils.db import get_connection


class TestModuloCompras(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compras_creadas = []
        cls.proveedores_creados = []
        cls.stock_original = {}

        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        try:
            # Guardar el stock original de las variantes que las pruebas modifican
            cur.execute("SELECT id_variante, stock FROM variantes_producto ORDER BY id_variante LIMIT 2")
            variantes = cur.fetchall()
            cls.variantes_disponibles = [v["id_variante"] for v in variantes]
            for v in variantes:
                cls.stock_original[v["id_variante"]] = v["stock"]

            # Buscar un usuario existente para asociar las compras de prueba
            cur.execute("SELECT id_usuario FROM usuarios WHERE id_rol = 2 ORDER BY id_usuario LIMIT 1")
            admin = cur.fetchone()
            if not admin:
                cur.execute("SELECT id_usuario FROM usuarios ORDER BY id_usuario LIMIT 1")
                admin = cur.fetchone()
            cls.id_usuario_admin = admin["id_usuario"] if admin else None
        finally:
            cur.close()
            conn.close()

        # Crear un proveedor base de prueba para no depender de id_proveedor = 1
        cls.id_proveedor_base = Proveedor.crear(
            f"Proveedor Base Pruebas {int(datetime.now().timestamp())}",
            "NIT 900.000.001-0",
        )
        cls.proveedores_creados.append(cls.id_proveedor_base)

    @classmethod
    def tearDownClass(cls):
        conn = get_connection()
        cur = conn.cursor()
        try:
            # 1. Borrar primero compra_detalle y luego compras creadas en las pruebas
            compras_ids = list(dict.fromkeys(cls.compras_creadas))
            if compras_ids:
                placeholders = ", ".join(["%s"] * len(compras_ids))
                cur.execute(
                    f"DELETE FROM compra_detalle WHERE id_compra IN ({placeholders})",
                    tuple(compras_ids),
                )
                cur.execute(
                    f"DELETE FROM compras WHERE id_compra IN ({placeholders})",
                    tuple(compras_ids),
                )

            # 2. Borrar proveedores creados en las pruebas
            proveedores_ids = list(dict.fromkeys(cls.proveedores_creados))
            if proveedores_ids:
                placeholders = ", ".join(["%s"] * len(proveedores_ids))
                cur.execute(
                    f"DELETE FROM proveedores WHERE id_proveedor IN ({placeholders})",
                    tuple(proveedores_ids),
                )

            # 3. Restaurar EXACTAMENTE el stock original de las variantes
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
        self.app = create_app()
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_01_proveedor_crear_y_listar(self):
        """Verifica que se pueda registrar y listar un proveedor con datos mínimos."""
        nombre_test = f"Proveedor Test {int(datetime.now().timestamp())}"
        ident_test = "NIT 999.888.777-1"
        id_prov = Proveedor.crear(nombre_test, ident_test)
        self.proveedores_creados.append(id_prov)

        self.assertIsNotNone(id_prov)
        self.assertTrue(id_prov > 0)

        prov = Proveedor.obtener_por_id(id_prov)
        self.assertIsNotNone(prov)
        self.assertEqual(prov["nombre"], nombre_test)
        self.assertEqual(prov["identificacion"], ident_test)
        self.assertEqual(prov["activo"], 1)

        # Validación: nombre obligatorio
        with self.assertRaises(ValueError):
            Proveedor.crear("")

    def test_02_compra_transaccion_aumento_stock(self):
        """Verifica que una compra registre cabecera, detalles y aumente el stock atómicamente."""
        if not self.variantes_disponibles:
            self.skipTest("No existen variantes de producto en la base de datos para probar compras.")
        if not self.id_usuario_admin:
            self.skipTest("No existe ningún usuario en la base de datos para asociar la compra.")

        id_v1 = self.variantes_disponibles[0]
        v1 = VarianteProducto.obtener_por_id(id_v1)
        stock_inicial_v1 = v1["stock"]
        cant_v1 = 15
        precio_v1 = Decimal("12500.00")

        items = [
            {"id_variante": id_v1, "cantidad": cant_v1, "precio_unitario": precio_v1},
        ]
        total_esperado = Decimal(cant_v1) * precio_v1

        if len(self.variantes_disponibles) >= 2:
            id_v2 = self.variantes_disponibles[1]
            v2 = VarianteProducto.obtener_por_id(id_v2)
            stock_inicial_v2 = v2["stock"]
            cant_v2 = 8
            precio_v2 = Decimal("34000.00")
            items.append({"id_variante": id_v2, "cantidad": cant_v2, "precio_unitario": precio_v2})
            total_esperado += Decimal(cant_v2) * precio_v2

        fecha_compra = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Ejecutar compra atómica
        id_compra = Compra.crear_con_transaccion(
            id_proveedor=self.id_proveedor_base,
            id_usuario=self.id_usuario_admin,
            fecha_compra=fecha_compra,
            items=items,
        )
        self.compras_creadas.append(id_compra)

        self.assertIsNotNone(id_compra)
        self.assertTrue(id_compra > 0)

        # 1. Verificar cabecera
        compra = Compra.obtener_por_id(id_compra)
        self.assertIsNotNone(compra)
        self.assertEqual(Decimal(str(compra["total"])), total_esperado)

        # 2. Verificar detalles
        detalles = CompraDetalle.listar_por_compra(id_compra)
        self.assertEqual(len(detalles), len(items))
        subtotal_detalles = sum(Decimal(str(d["subtotal"])) for d in detalles)
        self.assertEqual(subtotal_detalles, total_esperado)

        # 3. VERIFICAR QUE EL STOCK AUMENTÓ EXACTAMENTE
        var1_actual = VarianteProducto.obtener_por_id(id_v1)
        self.assertEqual(var1_actual["stock"], stock_inicial_v1 + cant_v1)

        if len(self.variantes_disponibles) >= 2:
            var2_actual = VarianteProducto.obtener_por_id(id_v2)
            self.assertEqual(var2_actual["stock"], stock_inicial_v2 + cant_v2)

    def test_03_validaciones_y_rollback(self):
        """Verifica que cantidades <= 0, precios <= 0 o productos inexistentes fallen y hagan rollback sin alterar stock."""
        if not self.variantes_disponibles:
            self.skipTest("No existen variantes de producto en la base de datos para probar validaciones de compra.")
        if not self.id_usuario_admin:
            self.skipTest("No existe ningún usuario en la base de datos para asociar la compra.")

        id_var = self.variantes_disponibles[0]
        var = VarianteProducto.obtener_por_id(id_var)
        stock_original = var["stock"]

        # Caso A: Cantidad <= 0
        with self.assertRaises(ValueError):
            Compra.crear_con_transaccion(
                id_proveedor=self.id_proveedor_base,
                id_usuario=self.id_usuario_admin,
                fecha_compra=datetime.now(),
                items=[{"id_variante": id_var, "cantidad": 0, "precio_unitario": 1000}],
            )

        # Caso B: Cantidad negativa
        with self.assertRaises(ValueError):
            Compra.crear_con_transaccion(
                id_proveedor=self.id_proveedor_base,
                id_usuario=self.id_usuario_admin,
                fecha_compra=datetime.now(),
                items=[{"id_variante": id_var, "cantidad": -5, "precio_unitario": 1000}],
            )

        # Caso C: Precio unitario <= 0
        with self.assertRaises(ValueError):
            Compra.crear_con_transaccion(
                id_proveedor=self.id_proveedor_base,
                id_usuario=self.id_usuario_admin,
                fecha_compra=datetime.now(),
                items=[{"id_variante": id_var, "cantidad": 5, "precio_unitario": 0}],
            )

        # Caso D: Variante inexistente
        with self.assertRaises(ValueError):
            Compra.crear_con_transaccion(
                id_proveedor=self.id_proveedor_base,
                id_usuario=self.id_usuario_admin,
                fecha_compra=datetime.now(),
                items=[{"id_variante": 9999999, "cantidad": 5, "precio_unitario": 1000}],
            )

        # Caso E: Proveedor inexistente
        with self.assertRaises(ValueError):
            Compra.crear_con_transaccion(
                id_proveedor=9999999,
                id_usuario=self.id_usuario_admin,
                fecha_compra=datetime.now(),
                items=[{"id_variante": id_var, "cantidad": 5, "precio_unitario": 1000}],
            )

        # Comprobar que el stock NUNCA cambió tras los fallos (Rollback íntegro)
        var_despues = VarianteProducto.obtener_por_id(id_var)
        self.assertEqual(var_despues["stock"], stock_original)

    def test_04_rutas_admin_http(self):
        """Verifica que las rutas administrativas respondan con 200 a un usuario administrador."""
        with self.client.session_transaction() as sess:
            sess["id_usuario"] = self.id_usuario_admin or 1
            sess["id_rol"] = 2  # Rol admin

        # Historial de compras
        res = self.client.get("/admin/compras")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Historial de Compras", res.data)

        # Formulario de nueva compra
        res = self.client.get("/admin/compras/nueva")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Registrar Nueva Compra", res.data)

        # Proveedores
        res = self.client.get("/admin/proveedores")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Proveedores", res.data)

        # Inventario
        res = self.client.get("/admin/inventario")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Registrar Compra", res.data)

    def test_05_crear_compra_via_http_post(self):
        """Verifica el registro de compra vía POST SIN especificar fecha (fecha automática por sistema)."""
        if not self.variantes_disponibles:
            self.skipTest("No existen variantes de producto en la base de datos para probar compras vía HTTP.")
        if not self.id_usuario_admin:
            self.skipTest("No existe ningún usuario en la base de datos para asociar la compra.")

        with self.client.session_transaction() as sess:
            sess["id_usuario"] = self.id_usuario_admin
            sess["id_rol"] = 2

        id_var = self.variantes_disponibles[0]
        var = VarianteProducto.obtener_por_id(id_var)
        stock_ant = var["stock"]

        post_data = {
            "id_proveedor": str(self.id_proveedor_base),
            "id_variante[]": [str(id_var)],
            "cantidad[]": ["25"],
            "precio_unitario[]": ["6200.00"],
        }

        res = self.client.post("/admin/compras/nueva", data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"registrada exitosamente", res.data)

        # Registrar el id_compra recién creado para limpiarlo en tearDownClass
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                "SELECT id_compra FROM compras WHERE id_proveedor = %s ORDER BY id_compra DESC LIMIT 1",
                (self.id_proveedor_base,),
            )
            fila = cur.fetchone()
            if fila:
                self.compras_creadas.append(fila["id_compra"])
        finally:
            cur.close()
            conn.close()

        # Verificar que el stock aumentó en 25
        var_post = VarianteProducto.obtener_por_id(id_var)
        self.assertEqual(var_post["stock"], stock_ant + 25)

    def test_06_api_proveedor_rapido(self):
        """Verifica la creación rápida de proveedor vía AJAX JSON."""
        with self.client.session_transaction() as sess:
            sess["id_usuario"] = self.id_usuario_admin or 1
            sess["id_rol"] = 2

        res = self.client.post(
            "/admin/api/proveedores/rapido",
            json={"nombre": "Proveedor Express S.A.", "identificacion": "NIT 123456"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["nombre"], "Proveedor Express S.A.")
        if data.get("id_proveedor"):
            self.proveedores_creados.append(data["id_proveedor"])

    def test_07_seguridad_permisos_no_admin(self):
        """Verifica que un usuario no administrador (cliente o sin sesión) sea bloqueado."""
        # Sin sesión
        res = self.client.get("/admin/compras")
        self.assertEqual(res.status_code, 302)

        # Como cliente (id_rol = 1)
        with self.client.session_transaction() as sess:
            sess["id_usuario"] = 99
            sess["id_rol"] = 1

        res = self.client.get("/admin/compras")
        self.assertEqual(res.status_code, 302)

    def test_08_crud_completo_proveedores(self):
        """Verifica el CRUD completo de proveedores: Create, Read, Update, Delete y protección referencial."""
        with self.client.session_transaction() as sess:
            sess["id_usuario"] = self.id_usuario_admin or 1
            sess["id_rol"] = 2

        # 1. CREATE: Registrar proveedor
        nombre_original = f"Distribuidora Los Andes {int(datetime.now().timestamp())}"
        res = self.client.post(
            "/admin/proveedores/nuevo",
            data={
                "nombre": nombre_original,
                "identificacion": "NIT 800.111.222-3",
            },
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn(nombre_original.encode("utf-8"), res.data)

        # Obtener el ID del proveedor recién creado
        prov_creado = [p for p in Proveedor.listar() if p["nombre"] == nombre_original][0]
        id_prov = prov_creado["id_proveedor"]
        self.proveedores_creados.append(id_prov)

        # 2. READ & SEARCH: Filtrar por buscador
        res_search = self.client.get(f"/admin/proveedores?busqueda={nombre_original}")
        self.assertEqual(res_search.status_code, 200)
        self.assertIn(nombre_original.encode("utf-8"), res_search.data)

        # 3. UPDATE: Modificar nombre e identificación
        nombre_actualizado = nombre_original + " MODIFICADO"
        res_edit = self.client.post(
            f"/admin/proveedores/{id_prov}/editar",
            data={
                "nombre": nombre_actualizado,
                "identificacion": "NIT 800.111.999-9",
                "activo": "1",
            },
            follow_redirects=True,
        )
        self.assertEqual(res_edit.status_code, 200)
        self.assertIn(b"actualizado correctamente", res_edit.data)

        prov_editado = Proveedor.obtener_por_id(id_prov)
        self.assertEqual(prov_editado["nombre"], nombre_actualizado)
        self.assertEqual(prov_editado["identificacion"], "NIT 800.111.999-9")
        self.assertEqual(prov_editado["activo"], 1)

        # 4. TOGGLE: Desactivar y activar
        res_toggle = self.client.post(f"/admin/proveedores/{id_prov}/toggle", follow_redirects=True)
        self.assertEqual(res_toggle.status_code, 200)
        self.assertEqual(Proveedor.obtener_por_id(id_prov)["activo"], 0)

        # 5. DELETE: Eliminar proveedor sin compras asociadas
        res_del = self.client.post(f"/admin/proveedores/{id_prov}/eliminar", follow_redirects=True)
        self.assertEqual(res_del.status_code, 200)
        self.assertIn(b"eliminado correctamente", res_del.data)
        self.assertIsNone(Proveedor.obtener_por_id(id_prov))

        # 6. PROTECCIÓN REFERENCIAL: Crear un proveedor temporal, registrarle una compra
        # y comprobar que Proveedor.eliminar NO lo borra por tener compras
        if not self.variantes_disponibles:
            self.skipTest("No existen variantes de producto para probar protección referencial con compra.")
        if not self.id_usuario_admin:
            self.skipTest("No existe usuario para registrar la compra de protección referencial.")

        id_prov_con_compra = Proveedor.crear(
            f"Proveedor Protegido S.A. {int(datetime.now().timestamp())}",
            "NIT 800.555.666-7",
        )
        self.proveedores_creados.append(id_prov_con_compra)

        id_compra_temp = Compra.crear_con_transaccion(
            id_proveedor=id_prov_con_compra,
            id_usuario=self.id_usuario_admin,
            fecha_compra=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            items=[
                {
                    "id_variante": self.variantes_disponibles[0],
                    "cantidad": 5,
                    "precio_unitario": Decimal("5000.00"),
                }
            ],
        )
        self.compras_creadas.append(id_compra_temp)

        with self.assertRaises(ValueError):
            Proveedor.eliminar(id_prov_con_compra)
        self.assertIsNotNone(Proveedor.obtener_por_id(id_prov_con_compra))

        res_del_protegido = self.client.post(
            f"/admin/proveedores/{id_prov_con_compra}/eliminar", follow_redirects=True
        )
        self.assertEqual(res_del_protegido.status_code, 200)
        self.assertIn(b"No se puede eliminar el proveedor", res_del_protegido.data)
        self.assertIsNotNone(Proveedor.obtener_por_id(id_prov_con_compra))

    def test_09_apartados_editar_y_eliminar_vistas(self):
        """Verifica que los apartados GET para editar y eliminar proveedor carguen con HTTP 200."""
        with self.client.session_transaction() as sess:
            sess["id_usuario"] = self.id_usuario_admin or 1
            sess["id_rol"] = 2

        # Apartado para Editar Proveedor
        res_edit_view = self.client.get(f"/admin/proveedores/{self.id_proveedor_base}/editar")
        self.assertEqual(res_edit_view.status_code, 200)
        self.assertIn(b"Editar Proveedor", res_edit_view.data)
        self.assertIn(b"Apartado para Eliminar Proveedor", res_edit_view.data)

        # Apartado para Eliminar Proveedor
        res_del_view = self.client.get(f"/admin/proveedores/{self.id_proveedor_base}/eliminar")
        self.assertEqual(res_del_view.status_code, 200)
        self.assertIn(b"Apartado para Eliminar Proveedor", res_del_view.data)


if __name__ == "__main__":
    unittest.main()
