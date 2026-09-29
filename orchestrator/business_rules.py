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
