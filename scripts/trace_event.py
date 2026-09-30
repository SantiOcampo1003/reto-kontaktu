"""Herramienta de aprendizaje/depuracion: NO es parte del pipeline de produccion.

Ejecuta el grafo sobre un evento y va imprimiendo, nodo a nodo, que se ejecuto
y que añadio al estado. Uso:

    python3 scripts/trace_event.py eventos/02-call-ended-tomas.json
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from orchestrator import repository
from orchestrator.config import load_campaign_config
from orchestrator.graph import build_graph

load_dotenv()

NODE_EXPLANATIONS = {
    "check_organization": "verifica que el evento sea de nuestra organizacion (R6)",
    "reject_organization": "es de otra organizacion: se rechaza, cero ordenes",
    "check_idempotency": "busca si este idempotency_key ya se proceso antes (R5)",
    "handle_replay": "es una reentrega: repite la etiqueta original, cero ordenes nuevas",
    "handle_message": "es un whatsapp entrante: cancela los recordatorios pendientes (R7)",
    "resolve_call": "es una llamada nueva: clasifica por telefonia/cita y arma las ordenes",
    "finalize": "persiste en SQLite y escribe decisiones.jsonl / ordenes.jsonl",
}


def main(event_path):
    with open(event_path, encoding="utf-8") as f:
        event = json.load(f)
    config = load_campaign_config()

    model = os.environ["MODELO"]
    with repository.open_connection() as connection:
        graph = build_graph(connection, config, model)
        print(f"--- procesando {event_path} ---")
        for step in graph.stream({"event": event}):
            for node_name, changes in step.items():
                explanation = NODE_EXPLANATIONS.get(node_name, "")
                print(f"\n[{node_name}]  {explanation}")
                for key, value in (changes or {}).items():
                    print(f"    {key} = {value!r}")


if __name__ == "__main__":
    main(sys.argv[1])
