"""
Servicio de envío de correos electrónicos utilizando Brevo API
Usa datos JSON transaccionales para los templates de Brevo.
"""
import logging
import os
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from config import Config
from app.utils.moneda import formatear_cop, cop_a_usd, obtener_tasa_cop_usd

logger = logging.getLogger(__name__)


def configure_brevo():
    """Configura la instancia de API de Brevo"""
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = Config.BREVO_API_KEY
    return sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))


def send_email(to_email, subject, html_content, sender_name=None, sender_email=None):
    """
    Envía un correo con HTML directo (sin template de Brevo).
    Útil para correos simples o cuando no hay template configurado.
    """
    try:
        if not Config.BREVO_API_KEY:
            logger.warning("API Key de Brevo no configurada en .env")
            return False

        if not to_email or not subject or not html_content:
            logger.warning("Faltan parámetros obligatorios para enviar correo")
            return False

        api_instance = configure_brevo()

        sender_name = sender_name or Config.BREVO_SENDER_NAME or "Beer House"
        sender_email = sender_email or Config.BREVO_SENDER_EMAIL or "noreply@beerhouse.com"

        smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": to_email}],
            sender={"name": sender_name, "email": sender_email},
            subject=subject,
            html_content=html_content
        )

        api_instance.send_transac_email(smtp_email)
        logger.info("Correo directo enviado exitosamente")
        return True

    except ApiException:
        logger.exception("Error de API de Brevo al enviar correo directo")
        return False
    except Exception:
        logger.exception("Error al enviar correo directo")
        return False


def send_email_template(to_email, to_name, template_id, params):
    """
    Envía un correo usando un template de Brevo con datos JSON transaccionales.

    Args:
        to_email:     Email del destinatario
        to_name:      Nombre del destinatario
        template_id:  ID numérico del template en Brevo (ver dashboard → Templates)
        params:       Diccionario con las variables que usa el template
                      Ej: {"nombre_cliente": "Juan", "id_pedido": 42}

    Returns:
        bool: True si el envío fue exitoso, False en caso contrario
    """
    try:
        logger.debug("Iniciando envío de correo con template %s", template_id)

        if not Config.BREVO_API_KEY:
            logger.warning("API Key de Brevo no configurada en .env")
            return False

        api_instance = configure_brevo()

        sender_name = Config.BREVO_SENDER_NAME or "Beer House"
        sender_email = Config.BREVO_SENDER_EMAIL or "noreply@beerhouse.com"

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
    Correo de bienvenida al registrarse.
    Variables que usa el template: {{ params.nombre_cliente }}
    """
    logger.debug("send_welcome_email llamado con template_id=%s", TEMPLATE_BIENVENIDA)
    return send_email_template(
        to_email=user_email,
        to_name=user_name,
        template_id=TEMPLATE_BIENVENIDA,
        params={
            "nombre_cliente": user_name,
            "url_catalogo": f"{os.getenv('BASE_URL', 'http://127.0.0.1:5000').rstrip('/')}/productos/"
        }
    )


def send_order_confirmation_email(user_email, user_name, order_details):
    """
    Correo de confirmación de pedido.

    Variables que usa el template:
      {{ params.nombre_cliente }}
      {{ params.id_pedido }}
      {{ params.fecha_pedido }}
      {{ params.estado }}
      {{ params.direccion_entrega }}
      {{ params.metodo_pago }}
      {{ params.total }}
      {{ params.url_pedido }}
      {% for item in params.items %}
        {{ item.nombre_producto }}
        {{ item.presentacion }}
        {{ item.cantidad }}
        {{ item.subtotal }}
      {% endfor %}
    """
    logger.debug("send_order_confirmation_email con template_id=%s", TEMPLATE_CONFIRMACION)

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
        if not monto_usd:
            try:
                tasa = tasa or obtener_tasa_cop_usd()
                monto_usd = cop_a_usd(total, tasa)
            except Exception:
                monto_usd = None

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
    Correo de actualización de estado del pedido.

    Variables que usa el template:
      {{ params.nombre_cliente }}
      {{ params.id_pedido }}
      {{ params.nuevo_estado }}
      {{ params.url_pedido }}
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
    Construye los detalles del pedido y envía el correo de confirmación.
    Devuelve True si se envió correctamente o si no hubo error crítico.
    """
    try:
        from app.models.pedido import Pedido, PedidoDetalle
        from app.models.usuario import Usuario
        from app.models.producto import Producto, VarianteProducto
        from app.models.pago import Pago

        pedido = Pedido.obtener_por_id(id_pedido)
        if not pedido:
            return False

        user_id = id_usuario or pedido.get("id_usuario")
        usuario = Usuario.obtener_por_id(user_id) if user_id else None
        if not usuario or not usuario.get("email"):
            return False

        pago = Pago.obtener_por_pedido(id_pedido)

        detalles = PedidoDetalle.listar_por_pedido(id_pedido)
        direccion_completa = f"{pedido.get('linea_direccion', '')}, {pedido.get('ciudad', '')}"
        if pedido.get("departamento"):
            direccion_completa += f", {pedido['departamento']}"
        if pedido.get("dir_alias"):
            direccion_completa = f"{pedido['dir_alias']}: {direccion_completa}"

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

        return send_order_confirmation_email(
            usuario["email"],
            usuario["nombre"],
            order_details,
        )
    except Exception:
        logger.exception("Error al enviar correo de confirmación para pedido %s", id_pedido)
        return False
