"""
Servicio de envío de correos electrónicos transaccionales utilizando Brevo API (Sendinblue).

Soporta tanto correos HTML directos como plantillas alojadas en Brevo alimentadas
mediante parámetros JSON (`params`). Todos los errores de red o API se capturan y
registran en log para que un fallo de correo no aborte operaciones críticas (como
registro de usuario o confirmación de compra).
"""
import logging
import os
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from config import Config
from app.utils.moneda import formatear_cop, cop_a_usd, obtener_tasa_cop_usd

# Logger del módulo para trazabilidad de envíos y errores de Brevo
logger = logging.getLogger(__name__)


def configure_brevo():
    """
    Configura y devuelve una instancia del cliente transaccional de Brevo.

    Lee la clave `Config.BREVO_API_KEY` y construye el objeto `TransactionalEmailsApi`
    necesario para despachar correos mediante la API v3 de Brevo.

    Returns:
        sib_api_v3_sdk.TransactionalEmailsApi: Cliente listo para enviar correos.
    """
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = Config.BREVO_API_KEY
    return sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))


def send_email(to_email, subject, html_content, sender_name=None, sender_email=None):
    """
    Envía un correo electrónico con contenido HTML directo (sin plantilla de Brevo).

    Útil para notificaciones simples o escenarios donde no se requiere un template
    previamente diseñado en el panel de Brevo.

    Args:
        to_email (str): Dirección de correo electrónico del destinatario.
        subject (str): Asunto del correo.
        html_content (str): Cuerpo del mensaje en formato HTML.
        sender_name (str | None): Nombre visible del remitente (opcional; usa `Config.BREVO_SENDER_NAME`).
        sender_email (str | None): Correo del remitente (opcional; usa `Config.BREVO_SENDER_EMAIL`).

    Returns:
        bool: `True` si Brevo aceptó el envío, `False` si faltan parámetros/credenciales o hubo error.
    """
    try:
        # Validamos que exista la API key antes de intentar conectar con Brevo
        if not Config.BREVO_API_KEY:
            logger.warning("API Key de Brevo no configurada en .env")
            return False

        # Verificamos los campos mínimos requeridos por el protocolo de envío
        if not to_email or not subject or not html_content:
            logger.warning("Faltan parámetros obligatorios para enviar correo")
            return False

        api_instance = configure_brevo()

        # Aplicamos valores por defecto de remitente si no fueron provistos
        sender_name = sender_name or Config.BREVO_SENDER_NAME or "Beer House"
        sender_email = sender_email or Config.BREVO_SENDER_EMAIL or "noreply@beerhouse.com"

        # Construimos el payload requerido por el SDK de Brevo
        smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": to_email}],
            sender={"name": sender_name, "email": sender_email},
            subject=subject,
            html_content=html_content
        )

        # Ejecutamos la petición HTTP POST hacia la API transaccional de Brevo
        api_instance.send_transac_email(smtp_email)
        logger.info("Correo directo enviado exitosamente")
        return True

    except ApiException:
        # Error HTTP devuelto por la API de Brevo (ej. 401, 400, límite excedido)
        logger.exception("Error de API de Brevo al enviar correo directo")
        return False
    except Exception:
        logger.exception("Error al enviar correo directo")
        return False


def send_email_template(to_email, to_name, template_id, params):
    """
    Envía un correo usando un template de Brevo con datos JSON transaccionales.

    Args:
        to_email (str): Email del destinatario.
        to_name (str): Nombre del destinatario.
        template_id (int): ID numérico del template en Brevo (ver dashboard → Templates).
        params (dict): Diccionario con las variables dinámicas que usa el template.
            Ej: `{"nombre_cliente": "Juan", "id_pedido": 42}`.

    Returns:
        bool: `True` si el envío fue exitoso, `False` en caso contrario.
    """
    try:
        logger.debug("Iniciando envío de correo con template %s", template_id)

        if not Config.BREVO_API_KEY:
            logger.warning("API Key de Brevo no configurada en .env")
            return False

        api_instance = configure_brevo()

        # Remitente configurado en el entorno o respaldo por defecto
        sender_name = Config.BREVO_SENDER_NAME or "Beer House"
        sender_email = Config.BREVO_SENDER_EMAIL or "noreply@beerhouse.com"

        # Brevo renderiza la plantilla remota interpolando el diccionario `params`
        smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": to_email, "name": to_name}],
            sender={"name": sender_name, "email": sender_email},
            template_id=template_id,
            params=params          # <-- aquí van los datos JSON transaccionales
        )

        api_instance.send_transac_email(smtp_email)
        logger.info("Correo (template %s) enviado exitosamente", template_id)
        return True

    except ApiException:
        logger.exception("Error de API de Brevo al enviar template %s", template_id)
        return False
    except Exception:
        logger.exception("Error al enviar correo con template %s", template_id)
        return False


