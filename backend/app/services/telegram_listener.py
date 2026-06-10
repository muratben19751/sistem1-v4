import asyncio
import json
import math
import re
import time

from ..core.event_bus import event_bus
from ..core.logger import create_logger
from ..core.time import format_db_time_ms, now_ms, parse_db_time_ms
from ..db.database import execute, query_all, query_one
from .alert_parser import get_alert_parse_failure_reason, parse_alert
from .bybit_api import get_funding_rate, is_tradable_linear_symbol

log = create_logger("telegram-listener")

_WS_REGEX = re.compile(r"\s+")
_NO_SUCH_TABLE_REGEX = re.compile(r"no such table", re.IGNORECASE)
_enrichment_tasks: set[asyncio.Task] = set()


async def _enrich_bybit_fr(alert_id: int, symbol: str) -> None:
    try:
        if not await is_tradable_linear_symbol(symbol):
            return
        fr = await get_funding_rate(symbol)
        if math.isfinite(fr):
            execute("UPDATE alerts SET bybit_fr = ? WHERE id = ?", (fr, alert_id))
    except Exception:  # noqa: BLE001
        pass


# fr alert'ine Bybit funding rate'ini arka planda (fire-and-forget) ekler; ingest'i bloklamaz.
def enrich_bybit_fr(alert_id: int, symbol: str) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_enrich_bybit_fr(alert_id, symbol))
    _enrichment_tasks.add(task)
    task.add_done_callback(_enrichment_tasks.discard)


async def cancel_alert_enrichment_tasks() -> None:
    while True:
        pending = [task for task in _enrichment_tasks if not task.done()]
        if not pending:
            return
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


_throttled_logs: dict[str, float] = {}


def log_throttled(key: str, level: str, message: str, min_interval_ms: int = 30_000) -> None:
    now = time.time() * 1000.0
    if now - _throttled_logs.get(key, 0.0) < min_interval_ms:
        return
    _throttled_logs[key] = now
    getattr(log, level)(message)


def table_exists(table_name: str) -> bool:
    try:
        row = query_one(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table_name,),
        )
        return bool(row and row["name"])
    except Exception:  # noqa: BLE001
        return False


def sample_message(raw_message: str) -> str:
    return _WS_REGEX.sub(" ", raw_message).strip()[:500]


