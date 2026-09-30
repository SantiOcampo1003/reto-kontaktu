from datetime import timedelta

from orchestrator import dates, orders, repository


def build_action_orders(action, event, decision, occurred_at, config, connection):
    handler = ACTION_BUILDERS[action]
    built = handler(event, decision, occurred_at, config, connection)
    if decision.get("needs_review"):
        built.append(_build_review_task(event, decision, occurred_at, config))
    return built


def _confirm_visit(event, decision, occurred_at, config, connection):
    appointment = event["agent_outcome"]["appointment"]
    start = dates.to_madrid(dates.parse_iso(appointment["start_time"]), config)
    margin = config["tareas"]["confirmar_visita_margen_horas"]
    return [orders.create_task(
        event["event_id"], event["idempotency_key"], event["lead"]["contact_id"],
        "confirmar_visita_direccion", "Confirmar direccion de la visita",
        start - timedelta(hours=margin), call_id=event["telephony"]["call_id"],
    )]


def _retry_general(event, decision, occurred_at, config, connection):
    not_before = dates.schedule_after(
        occurred_at, config["reintentos"]["separacion_minima_horas"] * 60, config,
    )
    return [_schedule_call(event, decision, not_before)]


def _retry_busy(event, decision, occurred_at, config, connection):
    not_before = dates.schedule_after_range(
        occurred_at,
        config["reintentos"]["ocupado_minutos_min"],
        config["reintentos"]["ocupado_minutos_max"],
        config,
    )
    return [_schedule_call(event, decision, not_before)]


def _schedule_cortada_retry(event, decision, occurred_at, config, connection):
    not_before = dates.schedule_after_range(
        occurred_at,
        config["reintentos"]["cortada_minutos_min"],
        config["reintentos"]["cortada_horas_max"] * 60,
        config,
    )
    return [_schedule_call(event, decision, not_before, context_note=decision["reason"])]


def _schedule_callback(event, decision, occurred_at, config, connection):
    requested = dates.to_madrid(dates.parse_iso(decision["requested_time"]), config)

    if dates.is_within_window(requested, config):
        return [_schedule_call(event, decision, requested, context_note=decision["reason"])]

    not_before = dates.next_valid_slot(requested, config)
    return [
        _schedule_call(event, decision, not_before, context_note=decision["reason"]),
        orders.send_whatsapp_template(
            event["event_id"], event["idempotency_key"], event["organization_id"],
            event["lead"]["phone"], "aviso_cambio_hora",
            parameters={
                "hora_pedida": decision["requested_time"],
                "hora_confirmada": not_before.isoformat(),
            },
        ),
    ]


def _backup_channel(event, decision, occurred_at, config, connection):
    contact_id = event["lead"]["contact_id"]
    if repository.is_whatsapp_blocked(connection, contact_id):
        return []
    return [orders.send_whatsapp_template(
        event["event_id"], event["idempotency_key"], event["organization_id"],
        event["lead"]["phone"], "primer_toque_respaldo",
    )]


def _mark_dnc(event, decision, occurred_at, config, connection):
    contact_id = event["lead"]["contact_id"]
    repository.flag_do_not_contact(connection, contact_id, decision["reason"])
    return [orders.mark_do_not_contact(
        event["event_id"], event["idempotency_key"], event["lead"]["phone"],
        decision["reason"], contact_id=contact_id,
    )]


def _verify_phone_task(event, decision, occurred_at, config, connection):
    due_at = occurred_at + timedelta(days=config["tareas"]["vencimiento_por_defecto_dias"])
    return [orders.create_task(
        event["event_id"], event["idempotency_key"], event["lead"]["contact_id"],
        "verificar_telefono", "Verificar telefono: persona equivocada",
        due_at, call_id=event["telephony"]["call_id"], detail=decision["reason"],
    )]


def _send_docs_whatsapp_and_task(event, decision, occurred_at, config, connection):
    contact_id = event["lead"]["contact_id"]

    lead_due = occurred_at + timedelta(hours=config["recordatorios"]["documentacion_lead_horas"])
    order_lead, reminder_lead_id = orders.schedule_reminder(
        event["event_id"], event["idempotency_key"], contact_id, "whatsapp_lead",
        lead_due, "lead", "lead_responde", template="recordatorio_documentacion",
    )
    repository.create_reminder(connection, reminder_lead_id, contact_id, "whatsapp_lead")

    comercial_due = dates.add_business_days(
        occurred_at, config["recordatorios"]["seguimiento_comercial_dias_habiles"], config,
    )
    order_comercial, reminder_comercial_id = orders.schedule_reminder(
        event["event_id"], event["idempotency_key"], contact_id, "tarea_comercial",
        comercial_due, "comercial", "lead_responde", task_type="llamar_a_mano",
    )
    repository.create_reminder(connection, reminder_comercial_id, contact_id, "tarea_comercial")

    return [order_lead, order_comercial]


def _send_docs_email_task(event, decision, occurred_at, config, connection):
    contact_id = event["lead"]["contact_id"]
    if not repository.is_whatsapp_blocked(connection, contact_id):
        repository.block_whatsapp(connection, contact_id)
    due_at = occurred_at + timedelta(days=config["tareas"]["vencimiento_por_defecto_dias"])
    return [orders.create_task(
        event["event_id"], event["idempotency_key"], contact_id,
        "enviar_documentacion_email", "Enviar documentacion por email",
        due_at, call_id=event["telephony"]["call_id"], detail=decision["reason"],
    )]


def _review_task(event, decision, occurred_at, config, connection):
    return [_build_review_task(event, decision, occurred_at, config)]


def _none(event, decision, occurred_at, config, connection):
    return []


def _schedule_call(event, decision, not_before, context_note=None):
    return orders.schedule_call(
        event["event_id"], event["idempotency_key"], event["campaign"]["entry_id"],
        event["lead"]["phone"], not_before, decision["reason"], context_note=context_note,
    )


def _build_review_task(event, decision, occurred_at, config):
    due_at = occurred_at + timedelta(days=config["tareas"]["vencimiento_por_defecto_dias"])
    return orders.create_task(
        event["event_id"], event["idempotency_key"], event["lead"]["contact_id"],
        "revisar_llamada", "Revisar llamada", due_at,
        call_id=event["telephony"]["call_id"], detail=decision["reason"],
    )


ACTION_BUILDERS = {
    "confirm_visit": _confirm_visit,
    "retry_general": _retry_general,
    "retry_busy": _retry_busy,
    "schedule_cortada_retry": _schedule_cortada_retry,
    "schedule_callback": _schedule_callback,
    "backup_channel": _backup_channel,
    "mark_dnc": _mark_dnc,
    "verify_phone_task": _verify_phone_task,
    "send_docs_whatsapp_and_task": _send_docs_whatsapp_and_task,
    "send_docs_email_task": _send_docs_email_task,
    "review_task": _review_task,
    "none": _none,
}
