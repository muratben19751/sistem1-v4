import asyncio
import inspect
import math
import os

from ..core.logger import create_logger
from ..core.time import now_ms
from ..services.bybit_api import get_tickers, get_klines, to_finite
from ..lib.indicators import (
    calc_rsi,
    calc_stoch_rsi,
    calc_rsi_series,
    sma,
    calc_nadaraya_watson,
    detect_rsi_divergence,
    Kline,
)
from ..services.telegram_listener import process_incoming_alert
from .replica_buffer import record_replica_scan, record_replica_signal, cooldown_ok, commit_cooldown
from . import replica_params as rp

log = create_logger("nw-sniper")


def _num_env(name: str, default: float, minimum: float) -> float:
    try:
        v = float(os.environ.get(name) or "")
    except ValueError:
        return default
    if v != v or v in (float("inf"), float("-inf")):
        return default
    return max(minimum, v)


def _js_round(x: float) -> int:
    return math.floor(x + 0.5)


TF_1H = "60"
TF_4H = "240"
TF_1D = "D"

NW_BANDWIDTH = _num_env("NW_SNIPER_BANDWIDTH", 6, 1)
NW_MULT = _num_env("NW_SNIPER_MULT", 3, 0.5)
MAX_SYMBOLS = _num_env("NW_SNIPER_MAX_SYMBOLS", 300, 10)
MIN_TURNOVER = _num_env("NW_SNIPER_MIN_TURNOVER", 5_000_000, 0)
# POS_MIN / RSI_OB / RSI_OS / SRSI_OB / SRSI_OS artik replica_params uzerinden
# CALISMA ZAMANINDA okunur; tuner bunlari canli ayarlar.
PARALLEL = math.floor(_num_env("NW_SNIPER_PARALLEL", 6, 1))
SOURCE = os.environ.get("NW_SNIPER_SOURCE") or "nw_local"
COOLDOWN_MS = _num_env("NW_SNIPER_COOLDOWN_MIN", 200, 0) * 60_000
FOUR_HOURS_MS = 4 * 60 * 60 * 1000

_scanning = False
_task: asyncio.Task | None = None
_stopping_tasks: set[asyncio.Task] = set()


def _to_klines(rows: list[dict]) -> list[Kline]:
    return [
        Kline(time=r["time"], open=r["open"], high=r["high"], low=r["low"], close=r["close"], volume=r["volume"])
        for r in rows
    ]


def _rsi_of(klines: list[Kline]):
    if len(klines) < 20:
        return None
    return _js_round(calc_rsi([k.close for k in klines]))


def _srsi_of(klines: list[Kline]):
    if len(klines) < 35:
        return None
    return _js_round(calc_stoch_rsi([k.close for k in klines])["k"])


def _ext(v) -> str:
    if v is None:
        return ""
    return "❗️" if (v >= 80 or v <= 20) else ""


def _fmt_tf(label: str, vals: dict) -> str:
    parts = [f"{tf}.{vals[tf]}{_ext(vals[tf])}" for tf in ("1h", "4h", "1d") if vals.get(tf) is not None]
    return f"{label}: **{' | '.join(parts)} **"


def _compute_boost(k4: list[Kline], direction: str) -> float:
    look = min(len(k4), 30)
    slice_ = k4[-look:]
    close = slice_[-1].close
    if direction == "DOWN":
        lo = min(k.low for k in slice_)
        return ((close - lo) / lo) * 100 if lo > 0 else 0.0
    hi = max(k.high for k in slice_)
    return ((hi - close) / close) * 100 if close > 0 else 0.0


