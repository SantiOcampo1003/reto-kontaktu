import json
import sys
from pathlib import Path

import jsonschema

from orchestrator import repository
from orchestrator.config import load_campaign_config
from orchestrator.graph import build_graph

PROJECT_ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = PROJECT_ROOT / "esquemas" / "evento.schema.json"


def load_event(event_path):
    with open(event_path, encoding="utf-8") as f:
        event = json.load(f)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(event, schema)
    return event


def main(argv):
    if len(argv) != 2:
        print("uso: python run.py <ruta-al-evento.json>", file=sys.stderr)
        return 2

    event_path = argv[1]
    try:
        event = load_event(event_path)
        config = load_campaign_config()
        with repository.open_connection() as connection:
            graph = build_graph(connection, config)
            graph.invoke({"event": event})
        return 0
    except Exception as exc:
        print(f"error procesando {event_path}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
