# Beer House Premium Spirits

Sistema de e-commerce para venta de licores premium desarrollado con Flask.

## Características

- **Catálogo de productos**: Gestión completa de licores con múltiples categorías
- **Sistema de usuarios**: Roles de cliente, administrador y trabajador
- **Carrito de compras**: Funcionalidad completa de compra
- **Gestión de pedidos**: Seguimiento de estados de pedidos
- **Panel de administración**: Gestión de productos, categorías, inventario y usuarios
- **Panel de trabajador**: Funcionalidades limitadas para trabajadores
- **Sistema de ofertas**: Gestión de promociones y descuentos
- **Relación muchos a muchos**: Productos pueden pertenecer a múltiples categorías

## Tecnologías

- **Backend**: Flask (Python)
- **Base de datos**: MySQL
- **Frontend**: HTML5, CSS3, Jinja2 templates
- **Autenticación**: Sistema de sesiones Flask

## Instalación

1. Clonar el repositorio
2. Crear entorno virtual:
   ```bash
   python -m venv venv
   venv\Scripts\activate  # Windows
   source venv/bin/activate  # Linux/Mac
   ```

3. Instalar dependencias:
   ```bash
   pip install -r requirements.txt
   ```

4. Configurar base de datos:
   - Crear base de datos MySQL
   - Configurar archivo `.env` con credenciales:
     ```
     DATABASE_HOST=localhost
     DATABASE_USER=tu_usuario
     DATABASE_PASSWORD=tu_contraseña
     DATABASE_NAME=beerhouse_db
     SECRET_KEY=tu_clave_secreta
     ```

5. Ejecutar esquema de base de datos:
   ```bash
   mysql -u tu_usuario -p beerhouse_db < database/schema.sql
   ```

6. (Opcional) Cargar datos de prueba:
   ```bash
   mysql -u tu_usuario -p beerhouse_db < database/seed_data.sql
   ```

## Ejecución

```bash
python run.py
```

La aplicación estará disponible en `http://127.0.0.1:5000`

## Docker

El proyecto incluye `Dockerfile` y `docker-compose.yml` con dos servicios: `db` (MySQL 8.0) y `app` (Flask).

- Los scripts montados en `/docker-entrypoint-initdb.d` (`01-schema.sql` y `02-seed_data.sql`) **solo se ejecutan la primera vez** que se crea el volumen `beerhouse_mysql_data`.
- Si deseas reiniciar la base de datos desde cero (borrar el volumen y volver a correr `initdb`), ejecuta:
  ```bash
  docker compose down -v
  docker compose up --build
  ```
- Para cargar los datos de demostración de reportes dentro del contenedor de la aplicación (`app`):
  ```bash
  docker compose exec app python -m scripts.generar_datos_demo
  ```

## Cómo correr las pruebas

Ejecutar desde la raíz del proyecto:

- **Solo las pruebas unitarias que no usan base de datos:**
  ```bash
  python -m unittest tests.test_edad tests.test_reportes tests.test_validaciones
  ```

- **Todas las pruebas (incluyendo integración con base de datos):**
  ```bash
  python -m unittest discover -s tests -t .
  ```

> **Nota:** `tests/test_compras.py` requiere tener la base de datos MySQL configurada y cargada con `database/schema.sql` y `database/seed_data.sql`.

## Credenciales de prueba

**Administrador:**
- Email: admin@beerhouse.com
- Contraseña: admin123

**Trabajador:**
- Email: trabajador@beerhouse.com
- Contraseña: trabajador123

## Estructura del proyecto

```
beerhouse/
├── app/
│   ├── models/          # Modelos de base de datos
│   ├── routes/          # Rutas de la aplicación
│   ├── templates/       # Plantillas HTML
│   ├── static/          # Archivos estáticos
│   └── utils/           # Utilidades
├── database/
│   ├── migrations/      # Migraciones incrementales SQL
│   ├── schema.sql       # Esquema de base de datos
│   └── seed_data.sql    # Datos de prueba
├── scripts/             # Scripts de mantenimiento y generación de datos demo
├── tests/               # Pruebas automatizadas (unittest)
├── config.py            # Configuración de la aplicación
├── run.py               # Punto de entrada
└── requirements.txt     # Dependencias
```

## Funcionalidades principales

### Administración
- Gestión de productos con múltiples categorías
- Gestión de categorías
- Control de inventario con alertas de stock
- Gestión de usuarios y roles
- Gestión de pedidos
- Creación de ofertas y promociones

### Cliente
- Navegación por catálogo
- Filtrado por categorías
- Carrito de compras
- Gestión de direcciones y métodos de pago
- Historial de pedidos

### Trabajador
- Gestión limitada de productos
- Control de inventario
- Gestión de pedidos
- Gestión de clientes

## Características técnicas

- **Relación muchos a muchos**: Productos pueden pertenecer a múltiples categorías
- **Variantes de producto**: Un producto puede tener múltiples presentaciones con diferentes precios y stock
- **Sistema de roles**: Control de acceso basado en roles
- **Alertas de stock**: Notificaciones automáticas de stock bajo
- **Transacciones de base de datos**: Integridad de datos garantizada

