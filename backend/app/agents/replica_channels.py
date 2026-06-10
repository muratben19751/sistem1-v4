import asyncio
import inspect
import math
import os

from ..core.logger import create_logger
from ..core.time import now_ms
from ..services.bybit_api import get_tickers, get_klines, to_finite
from ..lib.indicators import calc_rsi, calc_stoch_rsi, calc_volume_change, Kline
from ..services.telegram_listener import process_incoming_alert
from .replica_buffer import record_replica_scan, record_replica_signal, cooldown_ok, commit_cooldown
from . import replica_params as rp

log = create_logger("replica-ch")


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


MAX_SYMBOLS = math.floor(_num_env("REPLICA_MAX_SYMBOLS", 300, 10))
MIN_TURNOVER = _num_env("REPLICA_MIN_TURNOVER", 5_000_000, 0)
PARALLEL = math.floor(_num_env("REPLICA_PARALLEL", 6, 1))

# Esikler (HAMMER_RSI_*, HAMMER_SRSI_*, FR_THRESHOLD_PCT, M1_MOVE_PCT) artik
# replica_params uzerinden CALISMA ZAMANINDA okunur; tuner bunlari canli ayarlar.
HAMMER_INTERVAL_SEC = math.floor(_num_env("HAMMER_INTERVAL_SEC", 60, 15))
FR_INTERVAL_SEC = math.floor(_num_env("FR_INTERVAL_SEC", 60, 15))
M1_INTERVAL_SEC = math.floor(_num_env("M1_INTERVAL_SEC", 60, 15))

HAMMER_COOLDOWN_MS = _num_env("HAMMER_COOLDOWN_MIN", 60, 0) * 60_000
FR_COOLDOWN_MS = _num_env("FR_COOLDOWN_MIN", 5, 0) * 60_000
M1_COOLDOWN_MS = _num_env("M1_COOLDOWN_MIN", 1, 0) * 60_000

_running = {"hammer": False, "fr": False, "m1": False}
_tasks: dict[str, asyncio.Task | None] = {"hammer": None, "fr": None, "m1": None}
_stopping_tasks: set[asyncio.Task] = set()


def _to_klines(rows: list[dict]) -> list[Kline]:
    return [
        Kline(time=r["time"], open=r["open"], high=r["high"], low=r["low"], close=r["close"], volume=r["volume"])
        for r in rows
    ]


def _rsi_of(k: list[Kline]):
    if len(k) < 20:
        return None
    return _js_round(calc_rsi([x.close for x in k]))


def _srsi_of(k: list[Kline]):
    if len(k) < 35:
        return None
    return _js_round(calc_stoch_rsi([x.close for x in k])["k"])


def _ext(v) -> str:
    if v is None:
        return ""
    return "❗️" if (v >= 80 or v <= 20) else ""


def _fmt_tf(label: str, vals: dict, order: list[str]) -> str:
    parts = [f"{tf}.{vals[tf]}{_ext(vals[tf])}" for tf in order if vals.get(tf) is not None]
    return f"{label}: **{' | '.join(parts)} **"


def _pad(n: int) -> str:
    return str(n).rjust(2, "0")


def _fmt_countdown(ms: float) -> str:
    s = max(0, math.floor(ms / 1000))
    h = s // 3600
    s -= h * 3600
    m = s // 60
    s -= m * 60
    return f"{_pad(h)}:{_pad(m)}:{_pad(s)}"


async def _liquid_universe() -> list[dict]:
    tickers = await get_tickers()
    rows = [t for t in tickers if str(t.get("symbol", "")).endswith("USDT")]
    rows = [t for t in rows if to_finite(t.get("turnover24h")) >= MIN_TURNOVER]
    rows.sort(key=lambda t: to_finite(t.get("turnover24h")), reverse=True)
    return rows[:MAX_SYMBOLS]


async def _run_batched(items: list, fn) -> None:
    for i in range(0, len(items), PARALLEL):
        batch = items[i:i + PARALLEL]

        async def _safe(x):
            try:
                await fn(x)
            except Exception as err:  # noqa: BLE001
                log.warn(f"batch item: {err}")

        await asyncio.gather(*[_safe(x) for x in batch])


