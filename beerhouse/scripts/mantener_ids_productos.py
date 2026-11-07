"""
Script de mantenimiento para asegurar IDs automaticos de productos
Este script verifica y corrige cualquier inconsistencia en el sistema de IDs
"""

from app.utils.db import get_connection

def verificar_y_corregir_ids():
    """Verifica y corrige la integridad de IDs de productos"""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # 1. Verificar productos sin ID
        cursor.execute('SELECT COUNT(*) as sin_id FROM productos WHERE id_producto IS NULL')
        result_null = cursor.fetchone()
        
        if result_null["sin_id"] > 0:
            print(f"[ALERTA] Encontrados {result_null['sin_id']} productos sin ID")
            # Obtener el máximo ID existente
            cursor.execute('SELECT MAX(id_producto) as max_id FROM productos')
            max_id = cursor.fetchone()["max_id"] or 0

            # Asignar IDs a productos sin ID
            cursor.execute('SELECT id_producto FROM productos WHERE id_producto IS NULL')
            productos_sin_id = cursor.fetchall()

            for p in productos_sin_id:
                max_id += 1
                cursor.execute(
                    'UPDATE productos SET id_producto = %s WHERE id_producto IS NULL LIMIT 1',
                    (max_id,)
                )

            conn.commit()
            print(f"[OK] Asignados IDs a {len(productos_sin_id)} productos")
        else:
            print("[OK] Todos los productos tienen ID asignado")

        # 2. Sincronizar AUTO_INCREMENT
        cursor.execute('SELECT MAX(id_producto) as max_id FROM productos')
        max_id = cursor.fetchone()["max_id"] or 0

        cursor.execute(f"ALTER TABLE productos AUTO_INCREMENT = {max_id + 1}")
        conn.commit()
        print(f"[OK] AUTO_INCREMENT sincronizado a {max_id + 1}")

        # 3. Verificar integridad de relaciones
        cursor.execute('''
            SELECT COUNT(*) as count
            FROM variantes_producto v
            LEFT JOIN productos p ON v.id_producto = p.id_producto
            WHERE p.id_producto IS NULL
        ''')
        orphan_variantes = cursor.fetchone()["count"]

        if orphan_variantes > 0:
            print(f"[ALERTA] Encontradas {orphan_variantes} variantes huerfanas")
        else:
            print("[OK] Todas las variantes tienen productos validos")

        # 4. Estadisticas finales
        cursor.execute('SELECT COUNT(*) as total FROM productos')
        total = cursor.fetchone()["total"]

        cursor.execute('SELECT MIN(id_producto) as min_id, MAX(id_producto) as max_id FROM productos')
        rango = cursor.fetchone()

        print(f"\nEstadisticas finales:")
        print(f"   Total productos: {total}")
        print(f"   Rango de IDs: {rango['min_id']} - {rango['max_id']}")

        return True

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] {e}")
        return False
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    print("Verificando y corrigiendo IDs de productos...")
    print("=" * 50)
    verificar_y_corregir_ids()
