import asyncio
import math
import os

from ..core.logger import create_logger
from ..core.time import now_ms, parse_db_time_ms
from ..db.database import query_all
from ..services.bybit_api import get_tradable_linear_symbols
from .nw_sniper import is_nw_sniper_running, run_nw_sniper_scan
from .replica_channels import are_replica_channels_running, run_hammer_scan, run_fr_scan, run_m1_scan
from .replica_buffer import get_replica_scan_time, get_replica_signals

log = create_logger("replica-compare")


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


HAMMER_SEC = math.floor(_num_env("CMP_HAMMER_SEC", 90, 30))
FR_SEC = math.floor(_num_env("CMP_FR_SEC", 60, 20))
M1_SEC = math.floor(_num_env("CMP_M1_SEC", 90, 30))

CHANNELS = [
    {"channel": "sniper", "sourceType": "4s_sniper", "label": "Sniper (4H NW)"},
    {"channel": "hammer", "sourceType": "hammer", "label": "Hammer (1m/5m)"},
    {"channel": "fr", "sourceType": "fr", "label": "Funding Rate"},
    {"channel": "m1_a", "sourceType": "m1_a", "label": "M1 Momentum"},
]

_tasks: dict[str, asyncio.Task | None] = {"hammer": None, "fr": None, "m1": None}
_sniper_task: asyncio.Task | None = None
_started = False
_passive = False
_stopping_tasks: set[asyncio.Task] = set()

SNIPER_SEC = math.floor(_num_env("CMP_SNIPER_SEC", 1800, 300))


async def _run_compare_scan(channel: str, fn) -> None:
    await fn({"dryRun": True})


async def _periodic(channel: str, fn, interval_sec: int) -> None:
    while True:
        try:
            await _run_compare_scan(channel, fn)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            log.warn(f"Replica compare {channel} scan failed; next scan will retry: {err}")
        await asyncio.sleep(interval_sec)


def start_replica_compare() -> None:
    global _started, _sniper_task, _passive
    if _started:
        log.warn("Replica compare already running")
        return
    _started = True
    _passive = are_replica_channels_running() or is_nw_sniper_running()
    if _passive:
        log.info("Replica compare pasif gozlem modunda; aktif replica taramalarinin buffer'i kullaniliyor")
        return
    _tasks["fr"] = asyncio.create_task(_periodic("fr", run_fr_scan, FR_SEC))
    _tasks["hammer"] = asyncio.create_task(_periodic("hammer", run_hammer_scan, HAMMER_SEC))
    _tasks["m1"] = asyncio.create_task(_periodic("m1_a", run_m1_scan, M1_SEC))
    _sniper_task = asyncio.create_task(_periodic("sniper", run_nw_sniper_scan, SNIPER_SEC))
    log.info(f"Replica compare baslatildi (buffer-only; fr {FR_SEC}s, hammer {HAMMER_SEC}s, m1 {M1_SEC}s, sniper {SNIPER_SEC}s)")


def stop_replica_compare() -> None:
    global _started, _sniper_task, _passive
    for k in list(_tasks.keys()):
        t = _tasks[k]
        if t:
            if not t.done():
                _stopping_tasks.add(t)
                t.add_done_callback(_stopping_tasks.discard)
                t.cancel()
            _tasks[k] = None
    if _sniper_task:
        if not _sniper_task.done():
            _stopping_tasks.add(_sniper_task)
            _sniper_task.add_done_callback(_stopping_tasks.discard)
            _sniper_task.cancel()
        _sniper_task = None
    _started = False
    _passive = False
    log.info("Replica compare durduruldu")


