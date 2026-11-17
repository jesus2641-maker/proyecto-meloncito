"""
Modelo de Carrito y Gestión del carrito de compras.

Este módulo maneja la lógica de persistencia del carrito de compras en MySQL,
incluyendo la creación/recuperación del carrito por usuario, la gestión de
items del carrito, cantidades y la consulta de ofertas vigentes asociadas.
"""

# Función utilitaria que obtiene una conexión activa del pool/configuración de MySQL
from app.utils.db import get_connection


class Carrito:
    """
    Modelo que representa la cabecera del carrito de compras de un usuario
    (tabla `carritos`).
    """

    @staticmethod
    def obtener_o_crear(id_usuario):
        """
        Obtiene el carrito de un usuario o crea uno nuevo si no existe.

        Args:
            id_usuario (int): ID del usuario propietario del carrito.

        Returns:
            dict: Diccionario con información del carrito (`id_carrito`, `id_usuario`, etc.).
        """
        # Abrir conexión y cursor en modo diccionario para acceder por nombre de columna
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        # Buscar si el usuario ya tiene un carrito registrado
        cursor.execute("SELECT * FROM carritos WHERE id_usuario = %s", (id_usuario,))
        carrito = cursor.fetchone()

        if not carrito:
            # Crear nuevo carrito si el usuario no tiene uno
            cursor.execute("INSERT INTO carritos (id_usuario) VALUES (%s)", (id_usuario,))
            # Confirmar la inserción en la base de datos
            conn.commit()
            # Recuperar el ID autogenerado por AUTO_INCREMENT
            id_carrito = cursor.lastrowid
            # Construir el diccionario de retorno con la misma estructura esperada
            carrito = {"id_carrito": id_carrito, "id_usuario": id_usuario}

        # Liberar recursos de base de datos
        cursor.close()
        conn.close()
        return carrito

    @staticmethod
    def obtener_items(id_carrito):
        """
        Lista todos los ítems de un carrito junto con los datos del producto,
        su variante y cualquier oferta activa y vigente en la fecha actual.

        Args:
            id_carrito (int): ID del carrito a consultar.

        Returns:
            list[dict]: Lista de diccionarios con cada ítem, su variante, producto y oferta.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        # Consultar ítems uniendo variantes, productos y ofertas vigentes (por variante o producto)
        cursor.execute("""
            SELECT ci.id_item, ci.cantidad, v.id_variante, v.presentacion,
                   v.precio, p.nombre_producto, p.id_producto,
                   o.id_oferta, o.precio_oferta, o.descuento_porcentaje,
                   o.titulo as oferta_titulo
            FROM carrito_items ci
            JOIN variantes_producto v ON ci.id_variante = v.id_variante
            JOIN productos p ON v.id_producto = p.id_producto
            LEFT JOIN ofertas o ON (o.id_variante = v.id_variante OR o.id_producto = p.id_producto)
                AND o.activa = TRUE
                AND (o.fecha_inicio IS NULL OR o.fecha_inicio <= NOW())
                AND (o.fecha_fin IS NULL OR o.fecha_fin > NOW())
            WHERE ci.id_carrito = %s
        """, (id_carrito,))
        # Obtener todas las filas coincidentes
        items = cursor.fetchall()
        cursor.close()
        conn.close()
        return items

    @staticmethod
    def vaciar(id_carrito):
        """
        Elimina todos los items del carrito tras confirmar un pedido.

        Args:
            id_carrito (int): ID del carrito que se desea vaciar.
        """
        conn = get_connection()
        cursor = conn.cursor()
        # Borrar todos los registros hijos de `carrito_items` pertenecientes al carrito
        cursor.execute("DELETE FROM carrito_items WHERE id_carrito = %s", (id_carrito,))
        conn.commit()
        cursor.close()
        conn.close()


class CarritoItem:
    """
    Modelo que representa las líneas individuales de productos dentro de un
    carrito de compras (tabla `carrito_items`).
    """

    @staticmethod
    def obtener_cantidad(id_carrito, id_variante):
        """
        Obtiene la cantidad total acumulada de una variante específica dentro de un carrito.

        Args:
            id_carrito (int): ID del carrito.
            id_variante (int): ID de la variante de producto.

        Returns:
            int: Cantidad total de unidades de esa variante en el carrito (0 si no existe).
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        # COALESCE garantiza devolver 0 cuando no existen filas coincidentes
        cursor.execute(
            """SELECT COALESCE(SUM(cantidad), 0) AS total
               FROM carrito_items
               WHERE id_carrito = %s AND id_variante = %s""",
            (id_carrito, id_variante),
        )
        fila = cursor.fetchone()
        cursor.close()
        conn.close()
        # Convertir a entero de Python de forma segura
        return int(fila["total"]) if fila else 0

    @staticmethod
    def agregar(id_carrito, id_variante, cantidad=1):
        """
        Agrega una variante al carrito o incrementa su cantidad si ya existe.

        Utiliza `ON DUPLICATE KEY UPDATE` aprovechando la clave única
        `(id_carrito, id_variante)` para evitar duplicados.

        Args:
            id_carrito (int): ID del carrito destino.
            id_variante (int): ID de la variante de producto a agregar.
            cantidad (int, optional): Número de unidades a sumar. Por defecto 1.
        """
        conn = get_connection()
        cursor = conn.cursor()
        # Insertar nueva fila o sumar cantidad si la combinación carrito-variante ya existe
        cursor.execute("""
            INSERT INTO carrito_items (id_carrito, id_variante, cantidad)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE cantidad = cantidad + %s
        """, (id_carrito, id_variante, cantidad, cantidad))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def eliminar(id_item, id_carrito=None):
        """
        Elimina un ítem específico del carrito.

        Args:
            id_item (int): ID del ítem en `carrito_items`.
            id_carrito (int, optional): Si se proporciona, restringe el borrado
                al carrito indicado como medida de seguridad/propiedad.
        """
        conn = get_connection()
        cursor = conn.cursor()
        if id_carrito is not None:
            # Validar pertenencia al carrito del usuario al eliminar
            cursor.execute("DELETE FROM carrito_items WHERE id_item = %s AND id_carrito = %s", (id_item, id_carrito))
        else:
            # Eliminación directa por identificador de ítem
            cursor.execute("DELETE FROM carrito_items WHERE id_item = %s", (id_item,))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def obtener_por_id(id_item):
        """
        Obtiene un item específico del carrito con detalles de variante, stock,
        estado del producto y oferta vigente.

        Args:
            id_item (int): ID del ítem a consultar.

        Returns:
            dict | None: Diccionario con los datos del ítem o None si no existe.
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        # Unir con variantes, productos y ofertas vigentes para validar stock y precios
        cursor.execute("""
            SELECT ci.id_item, ci.id_carrito, ci.id_variante, ci.cantidad,
                   v.presentacion, v.precio, v.stock,
                   p.nombre_producto, p.activo, p.id_producto,
                   o.id_oferta, o.precio_oferta, o.descuento_porcentaje
            FROM carrito_items ci
            JOIN variantes_producto v ON ci.id_variante = v.id_variante
            JOIN productos p ON v.id_producto = p.id_producto
            LEFT JOIN ofertas o ON (o.id_variante = v.id_variante OR o.id_producto = p.id_producto)
                AND o.activa = TRUE
                AND (o.fecha_inicio IS NULL OR o.fecha_inicio <= NOW())
                AND (o.fecha_fin IS NULL OR o.fecha_fin > NOW())
            WHERE ci.id_item = %s
        """, (id_item,))
        item = cursor.fetchone()
        cursor.close()
        conn.close()
        return item

    @staticmethod
    def actualizar_cantidad(id_item, nueva_cantidad, id_carrito=None):
        """
        Actualiza la cantidad de un item en el carrito.

        Args:
            id_item (int): ID del ítem a modificar.
            nueva_cantidad (int): Nueva cantidad de unidades deseada.
            id_carrito (int, optional): ID del carrito para verificar propiedad.
        """
        conn = get_connection()
        cursor = conn.cursor()
        if id_carrito is not None:
            # Actualizar asegurando que el ítem pertenece al carrito especificado
            cursor.execute(
                "UPDATE carrito_items SET cantidad = %s WHERE id_item = %s AND id_carrito = %s",
                (nueva_cantidad, id_item, id_carrito)
            )
        else:
            # Actualizar directamente por id_item
            cursor.execute(
                "UPDATE carrito_items SET cantidad = %s WHERE id_item = %s",
                (nueva_cantidad, id_item)
            )
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def vaciar_por_carrito(id_carrito):
        """
        Elimina todos los ítems asociados a un `id_carrito`.

        Args:
            id_carrito (int): ID del carrito a limpiar.
        """
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM carrito_items WHERE id_carrito = %s", (id_carrito,))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def contar_items(id_usuario):
        """
        Cuenta el total de unidades en el carrito de un usuario.

        Args:
            id_usuario (int): ID del usuario.

        Returns:
            int: Suma de las cantidades de todos los ítems en el carrito (0 si está vacío).
        """
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        # Sumar las cantidades de todas las líneas del carrito del usuario
        cursor.execute("""
            SELECT COALESCE(SUM(ci.cantidad), 0) AS total
            FROM carrito_items ci
            JOIN carritos c ON ci.id_carrito = c.id_carrito
            WHERE c.id_usuario = %s
        """, (id_usuario,))
        fila = cursor.fetchone()
        cursor.close()
        conn.close()
        return int(fila["total"]) if fila else 0