def _rsi_sma_cross(k4: list[Kline]):
    series = calc_rsi_series([k.close for k in k4])
    if len(series) < 16:
        return None
    sma_series = sma(series, 14)
    if len(sma_series) < 2:
        return None
    off = len(series) - len(sma_series)
    r0 = series[-2]
    r1 = series[-1]
    s0 = sma_series[-2]
    s1 = sma_series[-1]
    if off < 0:
        return None
    if r0 <= s0 and r1 > s1 and r1 < 50:
        return "UP"
    if r0 >= s0 and r1 < s1 and r1 > 50:
        return "DOWN"
    return None


def _build_raw(symbol, direction, strategy, boost, price, previous_price, rsi, srsi) -> str:
    emoji = "🔴" if direction == "DOWN" else "🟢"
    return "\n".join([
        f"{emoji} #{symbol}  ",
        f"Strategy: {strategy}",
        f"Boost Value: +{boost:.2f}% ",
        f"Current Price: {price}",
        f"Previous Price: {previous_price}",
        _fmt_tf("RSI", rsi),
        _fmt_tf("SRSI", srsi),
        "Bybit | TradingView",
    ])


async def _analyze(symbol: str):
    k1_rows, k4_rows, kd_rows = await asyncio.gather(
        get_klines(symbol, TF_1H, 200),
        get_klines(symbol, TF_4H, 200),
        get_klines(symbol, TF_1D, 200),
    )
    k1 = _to_klines(k1_rows)
    k4 = _to_klines(k4_rows)
    kd = _to_klines(kd_rows)
    if len(k4) < 40 or len(k1) < 30:
        return None

    nw = calc_nadaraya_watson(k4, NW_BANDWIDTH, NW_MULT)
    if not nw:
        return None

    closes4 = [k.close for k in k4]
    price = closes4[-1]
    previous_price = closes4[-2]
    pos = nw["position"]

    rsi = {"1h": _rsi_of(k1), "4h": _rsi_of(k4), "1d": _rsi_of(kd)}
    srsi = {"1h": _srsi_of(k1), "4h": _srsi_of(k4), "1d": _srsi_of(kd)}
    rsi4 = rsi["4h"]
    srsi4 = srsi["4h"]

    pos_min = rp.get("NW_SNIPER_POS_MIN")
    rsi_ob = rp.get("NW_SNIPER_RSI_OB")
    rsi_os = rp.get("NW_SNIPER_RSI_OS")
    srsi_ob = rp.get("NW_SNIPER_SRSI_OB")
    srsi_os = rp.get("NW_SNIPER_SRSI_OS")
    direction = None
    strategy = None

    if pos >= pos_min and rsi4 is not None and srsi4 is not None and rsi4 >= rsi_ob and srsi4 >= srsi_ob:
        direction = "DOWN"
        strategy = "NW DOWN"
    elif pos <= -pos_min and rsi4 is not None and srsi4 is not None and rsi4 <= rsi_os and srsi4 <= srsi_os:
        direction = "UP"
        strategy = "NW UP"

    if not direction:
        cross = _rsi_sma_cross(k4)
        if cross:
            direction = cross
            strategy = "4H RSI SMA CROSSED"

    if not direction:
        dv = detect_rsi_divergence(k4)
        if dv["type"] in ("bearish", "forming_bearish"):
            direction = "DOWN"
            strategy = "4H RSI DIVERGENCE"
        elif dv["type"] in ("bullish", "forming_bullish"):
            direction = "UP"
            strategy = "4H RSI DIVERGENCE"

    if not direction or not strategy:
        return None

    boost = _compute_boost(k4, direction)
    raw = _build_raw(symbol, direction, strategy, boost, price, previous_price, rsi, srsi)
    return {
        "symbol": symbol,
        "direction": direction,
        "strategy": strategy,
        "boost": boost,
        "price": price,
        "previousPrice": previous_price,
        "rsi": rsi,
        "srsi": srsi,
        "raw": raw,
    }