# ---------------------------------------------------------------------------
# TEMPLATE IDs — copia el ID desde Brevo dashboard → Emails → Templates
# ---------------------------------------------------------------------------
TEMPLATE_BIENVENIDA    = 5   # <- cambia por el ID real de tu template
TEMPLATE_CONFIRMACION = 4      # <- cambia por el ID real de tu template
TEMPLATE_ESTADO_PEDIDO    = 6   # <- cambia por el ID real de tu template


def send_welcome_email(user_email, user_name):
    """
    Envía el correo de bienvenida al registrarse un nuevo cliente.

    Variables que usa el template en Brevo:
      - `{{ params.nombre_cliente }}`
      - `{{ params.url_catalogo }}`

    Args:
        user_email (str): Correo del usuario recién registrado.
        user_name (str): Nombre del usuario.

    Returns:
        bool: `True` si el correo se envió correctamente, `False` en caso contrario.
    """
    logger.debug("send_welcome_email llamado con template_id=%s", TEMPLATE_BIENVENIDA)
    return send_email_template(
        to_email=user_email,
        to_name=user_name,
        template_id=TEMPLATE_BIENVENIDA,
        params={
            "nombre_cliente": user_name,
            # Construimos la URL absoluta al catálogo usando BASE_URL sin barra final duplicada
            "url_catalogo": f"{os.getenv('BASE_URL', 'http://127.0.0.1:5000').rstrip('/')}/productos/"
        }
    )


def send_order_confirmation_email(user_email, user_name, order_details):
    """
    Envía el correo de confirmación de pedido con el desglose de productos y totales.

    Variables que usa el template en Brevo:
      `{{ params.nombre_cliente }}`, `{{ params.id_pedido }}`,
      `{{ params.fecha_pedido }}`, `{{ params.estado }}`,
      `{{ params.direccion_entrega }}`, `{{ params.metodo_pago }}`,
      `{{ params.total }}`, `{{ params.url_pedido }}` y la lista `params.items`.

    Args:
        user_email (str): Correo electrónico del cliente.
        user_name (str): Nombre completo del cliente.
        order_details (dict): Diccionario con los datos del pedido e items.

    Returns:
        bool: `True` si el envío fue exitoso, `False` en caso contrario.
    """
    logger.debug("send_order_confirmation_email con template_id=%s", TEMPLATE_CONFIRMACION)

    # Normalizamos cada ítem del pedido formateando su subtotal en pesos colombianos (COP)
    items = []
    for item in order_details.get("items", []):
        precio = item.get("precio_unitario", item.get("precio", 0))
        cantidad = item.get("cantidad", 0)
        subtotal = item.get("subtotal", precio * cantidad)
        items.append({
            "nombre_producto": item.get("nombre_producto", ""),
            "presentacion":    item.get("presentacion", ""),
            "cantidad":        cantidad,
            "subtotal":        formatear_cop(subtotal)
        })

    total = order_details.get("total", 0)
    id_pedido = order_details.get("id_pedido", "")
    metodo_pago = order_details.get("metodo_pago", "")

    # Si el método de pago es PayPal (o se especifica monto_usd/tasa), mostrar también el monto en USD
    metodo_pago_texto = metodo_pago
    if "paypal" in str(metodo_pago).lower() or order_details.get("monto_usd"):
        monto_usd = order_details.get("monto_usd")
        tasa = order_details.get("tasa_cop_usd")
        # Si no viene precalculado el monto en USD, intentamos calcularlo con la tasa configurada
        if not monto_usd:
            try:
                tasa = tasa or obtener_tasa_cop_usd()
                monto_usd = cop_a_usd(total, tasa)
            except Exception:
                monto_usd = None

        # Enriquecemos el texto del método de pago con el valor cobrado en USD y la tasa aplicada
        if monto_usd:
            tasa_str = f" (tasa: 1 USD = {formatear_cop(tasa)} COP)" if tasa else ""
            metodo_pago_texto = f"{metodo_pago} — Cobrado por PayPal: US${'%.2f' % monto_usd}{tasa_str}"

    return send_email_template(
        to_email=user_email,
        to_name=user_name,
        template_id=TEMPLATE_CONFIRMACION,
        params={
            "nombre_cliente":   user_name,
            "id_pedido":        id_pedido,
            "fecha_pedido":     str(order_details.get("fecha_creacion", "")),
            "estado":           order_details.get("nombre_estado", "Pendiente"),
            "direccion_entrega": order_details.get("direccion_entrega", ""),
            "metodo_pago":      metodo_pago_texto,
            "total":            f"{formatear_cop(total)} COP",
            "items":            items,
            "url_pedido":       f"{os.getenv('BASE_URL', 'http://127.0.0.1:5000').rstrip('/')}/carrito/confirmacion/{id_pedido}"
        }
    )


