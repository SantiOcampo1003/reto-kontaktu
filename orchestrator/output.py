import json
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "salida"
DECISIONS_PATH = OUTPUT_DIR / "decisiones.jsonl"
ORDERS_PATH = OUTPUT_DIR / "ordenes.jsonl"


def append_decision(decision):
    _append_line(DECISIONS_PATH, decision)


def append_orders(built_orders):
    for order in built_orders:
        _append_line(ORDERS_PATH, order)


def _append_line(path, payload):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
