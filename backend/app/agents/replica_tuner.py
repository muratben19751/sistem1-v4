"""Replica tuner — surekli calisan otomatik kalibrasyon ajani.

Amac: 4 replica kanalini (sniper / hammer / fr / m1_a) gercek kaynaklarla
"esitlemek". Her dongude build_comparison metriklerini okur ve her kanal icin
replica esiklerini (replica_params) gercek kaynaga yaklasacak sekilde ayarlar.

Kontrol mantigi (B modu: sembol-eslestirme = yon-dogru ortusme hedefli):
  R = gercek kaynaktaki ayri sembol sayisi (pencere icinde)
  P = replica'nin urettigi ayri sembol sayisi
  A = AYNI sembol + AYNI yon ortusen sayi (agree)
    effKapsama = A / R   -> gercegin ne kadarini ayni yonde yakaladik (recall)
    effIsabet  = A / P   -> urettigimizin ne kadari dogru ortusme (precision)
  Oncelik merdiveni:
    effIsabet  < ISABET_TABANI   -> SIKILASTIR (once gurultuyu kes; tasmayi onler)
    effKapsama < KAPSAMA_HEDEFI  -> GEVSET (daha cok gercek sembol yakala)
    effIsabet  < ISABET_HEDEFI   -> SIKILASTIR (yanlislari ayikla)
    yoksa                        -> denge, dokunma
  Boylece sadece sinyal SAYISI degil, AYNI sembolleri AYNI yonde yakalamak optimize edilir.
  R < MIN_REAL ise yeterli "yer gercegi" yok -> o kanali atla.

Adimlar kucuk ve sinirli (dongude en cok MAX_STEPS adim) tutulur; boylece
zamanla yakinsar, salinim yapmaz. Tum parametreler app_config'te kalicidir.
"""
import asyncio
import json
import math
import os

from ..core.logger import create_logger
from ..core.time import now_ms
from ..db.database import execute, query_one
from . import replica_params as rp
from .replica_compare import build_comparison

log = create_logger("replica-tuner")

_STATE_KEY = "replica_tuner_state"


def _num_env(name: str, default: float, minimum: float) -> float:
    try:
        v = float(os.environ.get(name) or "")
    except ValueError:
        return default
    if v != v or v in (float("inf"), float("-inf")):
        return default
    return max(minimum, v)


INTERVAL_SEC = math.floor(_num_env("REPLICA_TUNER_INTERVAL_SEC", 120, 30))
WINDOW_MIN = math.floor(_num_env("REPLICA_TUNER_WINDOW_MIN", 120, 5))
MIN_REAL = math.floor(_num_env("REPLICA_TUNER_MIN_REAL", 3, 1))
MAX_STEPS = math.floor(_num_env("REPLICA_TUNER_MAX_STEPS", 2, 1))
HISTORY_MAX = 60
MIN_ADJUST_INTERVAL_SEC = math.floor(
    _num_env("REPLICA_TUNER_MIN_ADJUST_INTERVAL_SEC", max(1800, WINDOW_MIN * 30), 300)
)
# B modu hedefleri (0..1): yon-dogru ortusme (agree) bazli kapsama/isabet
COVERAGE_TARGET = min(1.0, _num_env("REPLICA_TUNER_COVERAGE_TARGET", 0.70, 0.05))
PRECISION_TARGET = min(1.0, _num_env("REPLICA_TUNER_PRECISION_TARGET", 0.70, 0.05))
PRECISION_FLOOR = min(PRECISION_TARGET, _num_env("REPLICA_TUNER_PRECISION_FLOOR", 0.40, 0.0))
TARGET_BAND = _num_env("REPLICA_TUNER_TARGET_BAND", 0.05, 0.0)  # hedef etrafinda histerezis
STEP_SCALE = _num_env("REPLICA_TUNER_STEP_SCALE", 0.25, 0.05)   # bu kadar acik = 1 adim

_task: asyncio.Task | None = None
_stopping_tasks: set[asyncio.Task] = set()
_cycle_lock = asyncio.Lock()
_last_adjusted: dict[str, dict] = {}
_state_loaded = False
_state: dict = {
    "running": False,
    "cycles": 0,
    "updatedAt": 0,
    "intervalSec": INTERVAL_SEC,
    "windowMin": WINDOW_MIN,
    "channels": [],
    "params": {},
    "history": [],
}