## Pagos con PayPal (Sandbox)

La tienda integra la pasarela de pagos oficial de PayPal mediante **PayPal Orders v2** y el **PayPal JavaScript SDK**.

### 1. Obtención de Credenciales de Prueba
1. Ingresa a [PayPal Developer](https://developer.paypal.com) con tu cuenta de PayPal.
2. Ve a **Dashboard** &rarr; **Apps & Credentials**.
3. Selecciona la pestaña **Sandbox** y abre la aplicación por defecto (**Default Application**) o crea una nueva app.
4. Copia el **Client ID** y el **Secret**.

### 2. Variables de Entorno en `.env`
Configura las siguientes variables en tu archivo `.env`:
```env
PAYPAL_CLIENT_ID=tu_client_id_sandbox
PAYPAL_CLIENT_SECRET=tu_client_secret_sandbox
PAYPAL_MODE=sandbox
PAYPAL_CURRENCY=USD
PAGO_EXPIRA_MINUTOS=30
```
- `PAYPAL_MODE`: Define el entorno de ejecución (`sandbox` para pruebas, `live` para producción).
- `PAYPAL_CURRENCY`: Moneda en la que opera la pasarela (por defecto `USD`).
- `PAGO_EXPIRA_MINUTOS`: Tiempo en minutos que el pedido y el stock permanecen reservados mientras el usuario completa el pago antes de expirar automáticamente.

### 3. Prueba de Compra con Cuenta Sandbox
1. En el Dashboard de PayPal Developer, navega a **Testing Tools** &rarr; **Sandbox Accounts**.
2. Identifica la cuenta con tipo **Personal (Buyer)** creada automáticamente por PayPal (o crea una cuenta personal de prueba).
3. Haz clic en los tres puntos de la cuenta y selecciona **View/Edit Account** para ver el correo de prueba generado y la contraseña predeterminada.
4. En Beer House, agrega productos al carrito y procede al Checkout.
5. Selecciona la opción **PayPal** y confirma. En la pantalla de pago se mostrará el botón oficial de PayPal.
6. En la ventana emergente de PayPal, inicia sesión con las credenciales del comprador Sandbox y completa la autorización. Al volver a Beer House, la transacción se capturará y se enviará el correo de confirmación.

### 4. Moneda y Procesamiento en USD
- **Aviso de moneda**: La integración de sandbox procesa los montos en **USD**. En el checkout y en la pantalla de pago se visualiza el total en COP y el equivalente aproximado en USD calculado según la configuración de la tienda.

### 5. Disponibilidad y Contingencia Offline
- Si las credenciales de PayPal no están configuradas en `.env`, la opción de PayPal aparecerá deshabilitada en el Checkout con la etiqueta "(No disponible)".
- Si ocurre una falla de conectividad con los servidores de PayPal durante la carga del botón, se mostrará un mensaje amigable permitiendo al usuario volver al checkout y pagar con **Efectivo contra entrega**.

## Licencia

Este proyecto es de uso educativo.

## Despliegue en Railway

La app se despliega con el `Dockerfile` (Railway lo detecta solo). Al arrancar,
`start.sh` ejecuta `scripts/init_db.py`, que crea las tablas y carga el seed si
la base está vacía (es idempotente), y luego levanta gunicorn en `$PORT`.

### 1. Crear el proyecto
1. En Railway: **New Project → Deploy from GitHub repo** y elige este repo.
2. En el mismo proyecto: **+ New → Database → MySQL**.

### 2. Variables del servicio de la app (pestaña *Variables*)
```
DATABASE_URL=${{MySQL.MYSQL_URL}}
SECRET_KEY=<cadena aleatoria de 32+ caracteres>
SESSION_COOKIE_SECURE=true
TASA_COP_USD=4000
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
BREVO_API_KEY=...
BREVO_SENDER_EMAIL=...
BREVO_SENDER_NAME=...
PAYPAL_CLIENT_ID=...
PAYPAL_CLIENT_SECRET=...
PAYPAL_MODE=sandbox
PAYPAL_CURRENCY=USD
```
`${{MySQL.MYSQL_URL}}` es una referencia: Railway la reemplaza por la URL
privada del servicio MySQL (el nombre debe coincidir con el del servicio).

Generar una SECRET_KEY: `python -c "import secrets; print(secrets.token_hex(32))"`

### 3. Ajustes del servicio (pestaña *Settings*)
- **Networking → Generate Domain** para obtener la URL pública.
- **Deploy → Healthcheck Path:** `/health` (responde 200 si la app y la BD están vivas).

### Variables opcionales
| Variable | Default | Uso |
|---|---|---|
| `RUN_DB_INIT` | `1` | `0` para no tocar la BD al arrancar |
| `WEB_CONCURRENCY` | `2` | workers de gunicorn |
| `GUNICORN_THREADS` | `4` | hilos por worker |
| `GUNICORN_TIMEOUT` | `60` | segundos |

### Conexión a la BD
`config.py` acepta, en este orden: `DATABASE_URL`/`MYSQL_URL`, las variables
`DATABASE_*` (incluye `DATABASE_PORT`) o las `MYSQL*` que inyecta Railway.
