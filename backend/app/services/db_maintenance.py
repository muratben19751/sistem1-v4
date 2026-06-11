"""Gunluk DB bakim gorevi: sinirsiz buyuyen tablolari budar.

Retention pencereleri:
- bot_logs: islem gunlugu, kisa omurlu -> 14 gun
- telegram_ingest_events: ham ingest izi -> 90 gun
- alerts: backtest/optimizer 365 gunluk gecmis kullanir (OPTIMIZER_BACKTEST_DAYS)
  -> 430 gun tutulur ki yillik kosumlar bozulmasin.
- kline_cache: mevcut prune_kline_cache (400g + stale) gunluk olarak yeniden kosulur
  (startup'taki tek seferlik kosum uzun uptime'larda yetmez).

equity_snapshots BILEREK budanmaz: max-drawdown peak'i tum gecmis uzerinden
hesaplanir, silmek devre kesici davranisini degistirir.
"""

import asyncio
import os

from ..core.logger import create_logger
from ..db.database import execute
from .kline_cache import prune_kline_cache

log = create_logger("db-maintenance")


def _int_env(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.environ.get(name) or default))
    except ValueError:
        return default


BOT_LOGS_KEEP_DAYS = _int_env("DB_KEEP_BOT_LOGS_DAYS", 14, 1)
INGEST_KEEP_DAYS = _int_env("DB_KEEP_INGEST_DAYS", 90, 7)
ALERTS_KEEP_DAYS = _int_env("DB_KEEP_ALERTS_DAYS", 430, 400)
MAINTENANCE_INTERVAL_SEC = _int_env("DB_MAINTENANCE_INTERVAL_SEC", 24 * 3600, 3600)
STARTUP_DELAY_SEC = _int_env("DB_MAINTENANCE_STARTUP_DELAY_SEC", 120, 0)

_task: asyncio.Task | None = None


def _prune_once() -> dict[str, int]:
    deleted: dict[str, int] = {}
    deleted["bot_logs"] = execute(
        "DELETE FROM bot_logs WHERE created_at < datetime('now', ?)",
        (f"-{BOT_LOGS_KEEP_DAYS} days",),
    ).rowcount or 0
    deleted["telegram_ingest_events"] = execute(
        "DELETE FROM telegram_ingest_events WHERE created_at < datetime('now', ?)",
        (f"-{INGEST_KEEP_DAYS} days",),
    ).rowcount or 0
    deleted["alerts"] = execute(
        "DELETE FROM alerts WHERE created_at < datetime('now', ?)",
        (f"-{ALERTS_KEEP_DAYS} days",),
    ).rowcount or 0
    kline = prune_kline_cache()
    deleted["kline_cache"] = kline["byAge"] + kline["byStale"]
    return deleted


async def _loop() -> None:
    await asyncio.sleep(STARTUP_DELAY_SEC)
    while True:
        try:
            deleted = await asyncio.to_thread(_prune_once)
            total = sum(deleted.values())
            if total > 0:
                log.info(f"DB bakim: {total} satir budandi {deleted}")
        except Exception as err:  # noqa: BLE001
            log.error(f"DB bakim turu basarisiz: {err}")
        await asyncio.sleep(MAINTENANCE_INTERVAL_SEC)


def start_db_maintenance() -> None:
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop())
    log.info(
        f"DB bakim gorevi basladi (bot_logs {BOT_LOGS_KEEP_DAYS}g, ingest {INGEST_KEEP_DAYS}g, "
        f"alerts {ALERTS_KEEP_DAYS}g, periyot {MAINTENANCE_INTERVAL_SEC}s)"
    )


def stop_db_maintenance() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