async def _pick_universe() -> list[str]:
    tickers = await get_tickers()
    rows = [
        {"symbol": t["symbol"], "turnover": to_finite(t.get("turnover24h"))}
        for t in tickers
        if str(t.get("symbol", "")).endswith("USDT")
    ]
    rows = [t for t in rows if t["turnover"] >= MIN_TURNOVER]
    rows.sort(key=lambda t: t["turnover"], reverse=True)
    return [t["symbol"] for t in rows[:int(MAX_SYMBOLS)]]


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def run_nw_sniper_scan(opts: dict = {}) -> list:
    global _scanning
    if _scanning:
        log.warn("NW sniper scan already running, skipping")
        return []
    _scanning = True
    started = now_ms()
    completed = False
    signals: list = []
    try:
        universe = opts.get("symbols") or await _pick_universe()
        dry_run = bool(opts.get("dryRun"))
        log.info(f"NW sniper scan basladi: {len(universe)} sembol (dryRun={dry_run})")
        for i in range(0, len(universe), PARALLEL):
            batch = universe[i:i + PARALLEL]

            async def _safe(sym):
                try:
                    return await _analyze(sym)
                except Exception as err:  # noqa: BLE001
                    log.warn(f"analyze {sym}: {err}")
                    return None

            results = await asyncio.gather(*[_safe(sym) for sym in batch])
            for r in results:
                if not r:
                    continue
                cooldown_channel = "sniper:compare" if dry_run else "sniper"
                effective_cooldown = 0 if dry_run else COOLDOWN_MS
                if not cooldown_ok(cooldown_channel, r["symbol"], r["direction"], effective_cooldown, int(now_ms())):
                    continue
                signals.append(r)
                record_replica_signal({"channel": "sniper", "symbol": r["symbol"], "direction": r["direction"], "strategy": r["strategy"], "ts": int(now_ms())})

        if not dry_run:
            for s in signals:
                try:
                    ingested = await _maybe_await(process_incoming_alert(s["raw"], SOURCE))
                    if ingested is None:
                        log.warn(f"ingest rejected {s['symbol']}: alert parse/store failed")
                        continue
                    commit_cooldown("sniper", s["symbol"], s["direction"], int(now_ms()))
                except Exception as err:  # noqa: BLE001
                    log.warn(f"ingest {s['symbol']}: {err}")
        log.info(f"NW sniper scan bitti: {len(signals)} sinyal / {len(universe)} sembol ({now_ms() - started:.0f}ms)")
        completed = True
        return signals
    except Exception as err:  # noqa: BLE001
        log.error(f"NW sniper scan hatasi: {err}")
        return signals
    finally:
        _scanning = False
        if completed:
            record_replica_scan("sniper", int(now_ms()))


def _ms_until_next_4h_boundary(now: float) -> float:
    next_ = math.ceil((now + 1) / FOUR_HOURS_MS) * FOUR_HOURS_MS
    return next_ - now


async def _schedule_loop() -> None:
    while True:
        wait = _ms_until_next_4h_boundary(now_ms()) + 15_000
        log.info(f"NW sniper: sonraki tarama {round(wait / 1000)}s sonra (4H sinir + 15s)")
        await asyncio.sleep(wait / 1000.0)
        await run_nw_sniper_scan()


def start_nw_sniper() -> None:
    global _task
    if _task is not None and not _task.done():
        log.warn("NW sniper already scheduled")
        return
    _task = None
    _task = asyncio.create_task(_schedule_loop())
    log.info("NW sniper baslatildi (4 saatte bir, 4H mum kapanisinda)")


def is_nw_sniper_running() -> bool:
    return _task is not None and not _task.done()


def stop_nw_sniper() -> None:
    global _task
    if _task is not None:
        task = _task
        if not task.done():
            _stopping_tasks.add(task)
            task.add_done_callback(_stopping_tasks.discard)
            task.cancel()
        _task = None
        log.info("NW sniper durduruldu")


async def wait_for_nw_sniper_shutdown() -> None:
    while True:
        pending = [task for task in _stopping_tasks if not task.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)
