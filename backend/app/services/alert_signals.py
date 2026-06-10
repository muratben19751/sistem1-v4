import json

from ..core.time import format_db_time_ms, now_ms
from ..db.database import query_all


def get_recent_alerts(source_types: list[str], freshness_minutes: int) -> list[dict]:
    placeholders = ",".join("?" for _ in source_types)
    cutoff = format_db_time_ms(now_ms() - freshness_minutes * 60_000)
    rows = query_all(
        f"""
        SELECT id, symbol, direction, source_type, signal_type, raw_message, rsi_data, srsi_data, price, boost_value, stars, created_at
        FROM alerts
        WHERE source_type IN ({placeholders})
          AND created_at >= ?
        ORDER BY created_at DESC
        """,
        (*source_types, cutoff),
    )
    seen: set[str] = set()
    results: list[dict] = []
    for row in rows:
        key = f"{row['symbol']}:{row['direction']}:{row['source_type']}"
        if key in seen:
            continue
        seen.add(key)
        rsi_data = {}
        srsi_data = {}
        try:
            if row["rsi_data"]:
                rsi_data = json.loads(row["rsi_data"])
        except Exception:  # noqa: BLE001
            pass
        try:
            if row["srsi_data"]:
                srsi_data = json.loads(row["srsi_data"])
        except Exception:  # noqa: BLE001
            pass
        results.append({
            "symbol": row["symbol"],
            "direction": row["direction"],
            "sourceType": row["source_type"],
            "signalType": row["signal_type"] or "",
            "rawMessage": row["raw_message"] or "",
            "rsiData": rsi_data,
            "srsiData": srsi_data,
            "price": row["price"],
            "boostValue": row["boost_value"] or 0,
            "stars": row["stars"] or 0,
            "alertId": row["id"],
            "createdAt": row["created_at"],
        })
    return results


def get_source_types(signal_source: str) -> list[str]:
    return {
        "hammer": ["hammer"],
        "sniper": ["4s_sniper", "sniper"],
        "fr": ["fr"],
        "m1_a": ["m1_a"],
        "v3_a": ["v3_a"],
        "hammer+sniper": ["hammer", "4s_sniper", "sniper"],
        "hammer+fr": ["hammer", "fr"],
        "sniper+fr": ["4s_sniper", "sniper", "fr"],
        "hammer+sniper+fr": ["hammer", "4s_sniper", "sniper", "fr"],
        "hammer+sniper+fr+m1_a": ["hammer", "4s_sniper", "sniper", "fr", "m1_a"],
        "scanner+hammer": ["hammer"],
        "scanner+sniper": ["4s_sniper", "sniper"],
        "scanner+fr": ["fr"],
        "scanner+m1_a": ["m1_a"],
        "scanner+v3_a": ["v3_a"],
        "scanner+hammer+sniper+fr": ["hammer", "4s_sniper", "sniper", "fr"],
        "scanner+hammer+sniper+fr+m1_a": ["hammer", "4s_sniper", "sniper", "fr", "m1_a"],
        "all": ["hammer", "4s_sniper", "sniper", "fr", "m1_a", "v3_a"],
    }.get(signal_source, [])


def needs_scanner(signal_source: str) -> bool:
    return signal_source in (
        "scanner", "scanner+hammer", "scanner+sniper", "scanner+fr", "scanner+m1_a",
        "scanner+v3_a", "scanner+hammer+sniper+fr", "scanner+hammer+sniper+fr+m1_a", "all",
    )


def is_alert_only(signal_source: str) -> bool:
    return signal_source in (
        "hammer", "sniper", "fr", "m1_a", "v3_a", "hammer+sniper", "hammer+fr",
        "sniper+fr", "hammer+sniper+fr", "hammer+sniper+fr+m1_a",
    )
