"""
Servicio de envío de correos electrónicos utilizando Brevo API
Usa datos JSON transaccionales para los templates de Brevo.
"""
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from config import Config


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
            print("Error: API Key de Brevo no configurada en .env")
            return False

        if not to_email or not subject or not html_content:
            print("Error: Faltan parámetros obligatorios para enviar correo")
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
        print(f"Correo enviado exitosamente a {to_email}")
        return True

    except ApiException as e:
        print(f"Error de API de Brevo: {e}")
        if e.body:
            print(f"Detalles del error: {e.body}")
        return False
    except Exception as e:
        print(f"Error al enviar correo: {e}")
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
        print(f"DEBUG: Iniciando envío de correo con template {template_id}")
        print(f"DEBUG: Para: {to_email} ({to_name})")
        print(f"DEBUG: Parámetros: {params}")
        
        if not Config.BREVO_API_KEY:
            print("Error: API Key de Brevo no configurada en .env")
            return False

        api_instance = configure_brevo()

        sender_name = Config.BREVO_SENDER_NAME or "Beer House"
        sender_email = Config.BREVO_SENDER_EMAIL or "noreply@beerhouse.com"
        
        print(f"DEBUG: Remitente: {sender_name} <{sender_email}>")

        smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": to_email, "name": to_name}],
            sender={"name": sender_name, "email": sender_email},
            template_id=template_id,
            params=params          # <-- aquí van los datos JSON transaccionales
        )

        result = api_instance.send_transac_email(smtp_email)
        print(f"Correo (template {template_id}) enviado exitosamente a {to_email}")
        print(f"DEBUG: Resultado de Brevo: {result}")
        return True

    except ApiException as e:
        print(f"Error de API de Brevo: {e}")
        if e.body:
            print(f"Detalles del error: {e.body}")
        return False
    except Exception as e:
        print(f"Error al enviar correo: {e}")
        import traceback
        traceback.print_exc()
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
    print(f"DEBUG: send_welcome_email llamado con template_id={TEMPLATE_BIENVENIDA}")
    return send_email_template(
        to_email=user_email,
        to_name=user_name,
        template_id=TEMPLATE_BIENVENIDA,
        params={
            "nombre_cliente": user_name,
            "url_catalogo": "http://127.0.0.1:5000/productos/"
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
    # Preparar items con subtotal ya formateado
    print(f"DEBUG: send_order_confirmation_email - TEMPLATE_CONFIRMACION = {TEMPLATE_CONFIRMACION}")
    
    items = []
    for item in order_details.get("items", []):
        precio = item.get("precio_unitario", item.get("precio", 0))
        cantidad = item.get("cantidad", 0)
        items.append({
            "nombre_producto": item.get("nombre_producto", ""),
            "presentacion":    item.get("presentacion", ""),
            "cantidad":        cantidad,
            "subtotal":        f"${precio * cantidad:,.0f}"
        })

    total = order_details.get("total", 0)
    id_pedido = order_details.get("id_pedido", "")

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
            "metodo_pago":      order_details.get("metodo_pago", ""),
            "total":            f"${total:,.0f}",
            "items":            items,
            "url_pedido":       f"http://127.0.0.1:5000/carrito/confirmacion/{id_pedido}"
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
            "url_pedido":     f"http://127.0.0.1:5000/carrito/confirmacion/{order_id}"
        }
    )
