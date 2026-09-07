from app.utils.db import get_connection

conn = get_connection()
cursor = conn.cursor(dictionary=True)

# Verificar total de productos
cursor.execute('SELECT COUNT(*) as total FROM productos')
productos_total = cursor.fetchone()
print(f'Total productos: {productos_total["total"]}')

# Verificar productos con categoria
cursor.execute('SELECT COUNT(*) as con_categoria FROM productos p JOIN productos_categorias pc ON p.id_producto = pc.id_producto')
con_categoria = cursor.fetchone()
print(f'Productos con categoria: {con_categoria["con_categoria"]}')

# Verificar productos sin categoria
cursor.execute('SELECT COUNT(*) as sin_categoria FROM productos p LEFT JOIN productos_categorias pc ON p.id_producto = pc.id_producto WHERE pc.id_categoria IS NULL')
sin_categoria = cursor.fetchone()
print(f'Productos sin categoria: {sin_categoria["sin_categoria"]}')

# Mostrar algunos productos sin categoria
cursor.execute('SELECT p.id_producto, p.nombre_producto FROM productos p LEFT JOIN productos_categorias pc ON p.id_producto = pc.id_producto WHERE pc.id_categoria IS NULL LIMIT 5')
sin_cat_productos = cursor.fetchall()
if sin_cat_productos:
    print('Productos sin categoria:')
    for p in sin_cat_productos:
        print(f'  - {p["id_producto"]}: {p["nombre_producto"]}')

cursor.close()
conn.close()
