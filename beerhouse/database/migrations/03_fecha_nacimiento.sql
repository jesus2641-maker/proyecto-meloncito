-- ============================================
-- Migración 03: fecha de nacimiento del usuario
-- ============================================
-- Agrega la columna fecha_nacimiento a la tabla usuarios para poder
-- verificar la mayoría de edad (18+) al registrarse.
--
-- IMPORTANTE: este script se ejecuta UNA SOLA VEZ en bases de datos ya
-- creadas. Si la base se crea desde cero con schema.sql, la columna ya
-- existe y NO hay que correr esta migración (fallaría por columna duplicada).
-- Los usuarios existentes quedan con fecha_nacimiento en NULL.

USE beerhouse_db;

ALTER TABLE usuarios ADD COLUMN fecha_nacimiento DATE NULL AFTER telefono;
