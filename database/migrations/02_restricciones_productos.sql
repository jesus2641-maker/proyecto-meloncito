-- Migración: Restricciones de productos
-- Cambiar descripcion de TEXT a VARCHAR(100) y agregar restricciones de valores negativos

USE beerhouse_db;

-- 1. Cambiar descripcion de TEXT a VARCHAR(100)
ALTER TABLE productos MODIFY COLUMN descripcion VARCHAR(100);

-- 2. Agregar restricción CHECK para stock (no negativo)
ALTER TABLE variantes_producto ADD CONSTRAINT chk_stock_no_negativo CHECK (stock >= 0);

-- 3. Agregar restricción CHECK para stock_minimo (no negativo)
ALTER TABLE variantes_producto ADD CONSTRAINT chk_stock_minimo_no_negativo CHECK (stock_minimo >= 0);

-- 4. Agregar restricción CHECK para precio (no negativo)
ALTER TABLE variantes_producto ADD CONSTRAINT chk_precio_no_negativo CHECK (precio >= 0);

-- 5. Verificar y corregir datos existentes que violen las restricciones
UPDATE variantes_producto SET stock = 0 WHERE stock < 0;
UPDATE variantes_producto SET stock_minimo = 0 WHERE stock_minimo < 0;
UPDATE variantes_producto SET precio = 0 WHERE precio < 0;

-- 6. Truncar descripciones existentes que excedan 100 caracteres
UPDATE productos SET descripcion = LEFT(descripcion, 100) WHERE LENGTH(descripcion) > 100;
