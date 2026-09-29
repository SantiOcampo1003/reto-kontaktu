import functools
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "campana.yaml"

WEEKDAY_NAMES = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


@functools.lru_cache
def load_campaign_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)