async def _analyze_hammer(symbol: str):
    k1m_rows, k5m_rows, k1h_rows = await asyncio.gather(
        get_klines(symbol, "1", 200),
        get_klines(symbol, "5", 200),
        get_klines(symbol, "60", 200),
    )
    k1m = _to_klines(k1m_rows)
    k5m = _to_klines(k5m_rows)
    k1h = _to_klines(k1h_rows)
    if len(k5m) < 35 or len(k1m) < 35:
        return None

    rsi = {"1m": _rsi_of(k1m), "5m": _rsi_of(k5m), "1h": _rsi_of(k1h)}
    srsi = {"1m": _srsi_of(k1m), "5m": _srsi_of(k5m), "1h": _srsi_of(k1h)}
    r1 = rsi["1m"]
    r5 = rsi["5m"]
    s5 = srsi["5m"]
    if r1 is None or r5 is None or s5 is None:
        return None

    rsi_ob = rp.get("HAMMER_RSI_OB")
    rsi_os = rp.get("HAMMER_RSI_OS")
    srsi_ob = rp.get("HAMMER_SRSI_OB")
    srsi_os = rp.get("HAMMER_SRSI_OS")
    direction = None
    if r5 >= rsi_ob and r1 >= rsi_ob and s5 >= srsi_ob:
        direction = "DOWN"
    elif r5 <= rsi_os and r1 <= rsi_os and s5 <= srsi_os:
        direction = "UP"
    if not direction:
        return None

    closes = [k.close for k in k5m]
    price = closes[-1]
    previous_price = closes[-2]
    look = k5m[-6:]
    lo = min(k.low for k in look)
    hi = max(k.high for k in look)
    if direction == "DOWN":
        boost = ((price - lo) / lo) * 100 if lo > 0 else 0.0
    else:
        boost = ((hi - price) / price) * 100 if price > 0 else 0.0
    emoji = "🔴" if direction == "DOWN" else "🟢"
    raw = "\n".join([
        f"{emoji} #{symbol} ",
        f"Boost Value: +{boost:.2f}% ",
        f"Current Price: {price}",
        f"Previous Price: {previous_price}",
        _fmt_tf("RSI", rsi, ["1m", "5m", "1h"]),
        _fmt_tf("SRSI", srsi, ["1m", "5m", "1h"]),
        "Bybit | TradingView",
    ])
    return {"raw": raw, "symbol": symbol, "direction": direction}


async def _analyze_m1(symbol: str):
    k1_rows = await get_klines(symbol, "1", 120)
    k1 = _to_klines(k1_rows)
    if len(k1) < 30:
        return None
    closes = [k.close for k in k1]
    price = closes[-1]
    previous_price = closes[-2]
    move = ((price - previous_price) / previous_price) * 100 if previous_price > 0 else 0.0

    m1_move = rp.get("M1_MOVE_PCT")
    direction = None
    if move >= m1_move:
        direction = "UP"
    elif move <= -m1_move:
        direction = "DOWN"
    if not direction:
        return None

    rsi = _rsi_of(k1)
    st = calc_stoch_rsi(closes)
    vol = calc_volume_change(k1, 20)
    emoji = "🟢" if direction == "UP" else "🔴"
    label = "Boost Value" if direction == "UP" else "Drop Value"
    raw = "\n".join([
        f"{emoji} #{symbol}",
        f"{label}: {'+' if move >= 0 else ''}{move:.2f}%",
        f"Current Price: {price}",
        f"Previous Price: {previous_price}",
        f"Volume: {'+' if vol >= 0 else ''}{vol:.2f}%",
        f"RSI: **{rsi if rsi is not None else 50}**",
        f"Stochastic (K/D): **{_js_round(st['k'])}/{_js_round(st['d'])}**",
        "BTC Status: Normal",
        "Bybit | TradingView",
    ])
    return {"raw": raw, "symbol": symbol, "direction": direction}


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def _ingest(b: dict, source: str, dry_run: bool, cooldown_ms: float) -> bool:
    channel = source[:-6] if source.endswith("_local") else source
    cooldown_channel = f"{channel}:compare" if dry_run else channel
    effective_cooldown = 0 if dry_run else cooldown_ms
    if not cooldown_ok(cooldown_channel, b["symbol"], b["direction"], effective_cooldown, int(now_ms())):
        return False
    record_replica_signal({"channel": channel, "symbol": b["symbol"], "direction": b["direction"], "ts": int(now_ms())})
    if not dry_run:
        try:
            ingested = await _maybe_await(process_incoming_alert(b["raw"], source))
            if ingested is None:
                log.warn(f"ingest rejected {b['symbol']}: alert parse/store failed")
                return False
            commit_cooldown(cooldown_channel, b["symbol"], b["direction"], int(now_ms()))  # yalniz basarida tuket
        except Exception as err:  # noqa: BLE001
            log.warn(f"ingest {b['symbol']}: {err}")
            return False
    return True


