-- ============================================
-- Migración 04: Tabla de pagos (PayPal)
-- Beer House
-- ============================================

USE beerhouse_db;

-- --------------------------------------------
-- Tabla: pagos
-- --------------------------------------------
CREATE TABLE IF NOT EXISTS pagos (
    id_pago INT AUTO_INCREMENT PRIMARY KEY,
    id_pedido INT NOT NULL,
    proveedor VARCHAR(20) NOT NULL DEFAULT 'paypal',
    paypal_order_id VARCHAR(64) NULL UNIQUE,
    paypal_capture_id VARCHAR(64) NULL,
    monto DECIMAL(10,2) NOT NULL,
    moneda CHAR(3) NOT NULL,
    estado ENUM('pendiente','completado','fallido','cancelado','reembolsado') NOT NULL DEFAULT 'pendiente',
    fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_pagos_id_pedido (id_pedido),
    FOREIGN KEY (id_pedido) REFERENCES pedidos(id_pedido) ON DELETE RESTRICT
);