def _ensure_state_loaded() -> None:
    global _state_loaded, _last_adjusted
    if _state_loaded:
        return
    try:
        row = query_one("SELECT value FROM app_config WHERE key = ?", (_STATE_KEY,))
        if not row:
            _state_loaded = True
            return
        saved = json.loads(row["value"])
        if not isinstance(saved, dict):
            _state_loaded = True
            return
        for key in ("cycles", "updatedAt", "channels", "params", "history", "error"):
            if key in saved:
                _state[key] = saved[key]
        restored = saved.get("lastAdjusted") or {}
        if isinstance(restored, dict):
            _last_adjusted = {
                channel: {
                    "ts": int(value.get("ts") or 0),
                    "signature": tuple(value.get("signature") or ()),
                }
                for channel, value in restored.items()
                if isinstance(value, dict)
            }
        _state_loaded = True
    except Exception as err:  # noqa: BLE001
        log.warn(f"Replica tuner state could not be restored: {err}")


def _persist_state() -> None:
    try:
        _state["lastAdjusted"] = {
            channel: {"ts": value["ts"], "signature": list(value["signature"])}
            for channel, value in _last_adjusted.items()
        }
        execute(
            "INSERT INTO app_config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')",
            (_STATE_KEY, json.dumps(_state)),
        )
    except Exception:  # noqa: BLE001
        pass


def _steps_for(gap: float) -> int:
    """Hedefe uzaklik (gap, 0..1) buyukse daha cok adim (MAX_STEPS ile sinirli)."""
    n = math.ceil(gap / STEP_SCALE) if gap > 0 else 1
    return max(1, min(MAX_STEPS, n))


def _decide(metrics: dict, ts: int) -> dict:
    channel = metrics["channel"]
    real = metrics.get("realSymbols", 0)
    replica = metrics.get("replicaSymbols", 0)
    params = rp.CHANNEL_PARAMS.get(channel, [])
    if real < MIN_REAL:
        return {"channel": channel, "real": real, "replica": replica,
                "ratio": None, "action": "skip", "reason": "az_gercek", "steps": 0}

    scan_completed = metrics.get("replicaScanCompletedTs")
    window_start = ts - WINDOW_MIN * 60_000
    if not scan_completed or scan_completed < window_start:
        return {"channel": channel, "real": real, "replica": replica,
                "ratio": None, "action": "skip", "reason": "replica_tarama_hazir_degil", "steps": 0}

    # B modu: yon-dogru ortusme (agree) bazli kapsama/isabet (her hold/aksiyonda gosterilir)
    agree = metrics.get("agree", 0)
    eff_cov = agree / real if real else 0.0
    eff_prec = (agree / replica) if replica else 1.0  # sinyal yoksa yanlis-pozitif yok
    base = {"channel": channel, "real": real, "replica": replica,
            "ratio": round(replica / real, 2),
            "covPct": round(eff_cov * 100), "precPct": round(eff_prec * 100)}

    signature = (
        real,
        replica,
        metrics.get("matched", 0),
        agree,
        metrics.get("realLatestTs"),
        metrics.get("replicaLatestTs"),
    )
    previous = _last_adjusted.get(channel)
    if previous and previous["signature"] == signature:
        return {**base, "action": "hold", "reason": "yeni_veri_yok", "steps": 0}
    if previous and ts - previous["ts"] < MIN_ADJUST_INTERVAL_SEC * 1000:
        return {**base, "action": "hold", "reason": "ayar_bekleme_suresi", "steps": 0}

    # Oncelik merdiveni
    if eff_prec < PRECISION_FLOOR:
        sign, action, gap, reason = +1, "tighten", PRECISION_TARGET - eff_prec, "dusuk_isabet_taban"
    elif eff_cov < COVERAGE_TARGET - TARGET_BAND:
        sign, action, gap, reason = -1, "loosen", COVERAGE_TARGET - eff_cov, "dusuk_kapsama"
    elif eff_prec < PRECISION_TARGET - TARGET_BAND:
        sign, action, gap, reason = +1, "tighten", PRECISION_TARGET - eff_prec, "dusuk_isabet"
    else:
        return {**base, "action": "hold", "reason": "denge", "steps": 0}

    n = _steps_for(gap)
    changed = {}
    adjustments = {}
    before_values = {}
    for name in params:
        before_values[name] = rp.get(name)
        adjustments[name] = sign * rp.tighten_sign(name) * n
    updated = rp.adjust_many(adjustments)
    for name, after in updated.items():
        if after != before_values[name]:
            changed[name] = round(after, 4)
    if changed:
        _last_adjusted[channel] = {"ts": ts, "signature": signature}
        return {**base, "action": action, "steps": n, "reason": reason, "changed": changed}
    return {**base, "action": "hold", "steps": 0, "reason": "parametre_siniri", "changed": {}}


