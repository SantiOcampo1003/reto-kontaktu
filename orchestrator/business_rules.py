from orchestrator import telephony

# etiqueta -> status de cola que lleva cerrar_llamada (tabla de casos.md, transcrita literal)
STATUS_BY_LABEL = {
    "visita_reservada": "successful",
    "documentacion_enviada": "completed",
    "documentacion_pendiente": "completed",
    "callback": "callback_requested",
    "sin_respuesta": "no_answer",
    "ocupado": "no_answer",
    "buzon": "no_answer",
    "cortada": "needs_review",
    "visita_sin_confirmar": "needs_review",
    "otro": "needs_review",
    "persona_equivocada": "failed",
    "no_contactar": "dnc",
    "rechazada": "refused",
    "descartado": "skipped",
}


class NeedsTranscript(Exception):
    """La senalizacion no basta: hace falta leer la conversacion (nodo LLM, pendiente de construir)."""


def classify_call(event, attempts_so_far, max_attempts):
    if telephony.has_confirmed_appointment(event.get("agent_outcome")):
        return {
            "label": "visita_reservada",
            "reason": "el agente creo la cita durante la llamada",
            "confidence": 0.99,
            "action": "confirm_visit",
        }

    signaling = telephony.classify_from_signaling(event["telephony"])
    if signaling is None:
        raise NeedsTranscript("la senalizacion no basta, hace falta leer el transcript")

    label = signaling["label"]

    if label == "ocupado":
        return {**signaling, "action": "retry_busy"}

    if label == "rechazada":
        return {**signaling, "action": "backup_channel"}

    if label == "buzon":
        action = "retry_general" if attempts_so_far + 1 < max_attempts else "backup_channel"
        return {**signaling, "action": action}

    if label == "otro":
        return {**signaling, "action": "review_task"}

    return {**signaling, "action": "retry_general"}  # sin_respuesta


def classify_from_signals(signals, dropped_calls_so_far):
    """Prioridad fija sobre los hechos que extrajo el LLM (nunca al reves)."""

    if signals.quiere_no_ser_contactado:
        return {
            "label": "no_contactar",
            "reason": signals.resumen,
            "confidence": 0.95,
            "action": "mark_dnc",
        }

    if signals.es_persona_equivocada:
        return {
            "label": "persona_equivocada",
            "reason": signals.resumen,
            "confidence": 0.9,
            "action": "verify_phone_task",
        }

    if signals.ya_no_busca_propiedad:
        return {
            "label": "descartado",
            "reason": signals.resumen,
            "confidence": 0.9,
            "action": "none",
        }

    # visita_acordada_de_palabra se comprueba ANTES que llamada_cortada_a_mitad a proposito:
    # lo que distingue el caso 8 del 7 es si se acordo visita, no como se corto la llamada.
    if signals.visita_acordada_de_palabra:
        return {
            "label": "visita_sin_confirmar",
            "reason": signals.resumen,
            "confidence": 0.85,
            "action": "schedule_cortada_retry",
            "needs_review": dropped_calls_so_far >= 1,
        }

    if signals.llamada_cortada_a_mitad:
        return {
            "label": "cortada",
            "reason": signals.resumen,
            "confidence": 0.85,
            "action": "schedule_cortada_retry",
            "needs_review": dropped_calls_so_far >= 1,
        }

    if signals.pide_callback:
        return {
            "label": "callback",
            "reason": signals.resumen,
            "confidence": 0.92,
            "action": "schedule_callback",
            "requested_time": signals.hora_callback_pedida,
        }

    if signals.quiere_documentacion:
        if signals.rechaza_whatsapp:
            return {
                "label": "documentacion_pendiente",
                "reason": signals.resumen,
                "confidence": 0.9,
                "action": "send_docs_email_task",
            }
        return {
            "label": "documentacion_enviada",
            "reason": signals.resumen,
            "confidence": 0.9,
            "action": "send_docs_whatsapp_and_task",
        }

    return {
        "label": "otro",
        "reason": signals.resumen,
        "confidence": 0.5,
        "action": "review_task",
    }