async def wait_for_replica_compare_shutdown() -> None:
    while True:
        pending = [task for task in _stopping_tasks if not task.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


async def build_comparison(minutes: int) -> dict:
    now = int(now_ms())
    window_ms = max(5, min(720, minutes)) * 60_000
    since_ms = now - window_ms

    replica_all = get_replica_signals(since_ms)

    try:
        tradable = await get_tradable_linear_symbols()
    except Exception as err:  # noqa: BLE001
        log.warn(f"Replica comparison skipped; tradable symbol universe unavailable: {err}")
        return {
            "minutes": minutes,
            "generatedAt": now,
            "running": _started,
            "channels": [],
            "error": "tradable_symbol_universe_unavailable",
        }
    if not tradable:
        return {
            "minutes": minutes,
            "generatedAt": now,
            "running": _started,
            "channels": [],
            "error": "tradable_symbol_universe_empty",
        }

    def on_bybit(sym: str) -> bool:
        return sym in tradable

    real_rows = []
    try:
        for source_type in {c["sourceType"] for c in CHANNELS}:
            real_rows.extend(query_all(
                """
                SELECT symbol, direction, source_type, created_at FROM alerts
                WHERE source_type = ? AND (source IS NULL OR source NOT LIKE '%local')
                ORDER BY created_at DESC LIMIT 6000
                """,
                (source_type,),
            ))
    except Exception as err:  # noqa: BLE001
        log.warn(f"Replica comparison real alert query failed: {err}")
        return {
            "minutes": minutes,
            "generatedAt": now,
            "running": _started,
            "channels": [],
            "error": "real_alert_query_failed",
        }

    real_recent_all = []
    for r in real_rows:
        ts = parse_db_time_ms(r["created_at"])
        if ts == ts and ts >= since_ms:
            real_recent_all.append({"symbol": r["symbol"], "direction": r["direction"], "sourceType": r["source_type"], "ts": ts})
    real_recent = [r for r in real_recent_all if on_bybit(r["symbol"])]

    channels = []
    for c in CHANNELS:
        real = [r for r in real_recent if r["sourceType"] == c["sourceType"]]
        off_bybit = len([r for r in real_recent_all if r["sourceType"] == c["sourceType"] and not on_bybit(r["symbol"])])
        rep = [r for r in replica_all if r["channel"] == c["channel"]]

        real_dir: dict[str, str] = {}
        for r in real:
            if r["symbol"] not in real_dir:
                real_dir[r["symbol"]] = r["direction"]
        rep_dir: dict[str, str] = {}
        for r in rep:
            if r["symbol"] not in rep_dir:
                rep_dir[r["symbol"]] = r["direction"]

        matched = 0
        agree = 0
        for sym, dir_ in rep_dir.items():
            if sym in real_dir:
                matched += 1
                if real_dir[sym] == dir_:
                    agree += 1

        feed = []
        for r in real[:60]:
            m = r["symbol"] in rep_dir
            feed.append({
                "symbol": r["symbol"], "direction": r["direction"], "origin": "real", "ts": r["ts"],
                "matched": m, "agree": m and rep_dir.get(r["symbol"]) == r["direction"],
            })
        for r in rep[-60:]:
            m = r["symbol"] in real_dir
            feed.append({
                "symbol": r["symbol"], "direction": r["direction"], "origin": "replica", "ts": r["ts"],
                "matched": m, "agree": m and real_dir.get(r["symbol"]) == r["direction"],
            })
        feed.sort(key=lambda x: x["ts"], reverse=True)

        channels.append({
            "channel": c["channel"],
            "label": c["label"],
            "sourceType": c["sourceType"],
            "realCount": len(real),
            "realOffBybit": off_bybit,
            "replicaCount": len(rep),
            "realSymbols": len(real_dir),
            "replicaSymbols": len(rep_dir),
            "matched": matched,
            "agree": agree,
            "agreePct": _js_round((agree / matched) * 100) if matched else None,
            "coveragePct": _js_round((matched / len(real_dir)) * 100) if len(real_dir) else None,
            "precisionPct": _js_round((matched / len(rep_dir)) * 100) if len(rep_dir) else None,
            "realLatestTs": max((r["ts"] for r in real), default=None),
            "replicaLatestTs": max((r["ts"] for r in rep), default=None),
            "replicaScanCompletedTs": get_replica_scan_time(c["channel"]),
            "feed": feed[:50],
        })

    return {
        "minutes": minutes,
        "generatedAt": now,
        "running": _started,
        "passive": _passive,
        "channels": channels,
    }
