from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from orchestrator.config import WEEKDAY_NAMES


def parse_iso(value):
    return datetime.fromisoformat(value)


def to_madrid(dt, config):
    tz = ZoneInfo(config["campana"]["zona_horaria"])
    return dt.astimezone(tz)


def weekday_name(dt):
    return WEEKDAY_NAMES[dt.weekday()]


def _day_bounds(date_obj, config, tz):
    slots = config["ventana_llamadas"].get(WEEKDAY_NAMES[date_obj.weekday()]) or []
    if not slots:
        return None
    start_str, end_str = slots
    start = datetime.combine(date_obj, time.fromisoformat(start_str), tzinfo=tz)
    end = datetime.combine(date_obj, time.fromisoformat(end_str), tzinfo=tz)
    return start, end


def is_within_window(dt, config):
    bounds = _day_bounds(dt.date(), config, dt.tzinfo)
    if bounds is None:
        return False
    start, end = bounds
    return start <= dt <= end


def next_valid_slot(dt, config):
    """dt tal cual si ya cae en ventana; si no, el primer instante valido siguiente."""
    tz = dt.tzinfo
    for _ in range(8):
        bounds = _day_bounds(dt.date(), config, tz)
        if bounds is not None:
            start, end = bounds
            if dt < start:
                return start
            if dt <= end:
                return dt
        dt = datetime.combine(dt.date() + timedelta(days=1), time.min, tzinfo=tz)
    raise RuntimeError("no se encontro ninguna ventana de llamadas en una semana")


def schedule_after(occurred_at, minutes, config):
    candidate = occurred_at + timedelta(minutes=minutes)
    return next_valid_slot(candidate, config)


def schedule_after_range(occurred_at, min_minutes, max_minutes, config):
    midpoint = (min_minutes + max_minutes) / 2
    return schedule_after(occurred_at, midpoint, config)


def add_business_days(dt, n, config):
    business_days = set(config["dias_habiles"])
    current = dt
    added = 0
    while added < n:
        current = current + timedelta(days=1)
        if weekday_name(current) in business_days:
            added += 1
    return current
