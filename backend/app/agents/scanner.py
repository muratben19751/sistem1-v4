import asyncio
import os
from datetime import datetime, timezone

from ..core.logger import create_logger
from ..core.event_bus import event_bus
from ..core.time import now_ms
from ..services.bybit_api import get_top_gainers, to_finite
from .strategy import analyze_symbol

log = create_logger("scanner")


def _int_env(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.environ.get(name) or default))
    except ValueError:
        return default


MIN_SCAN_INTERVAL_SEC = 30
MAX_SCAN_INTERVAL_SEC = 3600
MAX_SCAN_LIMIT = 100
DEFAULT_SCAN_LIMIT = 20
SCANNER_SYNC_ANALYSIS_BUDGET_MS = _int_env("SCANNER_SYNC_ANALYSIS_BUDGET_MS", 240000, 5000)
SCANNER_PER_SYMBOL_TIMEOUT_MS = _int_env("SCANNER_PER_SYMBOL_TIMEOUT_MS", 12000, 1000)
SCANNER_FETCH_MULTIPLIER = _int_env("SCANNER_FETCH_MULTIPLIER", 2, 1)
SCANNER_PARALLEL = _int_env("SCANNER_PARALLEL", 6, 1)

_last_scan_result: dict | None = None
_is_scanning = False
_scan_task: asyncio.Task | None = None
_stopping_tasks: set[asyncio.Task] = set()


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_scan_limit(limit) -> int:
    try:
        parsed = int(limit)
    except (TypeError, ValueError):
        return DEFAULT_SCAN_LIMIT
    if parsed <= 0:
        return DEFAULT_SCAN_LIMIT
    return min(parsed, MAX_SCAN_LIMIT)


def normalize_scan_interval_sec(interval_seconds) -> int:
    try:
        parsed = int(interval_seconds)
    except (TypeError, ValueError):
        return MIN_SCAN_INTERVAL_SEC
    if parsed <= 0:
        return MIN_SCAN_INTERVAL_SEC
    return min(max(parsed, MIN_SCAN_INTERVAL_SEC), MAX_SCAN_INTERVAL_SEC)


def _serialize_signal(signal) -> dict:
    return {
        "symbol": signal.symbol,
        "totalScore": signal.total_score,
        "side": signal.side,
        "rules": signal.rules,
        "timestamp": signal.timestamp,
    }


async def _analyze_with_timeout(symbol: str, timeout_ms: float):
    try:
        return await asyncio.wait_for(analyze_symbol(symbol), timeout=timeout_ms / 1000)
    except asyncio.TimeoutError:
        log.info(f"Analysis timeout for {symbol} after {timeout_ms}ms")
        return None
    except Exception as err:  # noqa: BLE001
        log.error(f"Analysis failed for {symbol}: {err}")
        return None


async def run_scan(limit: int = DEFAULT_SCAN_LIMIT) -> dict:
    global _last_scan_result, _is_scanning
    limit = normalize_scan_limit(limit)
    if _is_scanning:
        log.warn("Scan already in progress, skipping")
        return _last_scan_result or {"timestamp": _iso(), "symbols": [], "signals": []}

    _is_scanning = True
    started_at = now_ms()
    fetch_limit = min(MAX_SCAN_LIMIT, limit * SCANNER_FETCH_MULTIPLIER)
    log.info(f"Starting market scan (target {limit} scored, fetching {fetch_limit})")

    try:
        gainers = await get_top_gainers(fetch_limit)
        ticker_map = {t["symbol"]: {
            "symbol": t["symbol"],
            "lastPrice": to_finite(t.get("lastPrice")),
            "price24hPcnt": to_finite(t.get("price24hPcnt")) * 100,
            "volume24h": to_finite(t.get("volume24h")),
            "turnover24h": to_finite(t.get("turnover24h")),
            "fundingRate": to_finite(t.get("fundingRate")),
        } for t in gainers}

        # Tarama suresince onceki tamamlanmis sonucu KORU; sadece WS'e ara durum yayinla.
        working = {"timestamp": _iso(), "symbols": [], "signals": []}
        event_bus.emit("scan:complete", working)

        signals: list[dict] = []
        kept_symbols: list[dict] = []
        budget = SCANNER_SYNC_ANALYSIS_BUDGET_MS
        scanned = 0

        i = 0
        while i < len(gainers) and len(signals) < limit:
            remaining_budget = budget - (now_ms() - started_at)
            if remaining_budget < 1000:
                log.info(f"Scanner budget exhausted: {len(signals)}/{limit} scored, {scanned} scanned")
                break
            batch = gainers[i:i + SCANNER_PARALLEL]
            timeout_per_symbol = min(SCANNER_PER_SYMBOL_TIMEOUT_MS, remaining_budget)
            results = await asyncio.gather(*[_analyze_with_timeout(t["symbol"], timeout_per_symbol) for t in batch])
            scanned += len(batch)
            for j, signal in enumerate(results):
                if len(signals) >= limit:
                    break
                if not signal or signal.total_score == 0:
                    continue
                signals.append(_serialize_signal(signal))
                sym = ticker_map.get(batch[j]["symbol"])
                if sym:
                    kept_symbols.append(sym)
            working = {"timestamp": working["timestamp"], "symbols": list(kept_symbols), "signals": list(signals)}
            event_bus.emit("scan:complete", working)
            i += SCANNER_PARALLEL

        log.info(f"Scan complete: {len(signals)}/{limit} scored from {scanned} scanned ({now_ms() - started_at:.0f}ms)")
        _last_scan_result = working
        return _last_scan_result
    except Exception as err:  # noqa: BLE001
        if _last_scan_result:
            log.warn(f"Scan failed, returning stale scan result: {err}")
            return _last_scan_result
        raise
    finally:
        _is_scanning = False


async def _auto_scan_loop(interval_seconds: int) -> None:
    while _scan_task is not None:
        try:
            await run_scan()
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            log.error(f"Auto scan tick failed; next scan will retry: {err}")
        await asyncio.sleep(interval_seconds)


def start_auto_scan(interval_seconds: int = 30) -> None:
    global _scan_task
    if _scan_task is not None and not _scan_task.done():
        log.warn("Auto scan already running")
        return
    _scan_task = None
    interval_seconds = normalize_scan_interval_sec(interval_seconds)
    log.info(f"Starting auto scan every {interval_seconds}s")
    _scan_task = asyncio.create_task(_auto_scan_loop(interval_seconds))


def stop_auto_scan() -> None:
    global _scan_task
    if _scan_task is not None:
        task = _scan_task
        if not task.done():
            _stopping_tasks.add(task)
            task.add_done_callback(_stopping_tasks.discard)
            task.cancel()
        _scan_task = None
        log.info("Auto scan stopped")


async def wait_for_auto_scan_shutdown() -> None:
    while True:
        pending = [task for task in _stopping_tasks if not task.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


def get_last_scan_result() -> dict | None:
    return _last_scan_result


def is_scan_running() -> bool:
    return (_scan_task is not None and not _scan_task.done()) or _is_scanning
