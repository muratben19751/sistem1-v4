import os
import time
from datetime import datetime, timedelta, timezone

from ..db.database import get_db
from .telegram_health import get_telegram_channel_health

BUCKETS_24H = 288
FRESHNESS_MS_UP = 3 * 60 * 1000
DAY_MS = 24 * 60 * 60 * 1000
PROCESS_STARTED_AT_MS = time.time() * 1000


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts_ms(ts: str | None) -> float | None:
    if not ts:
        return None
    text = ts if "T" in ts else ts.replace(" ", "T")
    if not (text.endswith("Z") or "+" in text[10:] or "-" in text[10:]):
        text += "Z"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000
    except ValueError:
        return None


def _bucket_sql_expr(col: str) -> str:
    return (
        f"substr(replace({col}, ' ', 'T'), 1, 14) || "
        f"(printf('%02d', (cast(substr({col}, 15, 2) as integer) / 5) * 5))"
    )


def _count_buckets(rows) -> int:
    return len({r["bucket"] for r in rows})


def _uptime_pct(up_buckets: int) -> float:
    return min(100.0, (up_buckets / BUCKETS_24H) * 100)


def _process_uptime_pct() -> float:
    uptime_ms = max(0.0, time.time() * 1000 - PROCESS_STARTED_AT_MS)
    return min(100.0, (min(uptime_ms, DAY_MS) / DAY_MS) * 100)


def _hourly_rows_for(col: str, table: str) -> list:
    return get_db().execute(
        f"SELECT DISTINCT substr(replace({col}, ' ', 'T'), 1, 13) as h FROM {table} "
        f"WHERE julianday({col}) > julianday('now','-24 hours')"
    ).fetchall()


def _hourly_buckets(rows) -> dict:
    seen = {r["h"] for r in rows}
    now = datetime.now(timezone.utc)
    hourly: list[bool] = []
    last_down = None
    for i in range(23, -1, -1):
        bucket = now - timedelta(hours=i)
        key = bucket.isoformat()[:13]
        up = key in seen
        hourly.append(up)
        if not up and i > 0:
            last_down = key + ":00:00Z"
    return {"hourly": hourly, "lastDown": last_down}


def _process_hourly_buckets() -> list[bool]:
    now = datetime.now(timezone.utc)
    hourly: list[bool] = []
    for i in range(23, -1, -1):
        bucket_end = now - timedelta(hours=i)
        bucket_end = bucket_end.replace(minute=59, second=59, microsecond=999000)
        hourly.append(bucket_end.timestamp() * 1000 >= PROCESS_STARTED_AT_MS)
    return hourly


def _latest_timestamp_for(col: str, table: str) -> str | None:
    row = get_db().execute(
        f"SELECT {col} as t FROM {table} WHERE {col} IS NOT NULL ORDER BY julianday({col}) DESC LIMIT 1"
    ).fetchone()
    return row["t"] if row else None


def _service_from_table(name: str, table: str, col: str, freshness_ms: int) -> dict:
    rows = get_db().execute(
        f"SELECT DISTINCT {_bucket_sql_expr(col)} as bucket FROM {table} "
        f"WHERE julianday({col}) > julianday('now','-24 hours')"
    ).fetchall()
    latest = _latest_timestamp_for(col, table)
    latest_ms = _ts_ms(latest)
    up = latest_ms is not None and (time.time() * 1000 - latest_ms) < freshness_ms
    hourly = _hourly_buckets(_hourly_rows_for(col, table))
    return {
        "name": name,
        "current": "up" if up else "down",
        "uptime24h": _uptime_pct(_count_buckets(rows)),
        "lastSeen": latest,
        "hourly": hourly["hourly"],
        "lastDown": hourly["lastDown"],
    }


async def get_services_health() -> dict:
    backend_up = True
    try:
        get_db().execute("SELECT 1").fetchone()
    except Exception:  # noqa: BLE001
        backend_up = False

    now_iso = _iso_now()
    telegram = _service_from_table("Telegram", "alerts", "created_at", 5 * 60 * 1000)
    channel_health = get_telegram_channel_health()
    blocking = [c for c in channel_health if c["configured"] and c["status"] == "parse_error"]
    soft = [c for c in channel_health if c["configured"] and c["status"] in ("stale", "no_data")]
    if blocking:
        telegram["current"] = "down"
        telegram["note"] = ", ".join(f"{c['label']} parse" for c in blocking)
    elif soft:
        telegram["note"] = ", ".join(f"{c['label']} {c['status']}" for c in soft)

    services = [
        {
            "name": "Backend",
            "current": "up" if backend_up else "down",
            "uptime24h": _process_uptime_pct(),
            "lastSeen": now_iso if backend_up else None,
            "hourly": _process_hourly_buckets(),
            "lastDown": None,
            "note": f"pid {os.getpid()}",
        },
        _service_from_table("Bots", "bot_logs", "created_at", FRESHNESS_MS_UP),
        telegram,
    ]
    return {"services": services, "ts": now_iso}
