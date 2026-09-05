import unittest
from decimal import Decimal
from datetime import datetime
from app import create_app
from app.models import Proveedor, Compra, CompraDetalle, VarianteProducto
from app.utils.db import get_connection


class TestModuloCompras(unittest.TestCase):
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
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        
        # Buscar un usuario admin existente para asociar la compra
        cur.execute("SELECT id_usuario FROM usuarios WHERE id_rol = 2 LIMIT 1")
        admin = cur.fetchone()
        id_usuario = admin["id_usuario"] if admin else 1

        # Obtener un proveedor existente
        cur.execute("SELECT id_proveedor FROM proveedores WHERE activo = TRUE LIMIT 1")
        prov = cur.fetchone()
        id_proveedor = prov["id_proveedor"]

        # Obtener dos variantes de producto existentes
        cur.execute("SELECT id_variante, stock FROM variantes_producto LIMIT 2")
        variantes = cur.fetchall()
        cur.close()
        conn.close()

        self.assertTrue(len(variantes) >= 2, "Deben existir al menos 2 variantes en la base de datos para la prueba")
        v1 = variantes[0]
        v2 = variantes[1]

        stock_inicial_v1 = v1["stock"]
        stock_inicial_v2 = v2["stock"]

        cant_v1 = 15
        precio_v1 = Decimal("12500.00")
        cant_v2 = 8
        precio_v2 = Decimal("34000.00")

        total_esperado = (Decimal(cant_v1) * precio_v1) + (Decimal(cant_v2) * precio_v2)

        items = [
            {"id_variante": v1["id_variante"], "cantidad": cant_v1, "precio_unitario": precio_v1},
            {"id_variante": v2["id_variante"], "cantidad": cant_v2, "precio_unitario": precio_v2}
        ]

        fecha_compra = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Ejecutar compra atómica
        id_compra = Compra.crear_con_transaccion(
            id_proveedor=id_proveedor,
            id_usuario=id_usuario,
            fecha_compra=fecha_compra,
            items=items
        )
        self.assertIsNotNone(id_compra)
        self.assertTrue(id_compra > 0)

        # 1. Verificar cabecera
        compra = Compra.obtener_por_id(id_compra)
        self.assertIsNotNone(compra)
        self.assertEqual(Decimal(str(compra["total"])), total_esperado)

        # 2. Verificar detalles
        detalles = CompraDetalle.listar_por_compra(id_compra)
        self.assertEqual(len(detalles), 2)
        subtotal_detalles = sum(Decimal(str(d["subtotal"])) for d in detalles)
        self.assertEqual(subtotal_detalles, total_esperado)

        # 3. VERIFICAR QUE EL STOCK AUMENTÓ EXACTAMENTE
        var1_actual = VarianteProducto.obtener_por_id(v1["id_variante"])
        var2_actual = VarianteProducto.obtener_por_id(v2["id_variante"])

        self.assertEqual(var1_actual["stock"], stock_inicial_v1 + cant_v1)
        self.assertEqual(var2_actual["stock"], stock_inicial_v2 + cant_v2)

    def test_03_validaciones_y_rollback(self):
        """Verifica que cantidades <= 0, precios <= 0 o productos inexistentes fallen y hagan rollback sin alterar stock."""
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id_variante, stock FROM variantes_producto LIMIT 1")
        var = cur.fetchone()
        cur.close()
        conn.close()

        stock_original = var["stock"]
        id_var = var["id_variante"]

        # Caso A: Cantidad <= 0
        with self.assertRaises(ValueError):
            Compra.crear_con_transaccion(
                id_proveedor=1,
                id_usuario=1,
                fecha_compra=datetime.now(),
                items=[{"id_variante": id_var, "cantidad": 0, "precio_unitario": 1000}]
            )

        # Caso B: Cantidad negativa
        with self.assertRaises(ValueError):
            Compra.crear_con_transaccion(
                id_proveedor=1,
                id_usuario=1,
                fecha_compra=datetime.now(),
                items=[{"id_variante": id_var, "cantidad": -5, "precio_unitario": 1000}]
            )

        # Caso C: Precio unitario <= 0
        with self.assertRaises(ValueError):
            Compra.crear_con_transaccion(
                id_proveedor=1,
                id_usuario=1,
                fecha_compra=datetime.now(),
                items=[{"id_variante": id_var, "cantidad": 5, "precio_unitario": 0}]
            )

        # Caso D: Variante inexistente
        with self.assertRaises(ValueError):
            Compra.crear_con_transaccion(
                id_proveedor=1,
                id_usuario=1,
                fecha_compra=datetime.now(),
                items=[{"id_variante": 9999999, "cantidad": 5, "precio_unitario": 1000}]
            )

        # Caso E: Proveedor inexistente
        with self.assertRaises(ValueError):
            Compra.crear_con_transaccion(
                id_proveedor=9999999,
                id_usuario=1,
                fecha_compra=datetime.now(),
                items=[{"id_variante": id_var, "cantidad": 5, "precio_unitario": 1000}]
            )

        # Comprobar que el stock NUNCA cambió tras los fallos (Rollback íntegro)
        var_despues = VarianteProducto.obtener_por_id(id_var)
        self.assertEqual(var_despues["stock"], stock_original)

    def test_04_rutas_admin_http(self):
        """Verifica que las rutas administrativas respondan con 200 a un usuario administrador."""
        # Simular sesión de administrador (id_rol = 2)
        with self.client.session_transaction() as sess:
            sess["id_usuario"] = 1
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
        with self.client.session_transaction() as sess:
            sess["id_usuario"] = 1
            sess["id_rol"] = 2

        # Obtener una variante para probar
        var = VarianteProducto.obtener_inventario()[0]
        id_var = var["id_variante"]
        stock_ant = var["stock"]

        # Formulario sin fecha_compra
        post_data = {
            "id_proveedor": "1",
            "id_variante[]": [str(id_var)],
            "cantidad[]": ["25"],
            "precio_unitario[]": ["6200.00"]
        }

        res = self.client.post("/admin/compras/nueva", data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"registrada exitosamente", res.data)

        # Verificar que el stock aumentó en 25
        var_post = VarianteProducto.obtener_por_id(id_var)
        self.assertEqual(var_post["stock"], stock_ant + 25)

    def test_06_api_proveedor_rapido(self):
        """Verifica la creación rápida de proveedor vía AJAX JSON."""
        with self.client.session_transaction() as sess:
            sess["id_usuario"] = 1
            sess["id_rol"] = 2

        res = self.client.post(
            "/admin/api/proveedores/rapido",
            json={"nombre": "Proveedor Express S.A.", "identificacion": "NIT 123456"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["nombre"], "Proveedor Express S.A.")

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
            sess["id_usuario"] = 1
            sess["id_rol"] = 2

        # 1. CREATE: Registrar proveedor
        nombre_original = f"Distribuidora Los Andes {int(datetime.now().timestamp())}"
        res = self.client.post("/admin/proveedores/nuevo", data={
            "nombre": nombre_original,
            "identificacion": "NIT 800.111.222-3"
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(nombre_original.encode("utf-8"), res.data)

        # Obtener el ID del proveedor recién creado
        prov_creado = [p for p in Proveedor.listar() if p["nombre"] == nombre_original][0]
        id_prov = prov_creado["id_proveedor"]

        # 2. READ & SEARCH: Filtrar por buscador
        res_search = self.client.get(f"/admin/proveedores?busqueda={nombre_original}")
        self.assertEqual(res_search.status_code, 200)
        self.assertIn(nombre_original.encode("utf-8"), res_search.data)

        # 3. UPDATE: Modificar nombre e identificación
        nombre_actualizado = nombre_original + " MODIFICADO"
        res_edit = self.client.post(f"/admin/proveedores/{id_prov}/editar", data={
            "nombre": nombre_actualizado,
            "identificacion": "NIT 800.111.999-9",
            "activo": "1"
        }, follow_redirects=True)
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

        # 6. PROTECCIÓN REFERENCIAL: Intentar eliminar proveedor que tiene compras (id_proveedor = 1)
        res_del_protegido = self.client.post("/admin/proveedores/1/eliminar", follow_redirects=True)
        self.assertEqual(res_del_protegido.status_code, 200)
        self.assertIn(b"No se puede eliminar el proveedor", res_del_protegido.data)

    def test_09_apartados_editar_y_eliminar_vistas(self):
        """Verifica que los apartados GET para editar y eliminar proveedor carguen con HTTP 200."""
        with self.client.session_transaction() as sess:
            sess["id_usuario"] = 1
            sess["id_rol"] = 2

        # Apartado para Editar Proveedor
        res_edit_view = self.client.get("/admin/proveedores/1/editar")
        self.assertEqual(res_edit_view.status_code, 200)
        self.assertIn(b"Editar Proveedor", res_edit_view.data)
        self.assertIn(b"Apartado para Eliminar Proveedor", res_edit_view.data)

        # Apartado para Eliminar Proveedor
        res_del_view = self.client.get("/admin/proveedores/1/eliminar")
        self.assertEqual(res_del_view.status_code, 200)
        self.assertIn(b"Apartado para Eliminar Proveedor", res_del_view.data)


if __name__ == "__main__":
    unittest.main()




