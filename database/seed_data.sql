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
INSERT INTO productos (id_categoria, nombre_producto, descripcion, marca, imagen_url, activo) VALUES
(1, 'Johnnie Walker Black Label', 'Un whisky blend premium con notas de vainilla y frutas negras, ideal para celebraciones especiales.', 'Johnnie Walker', 'https://images.unsplash.com/photo-1598866584243', TRUE),
(1, 'Macallan 12 Años', 'Whisky single malt escocés añejado 12 años en barricas de roble americano y español.', 'Macallan', 'https://images.unsplash.com/photo-1596900336459', TRUE),
(2, 'Zacapa 23 Años', 'Ron premium guatemalteco añejado 23 años en barricas a gran altura, con notas de caramelo y frutas.', 'Ron Zacapa', 'https://images.unsplash.com/photo-1615609426035', TRUE),
(2, 'Havana Club 7 Años', 'Ron cubano añejado 7 años con notas de vainilla, cacao y frutas tropicales.', 'Havana Club', 'https://images.unsplash.com/photo-1594733532865', TRUE),
(3, 'Don Julio 1942', 'Tequila añejo premium 100% agave con notas de caramelo, vainilla y madera.', 'Don Julio', 'https://images.unsplash.com/photo-1569529465841', TRUE),
(3, 'Clase Azul Reposado', 'Tequila reposado 100% agave en botella artesanal, con notas de agave cocido y caramelo.', 'Clase Azul', 'https://images.unsplash.com/photo-1614269939325', TRUE),
(4, 'Grey Goose VX', 'Vodka premium francés filtrado a través de piedra caliza, con notas limpias y suaves.', 'Grey Goose', 'https://images.unsplash.com/photo-1594814699011', TRUE),
(5, 'Tanqueray 10', 'Gin premium británico con notas de cítricos y enebro, destilado cuatro veces.', 'Tanqueray', 'https://images.unsplash.com/photo-1604243446478', TRUE),
(6, 'Hennessy VSOP', 'Coniac premium francés con notas de roble, frutas secas y especias.', 'Hennessy', 'https://images.unsplash.com/photo-1597807867838', TRUE);

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