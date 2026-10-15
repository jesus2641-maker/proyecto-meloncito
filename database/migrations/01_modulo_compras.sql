-- ============================================
-- Migración: Módulo de Compras e Inventario
-- Beer House
-- ============================================

USE beerhouse_db;

-- --------------------------------------------
-- Tabla: proveedores
-- Nota: Solo datos indispensables para identificar al proveedor.
-- Sin observaciones, email, teléfono ni dirección.
-- --------------------------------------------
CREATE TABLE IF NOT EXISTS proveedores (
    id_proveedor INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(150) NOT NULL,
    identificacion VARCHAR(50) NULL,
    activo BOOLEAN DEFAULT TRUE,
    fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- --------------------------------------------
-- Tabla: compras
-- --------------------------------------------
CREATE TABLE IF NOT EXISTS compras (
    id_compra INT AUTO_INCREMENT PRIMARY KEY,
    id_proveedor INT NOT NULL,
    id_usuario INT NOT NULL,
    fecha_compra DATETIME NOT NULL,
    total DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (id_proveedor) REFERENCES proveedores(id_proveedor),
    FOREIGN KEY (id_usuario) REFERENCES usuarios(id_usuario)
);

-- --------------------------------------------
-- Tabla: compra_detalle
-- --------------------------------------------
CREATE TABLE IF NOT EXISTS compra_detalle (
    id_detalle_compra INT AUTO_INCREMENT PRIMARY KEY,
    id_compra INT NOT NULL,
    id_variante INT NOT NULL,
    cantidad INT NOT NULL,
    precio_unitario DECIMAL(12,2) NOT NULL,
    subtotal DECIMAL(12,2) NOT NULL,
    FOREIGN KEY (id_compra) REFERENCES compras(id_compra) ON DELETE CASCADE,
    FOREIGN KEY (id_variante) REFERENCES variantes_producto(id_variante)
);

-- Proveedores iniciales de demostración si no existen
INSERT IGNORE INTO proveedores (id_proveedor, nombre, identificacion) VALUES
(1, 'Cervecería Nacional S.A.', 'NIT 890.900.123-1'),
(2, 'Distribuidora Premium de Licores S.A.S.', 'NIT 900.543.210-4'),
(3, 'Importadora Andina de Bebidas', 'NIT 860.012.345-6');