async def run_tuner_cycle() -> dict:
    """Tek bir kalibrasyon dongusu: kiyas oku, kanallari ayarla, durumu kaydet."""
    async with _cycle_lock:
        _ensure_state_loaded()
        cmp = await build_comparison(WINDOW_MIN)
        decisions = []
        ts = int(now_ms())
        for ch in cmp.get("channels", []):
            d = _decide(ch, ts)
            d["agreePct"] = ch.get("agreePct")
            d["coveragePct"] = ch.get("coveragePct")
            d["precisionPct"] = ch.get("precisionPct")
            d["label"] = ch.get("label")
            decisions.append(d)

        _state["running"] = _task_running()
        _state["cycles"] += 1
        _state["updatedAt"] = ts
        _state["channels"] = decisions
        _state["params"] = {k: round(v, 4) for k, v in rp.snapshot().items()}
        _state["error"] = cmp.get("error")
        hist = _state["history"]
        hist.append({"ts": ts, "decisions": [
            {"channel": d["channel"], "action": d["action"],
             "covPct": d.get("covPct"), "precPct": d.get("precPct"),
             "real": d["real"], "replica": d["replica"], "steps": d.get("steps", 0)}
            for d in decisions
        ]})
        if len(hist) > HISTORY_MAX:
            del hist[0:len(hist) - HISTORY_MAX]
        _persist_state()

    acted = [d for d in decisions if d["action"] in ("tighten", "loosen")]
    if acted:
        summary = ", ".join(
            f"{d['channel']}:{d['action']}(kapsama{d.get('covPct')}%/isabet{d.get('precPct')}%)"
            for d in acted
        )
        log.info(f"tuner dongu #{_state['cycles']}: {summary}")
    else:
        log.info(f"tuner dongu #{_state['cycles']}: degisiklik yok (tum kanallar denge/atlandi)")
    return _state


async def _loop() -> None:
    log.info(f"Replica tuner basladi [B modu: sembol-eslestirme] (her {INTERVAL_SEC}s, "
             f"pencere {WINDOW_MIN}dk, kapsama hedef {COVERAGE_TARGET}, isabet hedef {PRECISION_TARGET}, "
             f"isabet taban {PRECISION_FLOOR}, en cok {MAX_STEPS} adim)")
    # ilk dongu baslangic gecikmesiyle (replica buffer'in dolmasi icin)
    await asyncio.sleep(min(INTERVAL_SEC, 30))
    while True:
        try:
            await run_tuner_cycle()
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            log.warn(f"tuner dongu hatasi: {err}")
        await asyncio.sleep(INTERVAL_SEC)


def _task_running() -> bool:
    return _task is not None and not _task.done()


def start_replica_tuner() -> None:
    global _task
    _ensure_state_loaded()
    if _task_running():
        log.warn("Replica tuner already running")
        return
    _task = None
    _state["running"] = True
    _task = asyncio.create_task(_loop())


def stop_replica_tuner() -> None:
    global _task
    _ensure_state_loaded()
    if _task is not None:
        task = _task
        if not task.done():
            _stopping_tasks.add(task)
            task.add_done_callback(_stopping_tasks.discard)
            task.cancel()
        _task = None
    _state["running"] = False
    _persist_state()
    log.info("Replica tuner durduruldu")


async def wait_for_replica_tuner_shutdown() -> None:
    while True:
        pending = [task for task in _stopping_tasks if not task.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


def tuner_state() -> dict:
    _ensure_state_loaded()
    return {
        **_state,
        "running": _task_running(),
        "config": {
            "mode": "match",  # B: sembol-eslestirme (kapsama+isabet)
            "intervalSec": INTERVAL_SEC, "windowMin": WINDOW_MIN, "minReal": MIN_REAL,
            "coverageTarget": COVERAGE_TARGET, "precisionTarget": PRECISION_TARGET,
            "precisionFloor": PRECISION_FLOOR, "targetBand": TARGET_BAND,
            "stepScale": STEP_SCALE, "maxSteps": MAX_STEPS,
            "minAdjustIntervalSec": MIN_ADJUST_INTERVAL_SEC,
        },
        "params": {k: round(v, 4) for k, v in rp.snapshot().items()},
    }
