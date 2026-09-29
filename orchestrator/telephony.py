TRUNK_FAILURE_RANGE = range(500, 600)
VOICEMAIL_RESULTS = ("machine-vm", "machine-unavailable")


def classify_from_signaling(telephony):
    """Resolve a label from SIP/AMD alone, or None if the transcript must be read."""
    sip_code = telephony["sip_status_code"]
    sip_status = telephony.get("sip_status", "")
    amd = telephony.get("amd") or {}
    amd_result = amd.get("result", "not_run")

    if sip_code in (408, 480):
        return _resolved("sin_respuesta", f"{sip_code} {sip_status}: no contestaron", 0.95)

    if sip_code == 486:
        return _resolved("ocupado", f"{sip_code} {sip_status}: la linea comunica", 0.95)

    if sip_code == 603:
        return _resolved("rechazada", f"{sip_code} {sip_status}: rechazo activo antes de descolgar", 0.95)

    if sip_code in TRUNK_FAILURE_RANGE:
        return _resolved("otro", f"{sip_code} {sip_status}: fallo de trunk antes de conectar", 0.6)

    if amd_result in VOICEMAIL_RESULTS:
        return _resolved("buzon", f"AMD detecto contestador ({amd_result}, fuente {amd.get('source')})", 0.85)

    if amd_result == "machine-ivr":
        return _resolved("otro", "AMD detecto un IVR, fuera de catalogo", 0.6)

    return None


def has_confirmed_appointment(agent_outcome):
    if not agent_outcome:
        return False
    return agent_outcome.get("appointment") is not None


def _resolved(label, reason, confidence):
    return {"label": label, "reason": reason, "confidence": confidence}