async def run_hammer_scan(opts: dict = {}) -> list:
    if _running["hammer"]:
        return []
    _running["hammer"] = True
    completed = False
    out: list = []
    try:
        symbols = opts.get("symbols") or [t["symbol"] for t in await _liquid_universe()]
        dry_run = bool(opts.get("dryRun"))

        async def _do(sym):
            b = await _analyze_hammer(sym)
            if b and await _ingest(b, "hammer_local", dry_run, HAMMER_COOLDOWN_MS):
                out.append(b)

        await _run_batched(symbols, _do)
        log.info(f"hammer replica: {len(out)} sinyal / {len(symbols)} sembol")
        completed = True
        return out
    finally:
        _running["hammer"] = False
        if completed:
            record_replica_scan("hammer", int(now_ms()))


async def run_m1_scan(opts: dict = {}) -> list:
    if _running["m1"]:
        return []
    _running["m1"] = True
    completed = False
    out: list = []
    try:
        symbols = opts.get("symbols") or [t["symbol"] for t in await _liquid_universe()]
        dry_run = bool(opts.get("dryRun"))

        async def _do(sym):
            b = await _analyze_m1(sym)
            if b and await _ingest(b, "m1_a_local", dry_run, M1_COOLDOWN_MS):
                out.append(b)

        await _run_batched(symbols, _do)
        log.info(f"m1_a replica: {len(out)} sinyal / {len(symbols)} sembol")
        completed = True
        return out
    finally:
        _running["m1"] = False
        if completed:
            record_replica_scan("m1_a", int(now_ms()))


async def run_fr_scan(opts: dict = {}) -> list:
    if _running["fr"]:
        return []
    _running["fr"] = True
    completed = False
    out: list = []
    try:
        universe = await _liquid_universe()
        dry_run = bool(opts.get("dryRun"))
        now = int(now_ms())
        fr_threshold = rp.get("FR_THRESHOLD_PCT")
        for t in universe:
            try:
                rate = float(t.get("fundingRate"))
            except (TypeError, ValueError):
                continue
            if rate != rate or rate in (float("inf"), float("-inf")):
                continue
            pct = rate * 100
            if abs(pct) < fr_threshold:
                continue
            direction = "UP" if pct < 0 else "DOWN"
            try:
                next_ms = int(t.get("nextFundingTime"))
                tr = _fmt_countdown(next_ms - now)
            except (TypeError, ValueError):
                tr = "00:00:00"
            raw = "\n".join([
                f"#{t['symbol']}",
                f"Funding Rate: {pct:.4f}",
                f"Time Remaining: {tr}",
                "Bybit | TradingView",
            ])
            b = {"raw": raw, "symbol": t["symbol"], "direction": direction}
            if await _ingest(b, "fr_local", dry_run, FR_COOLDOWN_MS):
                out.append(b)
        log.info(f"fr replica: {len(out)} sinyal / {len(universe)} sembol (esik {fr_threshold}%)")
        completed = True
        return out
    finally:
        _running["fr"] = False
        if completed:
            record_replica_scan("fr", int(now_ms()))


async def _periodic(fn, interval_sec: int) -> None:
    while True:
        try:
            await fn()
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            log.warn(f"{fn.__name__} failed; next scan will retry: {err}")
        await asyncio.sleep(interval_sec)


def _task_running(task: asyncio.Task | None) -> bool:
    return task is not None and not task.done()


def start_replica_channels() -> None:
    if any(_task_running(task) for task in _tasks.values()):
        log.warn("Replica channels already scheduled")
        return
    for key, task in _tasks.items():
        if task is not None and task.done():
            _tasks[key] = None
    _tasks["fr"] = asyncio.create_task(_periodic(run_fr_scan, FR_INTERVAL_SEC))
    _tasks["hammer"] = asyncio.create_task(_periodic(run_hammer_scan, HAMMER_INTERVAL_SEC))
    _tasks["m1"] = asyncio.create_task(_periodic(run_m1_scan, M1_INTERVAL_SEC))
    log.info(f"Replica channels baslatildi (hammer {HAMMER_INTERVAL_SEC}s, fr {FR_INTERVAL_SEC}s, m1_a {M1_INTERVAL_SEC}s)")


def are_replica_channels_running() -> bool:
    return any(_task_running(task) for task in _tasks.values())


def stop_replica_channels() -> None:
    for k in list(_tasks.keys()):
        t = _tasks[k]
        if t:
            if not t.done():
                _stopping_tasks.add(t)
                t.add_done_callback(_stopping_tasks.discard)
                t.cancel()
            _tasks[k] = None
    log.info("Replica channels durduruldu")


async def wait_for_replica_channels_shutdown() -> None:
    while True:
        pending = [task for task in _stopping_tasks if not task.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)
