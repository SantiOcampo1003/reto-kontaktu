from pathlib import Path
from typing import Optional

from openai import OpenAI
from pydantic import BaseModel

from orchestrator import dates

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "extraer_senales.md"

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


class ExtractedSignals(BaseModel):
    quiere_no_ser_contactado: bool
    es_persona_equivocada: bool
    llamada_cortada_a_mitad: bool
    visita_acordada_de_palabra: bool
    hora_visita_acordada: Optional[str]
    pide_callback: bool
    hora_callback_pedida: Optional[str]
    quiere_documentacion: bool
    rechaza_whatsapp: bool
    ya_no_busca_propiedad: bool
    resumen: str


def extract_signals(event, config, model):
    occurred_at = dates.to_madrid(dates.parse_iso(event["occurred_at"]), config)
    transcript_text = "\n".join(
        f"{turno['role']}: {turno['message']}" for turno in event["transcript"]
    )

    prompt = (
        PROMPT_PATH.read_text(encoding="utf-8")
        .replace("<<DIA_SEMANA>>", dates.weekday_name(occurred_at))
        .replace("<<FECHA_REFERENCIA>>", occurred_at.isoformat())
        .replace("<<TRANSCRIPT>>", transcript_text)
    )

    client = _get_client()
    response = client.beta.chat.completions.parse(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format=ExtractedSignals,
    )
    return response.choices[0].message.parsed
