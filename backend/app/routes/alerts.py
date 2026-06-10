import asyncio
import math
import re
import sqlite3
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db.database import DB_PATH, query_one, query_all, execute
from ..services.telegram_client import backfill_channel_history
from ..services.telegram_listener import process_incoming_alert
from ..services.telegram_health import get_telegram_channel_health

router = APIRouter()


def parse_positive_int(value, fallback: int) -> int:
    text = str(value if value is not None else "").strip()
    if not re.fullmatch(r"\d+", text):
        return fallback
    parsed = int(text)
    return parsed if parsed > 0 else fallback


def parse_non_negative_int(value, fallback: int) -> int:
    text = str(value if value is not None else "").strip()
    if not re.fullmatch(r"\d+", text):
        return fallback
    parsed = int(text)
    return parsed if parsed >= 0 else fallback


@router.get("")
async def list_alerts(request: Request):
    q = request.query_params
    limit = min(parse_positive_int(q.get("limit"), 50), 500)
    offset = parse_non_negative_int(q.get("offset"), 0)
    symbol = (q.get("symbol") or "").strip()
    direction = (q.get("direction") or "").strip().upper()
    if direction and direction not in ("UP", "DOWN"):
        return JSONResponse(status_code=400, content={"error": "Invalid direction"})

    query = "SELECT * FROM alerts"
    conditions: list[str] = []
    params: list = []

    if symbol:
        conditions.append("symbol LIKE ?")
        params.append(f"%{symbol.upper()}%")
    if direction:
        conditions.append("direction = ?")
        params.append(direction)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = query_all(query, params)
    return [dict(r) for r in rows]


@router.get("/range")
async def alerts_range(request: Request):
    q = request.query_params
    symbol = (q.get("symbol") or "").strip().upper()
    if not symbol:
        return JSONResponse(status_code=400, content={"error": "symbol required"})
    try:
        since = float(q.get("since"))
        until = float(q.get("until"))
    except (TypeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "since/until (ms epoch) required"})
    if not math.isfinite(since) or not math.isfinite(until) or until <= since:
        return JSONResponse(status_code=400, content={"error": "since/until (ms epoch) required"})

    rows = query_all(
        """
        SELECT id, symbol, direction, source_type, price, stars, matched_with_bot, funding_rate, created_at,
          COALESCE(alerts.bybit_fr, (
            SELECT fc.funding_rate FROM funding_cache fc
            WHERE fc.symbol = alerts.symbol
              AND fc.funding_ts <= (julianday(replace(replace(alerts.created_at, 'T', ' '), 'Z', '')) - 2440587.5) * 86400000
            ORDER BY fc.funding_ts DESC LIMIT 1
          )) AS bybit_fr
        FROM alerts
        WHERE symbol = ?
          AND julianday(replace(replace(created_at, 'T', ' '), 'Z', '')) >= julianday(?, 'unixepoch')
          AND julianday(replace(replace(created_at, 'T', ' '), 'Z', '')) <= julianday(?, 'unixepoch')
        ORDER BY created_at ASC
        LIMIT 5000
        """,
        (symbol, since / 1000, until / 1000),
    )
    return [dict(r) for r in rows]


# /stats 1.3M+ satirda tam tarama yapar; UI her yeni alarmda cagiriyor. Kisa TTL cache ile
# DB yukunu bastir (sayim degerleri saniyelik tazelikte fazlasiyla yeterli).
_STATS_CACHE: dict = {"at": 0.0, "data": None}
_STATS_TTL_S = 30.0
_STATS_LOCK = asyncio.Lock()


def _load_alert_stats() -> dict:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 15000")
    try:
        counts = conn.execute(
            """
            SELECT COUNT(*) AS total,
              COALESCE(SUM(CASE WHEN matched_with_bot = 1 THEN 1 ELSE 0 END), 0) AS matched,
              COALESCE(SUM(CASE WHEN direction = 'UP' THEN 1 ELSE 0 END), 0) AS up_count,
              COALESCE(SUM(CASE WHEN direction = 'DOWN' THEN 1 ELSE 0 END), 0) AS down_count
            FROM alerts
            """
        ).fetchone()
        top_symbols = conn.execute(
            "SELECT symbol, COUNT(*) as cnt FROM alerts GROUP BY symbol ORDER BY cnt DESC LIMIT 10"
        ).fetchall()
        return {
            "total": counts["total"],
            "matched": counts["matched"],
            "upCount": counts["up_count"],
            "downCount": counts["down_count"],
            "topSymbols": [dict(r) for r in top_symbols],
        }
    finally:
        conn.close()


@router.get("/stats")
async def alerts_stats():
    now = time.monotonic()
    if _STATS_CACHE["data"] is not None and (now - _STATS_CACHE["at"]) < _STATS_TTL_S:
        return _STATS_CACHE["data"]
    async with _STATS_LOCK:
        now = time.monotonic()
        if _STATS_CACHE["data"] is not None and (now - _STATS_CACHE["at"]) < _STATS_TTL_S:
            return _STATS_CACHE["data"]
        data = await asyncio.to_thread(_load_alert_stats)
        _STATS_CACHE["data"] = data
        _STATS_CACHE["at"] = time.monotonic()
        return data


@router.get("/channel-health")
async def channel_health():
    return get_telegram_channel_health()


@router.post("")
async def create_alert(request: Request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    message = body.get("message") if isinstance(body, dict) else None
    source = body.get("source") if isinstance(body, dict) else None
    if not isinstance(message, str) or len(message.strip()) == 0:
        return JSONResponse(status_code=400, content={"error": "message required"})
    result = process_incoming_alert(message, source or "manual")
    if not result:
        return JSONResponse(status_code=400, content={"error": "Could not parse alert"})
    return result


@router.post("/backfill")
async def backfill(request: Request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    limit = min(parse_positive_int(body.get("limit") if isinstance(body, dict) else None, 500), 2000)
    try:
        results = await backfill_channel_history(limit)
    except Exception as err:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(err)})
    return {
        "success": True,
        "totalInserted": sum(result["inserted"] for result in results),
        "channels": results,
    }


@router.delete("/{alert_id}")
async def delete_alert(alert_id: str):
    valid = bool(re.fullmatch(r"\d+", alert_id))
    aid = int(alert_id) if valid else None
    if aid is None or aid <= 0:
        return JSONResponse(status_code=400, content={"error": "Invalid alert id"})
    execute("DELETE FROM alerts WHERE id = ?", (aid,))
    return {"success": True}