def record_ingest_event(
    source: str,
    status: str,
    raw_message: str,
    received_at: str,
    parsed: dict | None = None,
    error: str | None = None,
) -> None:
    if not table_exists("telegram_ingest_events"):
        log_throttled("ingest-table-missing", "warn", "telegram_ingest_events tablosu yok, ingest event atlandi")
        return

    try:
        execute(
            """
            INSERT INTO telegram_ingest_events
                (source_type, status, symbol, direction, error, raw_message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parsed["sourceType"] if parsed else source,
                status,
                parsed["symbol"] if parsed else None,
                parsed["direction"] if parsed else None,
                error,
                sample_message(raw_message) if status == "unparsed" else None,
                received_at,
            ),
        )
    except Exception as err:  # noqa: BLE001
        log_throttled("ingest", "error", f"Telegram ingest-event yazilamadi: {err}")


def process_incoming_alert(
    raw_message: str,
    source: str = "telegram",
    record_ingest: bool = True,
    received_at: str | None = None,
) -> dict | None:
    received_ms = parse_db_time_ms(received_at) if received_at else now_ms()
    if not math.isfinite(received_ms):
        received_ms = now_ms()
    received_at = format_db_time_ms(received_ms)

    if not table_exists("alerts"):
        log_throttled("alerts-table-missing", "warn", "alerts tablosu yok, gelen alarm kaydi atlandi")
        return None

    parsed = parse_alert(raw_message, source)
    if not parsed:
        reason = get_alert_parse_failure_reason(raw_message, source)
        if record_ingest is not False:
            record_ingest_event(
                source=source,
                status="unparsed",
                raw_message=raw_message,
                error=reason,
                received_at=received_at,
            )
        log_throttled(
            "parse:" + source,
            "warn",
            f'Could not parse alert message [{source}] reason={reason} sample="{sample_message(raw_message)[:160]}"',
        )
        return None

    try:
        positions = (
            query_all("SELECT * FROM open_positions WHERE symbol = ?", (parsed["symbol"],))
            if table_exists("open_positions")
            else []
        )

        if len(positions) == 0 and not table_exists("open_positions"):
            log_throttled("positions-table-missing", "warn", "open_positions tablosu yok, eslesme hesaplamasi atlandi")

        matched_with_bot = 1 if any(
            (parsed["direction"] == "UP" and p["side"] == "long")
            or (parsed["direction"] == "DOWN" and p["side"] == "short")
            for p in positions
        ) else 0

        rsi = parsed["rsi"]
        srsi = parsed["srsi"]

        result = execute(
            """
            INSERT INTO alerts (symbol, direction, signal_type, source_type,
                rsi_h1, rsi_h4, rsi_d1, rsi_1m, rsi_5m,
                srsi, srsi_1m, srsi_5m, srsi_1h, srsi_4h, srsi_1d,
                rsi_data, srsi_data,
                boost_value, price, previous_price,
                funding_rate, previous_funding, time_remaining, funding_changed,
                stars, raw_message, source, matched_with_bot, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parsed["symbol"],
                parsed["direction"],
                parsed["signalType"],
                parsed["sourceType"],
                rsi.get("1h"),
                rsi.get("4h"),
                rsi.get("1d"),
                rsi.get("1m"),
                rsi.get("5m"),
                srsi.get("1h") if srsi.get("1h") is not None else srsi.get("1m"),
                srsi.get("1m"),
                srsi.get("5m"),
                srsi.get("1h"),
                srsi.get("4h"),
                srsi.get("1d"),
                json.dumps(rsi, separators=(",", ":")),
                json.dumps(srsi, separators=(",", ":")),
                parsed["boostValue"],
                parsed["price"],
                parsed["previousPrice"],
                parsed["fundingRate"],
                parsed["previousFunding"],
                parsed["timeRemaining"],
                parsed["fundingChanged"],
                parsed["stars"],
                parsed["rawMessage"],
                parsed["source"],
                matched_with_bot,
                received_at,
            ),
        )

        alert_id = result.lastrowid

        if parsed["sourceType"] == "fr":
            enrich_bybit_fr(int(alert_id), parsed["symbol"])

        if record_ingest is not False:
            record_ingest_event(
                source=source,
                status="parsed",
                raw_message=raw_message,
                parsed=parsed,
                received_at=received_at,
            )

        alert_data = {
            "id": int(alert_id),
            "symbol": parsed["symbol"],
            "direction": parsed["direction"],
            "signal_type": parsed["signalType"],
            "source_type": parsed["sourceType"],
            "rsi_data": json.dumps(rsi, separators=(",", ":")),
            "srsi_data": json.dumps(srsi, separators=(",", ":")),
            "boost_value": parsed["boostValue"],
            "price": parsed["price"],
            "previous_price": parsed["previousPrice"],
            "funding_rate": parsed["fundingRate"],
            "previous_funding": parsed["previousFunding"],
            "time_remaining": parsed["timeRemaining"],
            "funding_changed": parsed["fundingChanged"],
            "stars": parsed["stars"],
            "matched_with_bot": matched_with_bot,
            "created_at": received_at,
        }

        event_bus.emit("alert:received", alert_data)
        log.info(
            f"Alert processed: {parsed['symbol']} {parsed['direction']} "
            f"[{parsed['sourceType']}] (matched: {matched_with_bot})"
        )

        return alert_data
    except Exception as err:  # noqa: BLE001
        message = str(err)
        if _NO_SUCH_TABLE_REGEX.search(message):
            log_throttled("db-table-missing", "warn", f"Telegram alert DB tablosu eksik [{parsed['symbol']}]: {message}")
            return None
        log_throttled("db-insert", "error", f"Telegram alert DB yazimi basarisiz [{parsed['symbol']}]: {message}")
        return None


def reparse_old_alerts() -> None:
    if not table_exists("alerts"):
        log_throttled("reparse-alerts-missing", "warn", "alerts tablosu yok, reparse atlandi")
        return
    old = query_all("SELECT id, raw_message, source, direction FROM alerts WHERE raw_message IS NOT NULL")
    if len(old) == 0:
        return

    sql = """
        UPDATE alerts SET source_type = ?, direction = ?, rsi_data = ?, srsi_data = ?,
            rsi_1m = ?, rsi_5m = ?, rsi_h1 = ?, rsi_h4 = ?, rsi_d1 = ?,
            srsi_1m = ?, srsi_5m = ?, srsi_1h = ?, srsi_4h = ?, srsi_1d = ?, srsi = ?,
            previous_price = ?, signal_type = COALESCE(?, signal_type),
            funding_rate = ?, previous_funding = ?, time_remaining = ?, funding_changed = ?,
            stars = ?
        WHERE id = ?
    """

    count = 0
    for row in old:
        parsed = parse_alert(row["raw_message"], row["source"] or "telegram")
        if not parsed:
            continue
        rsi = parsed["rsi"]
        srsi = parsed["srsi"]
        execute(
            sql,
            (
                parsed["sourceType"],
                parsed["direction"],
                json.dumps(rsi, separators=(",", ":")),
                json.dumps(srsi, separators=(",", ":")),
                rsi.get("1m"),
                rsi.get("5m"),
                rsi.get("1h"),
                rsi.get("4h"),
                rsi.get("1d"),
                srsi.get("1m"),
                srsi.get("5m"),
                srsi.get("1h"),
                srsi.get("4h"),
                srsi.get("1d"),
                srsi.get("1h") if srsi.get("1h") is not None else srsi.get("1m"),
                parsed["previousPrice"],
                parsed["signalType"] if parsed["signalType"] != "UNKNOWN" else None,
                parsed["fundingRate"],
                parsed["previousFunding"],
                parsed["timeRemaining"],
                parsed["fundingChanged"],
                parsed["stars"],
                row["id"],
            ),
        )
        count += 1
    log.info(f"Reparsed {count}/{len(old)} old alerts")
