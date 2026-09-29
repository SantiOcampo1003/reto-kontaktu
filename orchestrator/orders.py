import hashlib


def _short_hash(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def make_order_id(idempotency_key):
    return f"ord_{_short_hash(idempotency_key)}"


def make_reminder_id(idempotency_key):
    return f"rem_{_short_hash(idempotency_key)}"


def build_order(event_id, operation, idempotency_key, body):
    return {
        "orden_id": make_order_id(idempotency_key),
        "event_id": event_id,
        "operacion": operation,
        "idempotency_key": idempotency_key,
        "cuerpo": body,
    }


def close_call(event_id, event_idempotency_key, entry_id, status, label, reason, confidence, duration_seconds):
    idempotency_key = f"{event_idempotency_key}:cerrar_llamada"
    body = {
        "entry_id": entry_id,
        "status": status,
        "etiqueta": label,
        "motivo": reason,
        "confianza": confidence,
        "duration_seconds": duration_seconds,
    }
    return build_order(event_id, "cerrar_llamada", idempotency_key, body)


def schedule_call(event_id, event_idempotency_key, entry_id, phone, not_before, reason, context_note=None):
    idempotency_key = f"{event_idempotency_key}:programar_llamada"
    body = {
        "entry_id": entry_id,
        "telefono": phone,
        "no_antes_de": not_before.isoformat(),
        "motivo": reason,
    }
    if context_note is not None:
        body["nota_contexto"] = context_note
    return build_order(event_id, "programar_llamada", idempotency_key, body)


def send_whatsapp_template(event_id, event_idempotency_key, organization_id, phone, template, parameters=None):
    idempotency_key = f"{event_idempotency_key}:enviar_plantilla_whatsapp"
    body = {
        "organization_id": organization_id,
        "telefono": phone,
        "plantilla": template,
    }
    if parameters is not None:
        body["parametros"] = parameters
    return build_order(event_id, "enviar_plantilla_whatsapp", idempotency_key, body)


def schedule_reminder(event_id, event_idempotency_key, contact_id, channel, when, discriminator, cancel_if, template=None, task_type=None):
    idempotency_key = f"{event_idempotency_key}:programar_recordatorio:{discriminator}"
    reminder_id = make_reminder_id(idempotency_key)
    body = {
        "contact_id": contact_id,
        "canal": channel,
        "cuando": when.isoformat(),
        "cancelar_si": cancel_if,
    }
    if template is not None:
        body["plantilla"] = template
    if task_type is not None:
        body["tipo_tarea"] = task_type
    order = build_order(event_id, "programar_recordatorio", idempotency_key, body)
    return order, reminder_id


def cancel_reminder(event_id, event_idempotency_key, reminder_id, reason):
    idempotency_key = f"{event_idempotency_key}:cancelar_recordatorio:{reminder_id}"
    body = {"reminder_id": reminder_id, "motivo": reason}
    return build_order(event_id, "cancelar_recordatorio", idempotency_key, body)


def create_task(event_id, event_idempotency_key, contact_id, task_type, title, due_at, call_id=None, detail=None, assigned_to="comercial_asignado"):
    idempotency_key = f"{event_idempotency_key}:crear_tarea:{task_type}"
    body = {
        "contact_id": contact_id,
        "call_id": call_id,
        "tipo": task_type,
        "titulo": title,
        "vence_el": due_at.isoformat(),
        "asignada_a": assigned_to,
    }
    if detail is not None:
        body["detalle"] = detail
    return build_order(event_id, "crear_tarea", idempotency_key, body)


def mark_do_not_contact(event_id, event_idempotency_key, phone, reason, contact_id=None, channel="todos", origin="voice_agent"):
    idempotency_key = f"{event_idempotency_key}:marcar_no_contactar"
    body = {
        "telefono": phone,
        "contact_id": contact_id,
        "canal": channel,
        "motivo": reason,
        "origen": origin,
    }
    return build_order(event_id, "marcar_no_contactar", idempotency_key, body)
