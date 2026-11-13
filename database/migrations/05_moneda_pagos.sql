-- ============================================
-- Migración 05: Moneda y tasa de conversión en pagos
-- Beer House
-- ============================================

USE beerhouse_db;

ALTER TABLE pagos 
    ADD COLUMN tasa_cop_usd DECIMAL(10,2) NULL,
    ADD COLUMN monto_usd DECIMAL(10,2) NULL;
