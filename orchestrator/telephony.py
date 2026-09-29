TRUNK_FAILURE_RANGE = range(500, 600)

# sip_status_code -> (label, resumen del motivo, confianza)
SIP_CODE_RULES = {
    408: ("sin_respuesta", "no contestaron", 0.95),
    480: ("sin_respuesta", "no contestaron", 0.95),
    486: ("ocupado", "la linea comunica", 0.95),
    603: ("rechazada", "rechazo activo antes de descolgar", 0.95),
}

# amd.result -> (label, plantilla del motivo, confianza)
AMD_RESULT_RULES = {
    "machine-vm": ("buzon", "AMD detecto contestador (machine-vm, fuente {source})", 0.85),
    "machine-unavailable": ("buzon", "AMD detecto contestador (machine-unavailable, fuente {source})", 0.85),
    "machine-ivr": ("otro", "AMD detecto un IVR, fuera de catalogo (fuente {source})", 0.6),
}


def classify_from_signaling(telephony):
    """Resolve a label from SIP/AMD alone, or None if the transcript must be read."""
    sip_code = telephony["sip_status_code"]
    sip_status = telephony.get("sip_status", "")
    amd = telephony.get("amd") or {}
    amd_result = amd.get("result", "not_run")

    if sip_code in SIP_CODE_RULES:
        label, summary, confidence = SIP_CODE_RULES[sip_code]
        return _resolved(label, f"{sip_code} {sip_status}: {summary}", confidence)

    if sip_code in TRUNK_FAILURE_RANGE:
        return _resolved("otro", f"{sip_code} {sip_status}: fallo de trunk antes de conectar", 0.6)

    if amd_result in AMD_RESULT_RULES:
        label, reason_template, confidence = AMD_RESULT_RULES[amd_result]
        return _resolved(label, reason_template.format(source=amd.get("source")), confidence)

    return None


def has_confirmed_appointment(agent_outcome):
    if not agent_outcome:
        return False
    return agent_outcome.get("appointment") is not None


def _resolved(label, reason, confidence):
    return {"label": label, "reason": reason, "confidence": confidence}
