import math
from datetime import datetime, timezone


def format_db_time_ms(value_ms: float) -> str:
    value = float(value_ms)
    if not math.isfinite(value):
        raise ValueError("timestamp must be finite")
    dt = datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_db_time_ms(value) -> float:
    if value is None:
        return float("nan")
    if isinstance(value, (int, float)):
        return float(value)
    txt = str(value).strip()
    if not txt:
        return float("nan")
    try:
        if "T" in txt:
            t = txt.replace("Z", "+00:00")
            dt = datetime.fromisoformat(t)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp() * 1000.0
        dt = datetime.strptime(txt[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.timestamp() * 1000.0
    except Exception:  # noqa: BLE001
        return float("nan")


def now_ms() -> float:
    return datetime.now(timezone.utc).timestamp() * 1000.0