def send_order_status_update_email(user_email, user_name, order_id, new_status):
    """
    Envía un correo notificando el cambio de estado de un pedido al cliente.

    Variables que usa el template en Brevo:
      `{{ params.nombre_cliente }}`, `{{ params.id_pedido }}`,
      `{{ params.nuevo_estado }}`, `{{ params.url_pedido }}`.

    Args:
        user_email (str): Correo del cliente.
        user_name (str): Nombre del cliente.
        order_id (int | str): Identificador del pedido actualizado.
        new_status (str): Nombre del nuevo estado (ej. "Confirmado", "Enviado").

    Returns:
        bool: `True` si se envió correctamente, `False` en caso contrario.
    """
    return send_email_template(
        to_email=user_email,
        to_name=user_name,
        template_id=TEMPLATE_ESTADO_PEDIDO,
        params={
            "nombre_cliente": user_name,
            "id_pedido":      order_id,
            "nuevo_estado":   new_status,
            "url_pedido":     f"{os.getenv('BASE_URL', 'http://127.0.0.1:5000').rstrip('/')}/carrito/confirmacion/{order_id}"
        }
    )


def enviar_confirmacion_pedido_por_id(id_pedido, id_usuario=None):
    """
    Consulta la base de datos para armar los detalles de un pedido y envía su confirmación.

    Reúne información del pedido, usuario, pago (tasa y USD si aplica), dirección de
    entrega y líneas de detalle con producto/presentación, delegando finalmente en
    `send_order_confirmation_email`.

    Args:
        id_pedido (int): Identificador del pedido a confirmar por correo.
        id_usuario (int | None): ID del usuario destinatario (opcional; si es `None`,
            se toma `pedido["id_usuario"]`).

    Returns:
        bool: `True` si el correo se envió correctamente, `False` si faltan datos o falla el envío.
    """
    try:
        # Importaciones locales para evitar dependencias circulares al cargar modelos
        from app.models.pedido import Pedido, PedidoDetalle
        from app.models.usuario import Usuario
        from app.models.producto import Producto, VarianteProducto
        from app.models.pago import Pago

        # 1. Obtenemos la cabecera del pedido
        pedido = Pedido.obtener_por_id(id_pedido)
        if not pedido:
            return False

        # 2. Resolvemos el usuario destinatario y validamos que tenga email
        user_id = id_usuario or pedido.get("id_usuario")
        usuario = Usuario.obtener_por_id(user_id) if user_id else None
        if not usuario or not usuario.get("email"):
            return False

        # 3. Consultamos el registro de pago (para obtener monto_usd/tasa si fue PayPal)
        pago = Pago.obtener_por_pedido(id_pedido)

        # 4. Obtenemos el detalle de ítems y formateamos la dirección completa en una sola cadena
        detalles = PedidoDetalle.listar_por_pedido(id_pedido)
        direccion_completa = f"{pedido.get('linea_direccion', '')}, {pedido.get('ciudad', '')}"
        if pedido.get("departamento"):
            direccion_completa += f", {pedido['departamento']}"
        if pedido.get("dir_alias"):
            direccion_completa = f"{pedido['dir_alias']}: {direccion_completa}"

        # 5. Construimos la estructura base esperada por `send_order_confirmation_email`
        order_details = {
            "id_pedido": pedido["id_pedido"],
            "fecha_creacion": pedido.get("fecha_pedido"),
            "nombre_estado": pedido.get("nombre_estado", "Pendiente"),
            "total": pedido.get("total", 0),
            "direccion_entrega": direccion_completa,
            "metodo_pago": pedido.get("tipo_pago", "No especificado"),
            "monto_usd": pago.get("monto_usd") if pago else None,
            "tasa_cop_usd": pago.get("tasa_cop_usd") if pago else None,
            "items": [],
        }

        # 6. Enriquecemos cada línea del pedido con el nombre del producto y su presentación
        for detalle in detalles:
            variante = VarianteProducto.obtener_por_id(detalle["id_variante"])
            producto = Producto.obtener_por_id(variante["id_producto"]) if variante else None
            item_data = {
                "nombre_producto": producto["nombre_producto"] if producto else "",
                "presentacion": variante["presentacion"] if variante else "",
                "cantidad": detalle["cantidad"],
                "precio_unitario": detalle["precio_unitario"],
                "subtotal": detalle["subtotal"],
            }
            order_details["items"].append(item_data)

        # 7. Despachamos el correo de confirmación usando el template de Brevo
        return send_order_confirmation_email(
            usuario["email"],
            usuario["nombre"],
            order_details,
        )
    except Exception:
        logger.exception("Error al enviar correo de confirmación para pedido %s", id_pedido)
        return False
