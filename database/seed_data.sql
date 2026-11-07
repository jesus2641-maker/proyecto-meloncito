-- ============================================
-- Beer House - Datos de prueba
-- ============================================

USE beerhouse_db;

-- Insertar categorías de prueba
INSERT INTO categorias (nombre_categoria, descripcion) VALUES
('Whisky', 'Colección de whiskies premium de las mejores destilerías del mundo'),
('Ron', 'Rones añejos y premium del Caribe y América Latina'),
('Tequila', 'Tequilas 100% agave de las mejores regiones de México'),
('Vodka', 'Vodkas premium de calidad superior'),
('Gin', 'Gins artesanales y premium de alta calidad'),
('Brandy', 'Coniacs y brandys premium de las mejores regiones');

-- Insertar productos de prueba
INSERT INTO productos (nombre_producto, descripcion, marca, imagen_url, activo) VALUES
('Johnnie Walker Black Label', 'Un whisky blend premium con notas de vainilla y frutas negras, ideal para celebraciones especiales.', 'Johnnie Walker', 'https://images.unsplash.com/photo-1598866584243', TRUE),
('Macallan 12 Años', 'Whisky single malt escocés añejado 12 años en barricas de roble americano y español.', 'Macallan', 'https://images.unsplash.com/photo-1596900336459', TRUE),
('Zacapa 23 Años', 'Ron premium guatemalteco añejado 23 años en barricas a gran altura, con notas de caramelo y frutas.', 'Ron Zacapa', 'https://images.unsplash.com/photo-1615609426035', TRUE),
('Havana Club 7 Años', 'Ron cubano añejado 7 años con notas de vainilla, cacao y frutas tropicales.', 'Havana Club', 'https://images.unsplash.com/photo-1594733532865', TRUE),
('Don Julio 1942', 'Tequila añejo premium 100% agave con notas de caramelo, vainilla y madera.', 'Don Julio', 'https://images.unsplash.com/photo-1569529465841', TRUE),
('Clase Azul Reposado', 'Tequila reposado 100% agave en botella artesanal, con notas de agave cocido y caramelo.', 'Clase Azul', 'https://images.unsplash.com/photo-1614269939325', TRUE),
('Grey Goose VX', 'Vodka premium francés filtrado a través de piedra caliza, con notas limpias y suaves.', 'Grey Goose', 'https://images.unsplash.com/photo-1594814699011', TRUE),
('Tanqueray 10', 'Gin premium británico con notas de cítricos y enebro, destilado cuatro veces.', 'Tanqueray', 'https://images.unsplash.com/photo-1604243446478', TRUE),
('Hennessy VSOP', 'Coniac premium francés con notas de roble, frutas secas y especias.', 'Hennessy', 'https://images.unsplash.com/photo-1597807867838', TRUE);

-- Insertar relaciones productos_categorias
INSERT INTO productos_categorias (id_producto, id_categoria) VALUES
(1, 1), (2, 1),  -- Whisky
(3, 2), (4, 2),  -- Ron
(5, 3), (6, 3),  -- Tequila
(7, 4),          -- Vodka
(8, 5),          -- Gin
(9, 6);          -- Brandy

-- Insertar usuarios de prueba
INSERT IGNORE INTO usuarios (nombre, apellido, email, password_hash, fecha_nacimiento, id_rol, activo) VALUES
('Admin', 'Beer House', 'admin@beerhouse.com', 'scrypt:32768:8:1$uJioUTTyjscoa90r$9846e9dbb3ef3bdba5c83bb1423ca5086c523c855da1a1ffac3ca28b5184abee5f1b5e2b23274ccd09fd477a8d384cc2c685ae847214214367e20dfdfc112a75', '1990-05-15', 2, TRUE),
('Trabajador', 'Beer House', 'trabajador@beerhouse.com', 'scrypt:32768:8:1$9gh9JRSFJy5ZiF6p$ebcfac14ca59f38c4b31a902f7b2fa6f78d190e0c1fd11872e2bb056d6862a988cf10462731be0de572394c4f7cca0669132ad12944f8134e848fcc94c74ce18', '1995-03-20', 4, TRUE),
('Cliente', 'Beer House', 'cliente@beerhouse.com', 'scrypt:32768:8:1$5QWrq8T5t96roKwu$09a9ee7bccca20bfaa50cd2c7a54084ef803b1653739ced8f36e84e33217948211cf5b2a142c6fd42c6243b38b773fedaa99159a1fd5c66325b6f5cef70b38d7', '1998-08-10', 1, TRUE);

-- Insertar variantes de producto (presentaciones, precios y stock)
INSERT INTO variantes_producto (id_producto, presentacion, precio, stock, sku) VALUES
-- Johnnie Walker Black Label
(1, '750ml', 45.99, 50, 'JW-BL-750'),
(1, '1L', 59.99, 30, 'JW-BL-1L'),
-- Macallan 12 Años
(2, '700ml', 89.99, 25, 'MAC-12-700'),
(2, '1L', 129.99, 15, 'MAC-12-1L'),
-- Zacapa 23 Años
(3, '750ml', 75.99, 40, 'ZAC-23-750'),
-- Havana Club 7 Años
(4, '700ml', 32.99, 60, 'HC-7-700'),
(4, '1L', 44.99, 35, 'HC-7-1L'),
-- Don Julio 1942
(5, '750ml', 159.99, 20, 'DJ-1942-750'),
-- Clase Azul Reposado
(6, '750ml', 139.99, 25, 'CA-REP-750'),
-- Grey Goose VX
(7, '750ml', 65.99, 45, 'GG-VX-750'),
(7, '1L', 89.99, 20, 'GG-VX-1L'),
-- Tanqueray 10
(8, '750ml', 49.99, 55, 'TAN-10-750'),
-- Hennessy VSOP
(9, '700ml', 69.99, 40, 'HEN-VSOP-700'),
(9, '1L', 95.99, 25, 'HEN-VSOP-1L');