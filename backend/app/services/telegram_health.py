import math
from datetime import datetime, timezone

from ..core.config import config
from ..db.database import query_one

CHANNELS = [
    {"source": "4s_sniper", "label": "SNIPER", "env_key": "sniper", "stale_minutes": 180},
    {"source": "hammer", "label": "HAMMER", "env_key": "hammer", "stale_minutes": 180},
    {"source": "fr", "label": "FR", "env_key": "fr", "stale_minutes": 90},
    {"source": "m1_a", "label": "M1-A", "env_key": "m1a", "stale_minutes": 15},
]


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


def _newer(a: str | None, b: str | None) -> str | None:
    a_ms = _ts_ms(a)
    b_ms = _ts_ms(b)
    if a_ms is None:
        return b
    if b_ms is None:
        return a
    return a if a_ms >= b_ms else b


def _minutes_since(ts: str | None, now_ms: float) -> int | None:
    value = _ts_ms(ts)
    if value is None:
        return None
    return max(0, math.floor((now_ms - value) / 60_000))


def _latest_for_source(table: str, source: str, status: str | None = None) -> str | None:
    status_where = " AND status = ?" if status else ""
    params = (source, status) if status else (source,)
    row = query_one(
        f"""
        SELECT created_at as t
        FROM {table}
        WHERE source_type = ?{status_where}
        ORDER BY julianday(created_at) DESC
        LIMIT 1
        """,
        params,
    )
    return row["t"] if row else None


def get_telegram_channel_health() -> list[dict]:
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    rows: list[dict] = []

    for channel in CHANNELS:
        source = channel["source"]
        parsed_stats = query_one(
            """
            SELECT COUNT(*) as parsed_24h
            FROM alerts
            WHERE source_type = ?
              AND julianday(created_at) >= julianday('now', '-24 hours')
            """,
            (source,),
        )
        ingest_stats = query_one(
            """
            SELECT
              COUNT(*) as messages_24h,
              SUM(CASE WHEN status = 'unparsed' THEN 1 ELSE 0 END) as unparsed_24h
            FROM telegram_ingest_events
            WHERE source_type = ?
              AND julianday(created_at) >= julianday('now', '-24 hours')
            """,
            (source,),
        )

        parsed_24h = int((parsed_stats["parsed_24h"] if parsed_stats else 0) or 0)
        unparsed_24h = int((ingest_stats["unparsed_24h"] if ingest_stats else 0) or 0)
        messages_24h = max(
            int((ingest_stats["messages_24h"] if ingest_stats else 0) or 0),
            parsed_24h + unparsed_24h,
        )
        last_parsed_at = _latest_for_source("alerts", source)
        last_ingest_at = _latest_for_source("telegram_ingest_events", source)
        last_message_at = _newer(last_ingest_at, last_parsed_at)
        last_unparsed_at = _latest_for_source("telegram_ingest_events", source, "unparsed")
        fail_rate = unparsed_24h / messages_24h if messages_24h > 0 else 0.0
        parsed_age = _minutes_since(last_parsed_at, now_ms)
        configured = bool(getattr(config.telegram.channels, channel["env_key"], ""))

        status = "active"
        note = "ok"
        if not configured:
            status = "disabled"
            note = "not configured"
        elif not last_message_at and not last_parsed_at:
            status = "no_data"
            note = "no messages seen"
        elif fail_rate >= 0.25 and unparsed_24h >= 5:
            status = "parse_error"
            note = f"{round(fail_rate * 100)}% parse failures (24h)"
        elif parsed_age is not None and parsed_age > channel["stale_minutes"]:
            status = "stale"
            note = f"{parsed_age}m since parsed signal"

        rows.append(
            {
                "source_type": source,
                "label": channel["label"],
                "configured": configured,
                "status": status,
                "last_message_at": last_message_at,
                "last_parsed_at": last_parsed_at,
                "last_unparsed_at": last_unparsed_at,
                "messages_24h": messages_24h,
                "parsed_24h": parsed_24h,
                "unparsed_24h": unparsed_24h,
                "parse_fail_rate_24h": round(fail_rate, 4),
                "stale_minutes": channel["stale_minutes"],
                "note": note,
            }
        )

    return rows
