# Resumen de Documentación — Beer House (ADSO / SENA)

Proyecto web de tienda de licores desarrollado en **Flask + MySQL/TiDB Cloud** usando Blueprints, Flask-WTF (CSRF), Jinja2 y Bootstrap 5.

## 1. Estructura de Carpetas

- **Raíz del proyecto**:
  - `config.py`: Carga variables de entorno (`.env`), configura sesiones, CSRF, base de datos (con SSL), Cloudinary, Brevo y PayPal.
  - `run.py`: Punto de entrada para ejecutar la aplicación en local.
  - `importar_schema.py`: Script auxiliar para importar `database/schema.sql` en MySQL/TiDB Cloud.
- **`api/`**: `index.py` expone la instancia `app` para despliegue serverless en Vercel.
- **`app/`**: Paquete principal de la aplicación (`__init__.py` implementa `create_app()`, registra `ProxyFix`, `CSRFProtect`, cierre automático de BD, hook de mayoría de edad, `context_processor` del carrito y manejadores 404/500).
  - **`app/models/`**: Clases de acceso a datos con SQL directo (`Usuario`, `Categoria`, `Producto`/`VarianteProducto`, `Carrito`/`CarritoItem`, `Pedido`/`PedidoDetalle`, `Pago`, `Direccion`, `MetodoPago`, `Oferta`, `Proveedor`, `Compra`/`CompraDetalle`, `Reporte`).
  - **`app/routes/`**: Blueprints que separan las rutas por módulo y rol.
  - **`app/services/`**: Lógica de negocio compleja (orquestación de pagos, capturas, reembolsos y expiración de pedidos en `pagos_paypal.py`).
  - **`app/utils/`**: Utilidades transversales (`db.py`, `decoradores.py`, `validaciones.py`, `moneda.py`, `paypal_client.py`, `email_service.py`, `cloudinary_utils.py`, `login_attempts.py`, `reportes_utils.py`).
  - **`app/templates/`** y **`app/static/`**: Vistas HTML/Jinja2 (tienda pública, `auth/`, `carrito/`, `cuenta/`, `admin/`, `trabajador/`, `pagos/`, `edad/`, `errors/`) y estilos/scripts JS.
- **`database/`**: `schema.sql`, datos semilla (`seed_data.sql`, `seed_data_cop.sql`) y migraciones en `migrations/`.
- **`scripts/`**: Utilidades de mantenimiento (inicialización de BD, diagnóstico de stock, limpieza de tarjetas, datos demo).
- **`tests/`**: Pruebas unitarias y de integración con `unittest` (edad, validaciones, pedidos, compras, pagos, reportes).

## 2. Blueprints (`app/routes/`)

| Blueprint | Prefijo | Qué hace y quién lo usa |
| :--- | :--- | :--- |
| `auth_bp` | `/auth` | Login, registro de clientes (18+) y cierre de sesión; redirige según el rol (`cliente=1`, `admin=2`, `trabajador=4`). |
| `edad_bp` | `/` | Filtro legal de mayoría de edad (`/verificar-edad` y `/acceso-restringido`) mediante cookie `mayor_edad`. |
| `productos_bp` | `/productos` | Catálogo público con búsqueda, filtro por categoría y detalle de variantes/stock. |
| `categorias_bp` | `/` | Vista pública `/categorias` con el listado dinámico desde BD. |
| `carrito_bp` | `/carrito` | Carrito del cliente: ver, agregar (soporta formulario y AJAX/JSON), actualizar, eliminar, checkout y confirmación. |
| `cuenta_bp` | `/cuenta` | Panel del cliente: perfil, direcciones de envío, métodos de pago guardados e historial/cancelación de pedidos. |
| `pagos_bp` | `/pagos` | Flujo de pago con PayPal Orders v2 (crear orden, capturar pago, retorno y cancelación). |
| `admin_bp` | `/admin` | Panel exclusivo del **Administrador (`id_rol=2`)**: dashboard, CRUD de productos/variantes/categorías/ofertas/proveedores, compras, usuarios, reportes CSV y cancelación con reembolso. |
| `trabajador_bp` | `/trabajador` | Panel operativo para **Trabajador (`id_rol=4`)** y Admin: ver productos/clientes, actualizar stock y avanzar pedidos (sin permisos para cancelar pedidos ni gestionar usuarios/compras). |
| `api_bp` | `/api/v1` | Endpoints JSON públicos (productos, categorías, ofertas), de cliente (carrito, pedidos) y operativos (inventario, estadísticas). |
