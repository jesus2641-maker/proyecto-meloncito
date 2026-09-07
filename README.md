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
│   ├── schema.sql       # Esquema de base de datos
│   └── seed_data.sql    # Datos de prueba
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

## Licencia

Este proyecto es de uso educativo.