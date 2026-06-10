"""Backtest GA optimizer — v4 (gelistirilmis).

v3'e gore dort eksende iyilestirildi (public API birebir korunur, motor degismez):

1) ASIRI-UYUM / VALIDASYON
   - Tek sabit pencere yerine **walk-forward**: pencere F kat'a (fold) bolunur, her genom
     her fold'da ayri backtest edilir. Fold'lar arasina **embargo (purge) bosulugu** konur
     ki bir fold'un sonunda acilip digerinde kapanan islem sizmasin.
   - Fitness fold'lar arasi **ortalama - lambda*std** ile hesaplanir: yalnizca tek bir
     rejimde iyi olan (overfit) strateji yuksek dispersiyon -> dusuk fitness alir.
   - OPTIMIZER_WF_FOLDS=1 verilirse eski tek-pencere davranisina geri doner.

2) JUNK BUG
   - calmar=99 / maxDD=0 artifakti fitness'i kacirmasin diye DD'ye taban (DD_FLOOR)
     uygulanir ve calmar CAP'lenir. Junk (cok az islem / sifir DD) hem skorlamada hem
     **ureme havuzunda** elenir (eskiden yalnizca ekranda eleniyordu).

3) GA KALITESI
   - Turnuva secimi (sadece top-3 degil), daha buyuk elit + ureme havuzu.
   - Her nesle **rastgele goçmen (immigrant)** enjekte edilir -> cesitlilik korunur,
     popülasyon elitlerin kopyasina yakinsamaz.
   - Genomlar config_hash ile tekillestirilir; popülasyon DB'ye yazilir (restart'ta surer).

4) PERFORMANS
   - Backtest saf-Python CPU-bound (numpy yok) -> asyncio paralellik vermez (GIL).
     Opsiyonel **ProcessPoolExecutor** (spawn) ile genom×fold backtest'leri gercek
     cekirdeklere dagitilir. OPTIMIZER_PROCESS_POOL=auto|1|0 (varsayilan auto).
     Havuz ilk gercek is parcasinda denenir; hata olursa otomatik in-process'e duser.
"""

import asyncio
import concurrent.futures
import json
import math
import multiprocessing
import os
import random
import time
from dataclasses import dataclass, field, replace

from ..core.logger import create_logger
from ..core.event_bus import event_bus
from ..db.database import query_one, query_all, execute
from ..strategies.rule_registry import get_all_rule_keys
from ..engines.backtest_engine import run_backtest
from ..services.kline_cache import configure_kline_heap_cache, enable_kline_heap_cache

log = create_logger("bt-optimizer")


def _env_int(name: str, default: int) -> int:
    try:
        v = int(os.environ.get(name) or "")
    except ValueError:
        v = 0
    return v or default


def _env_float(name: str, default: float) -> float:
    try:
        v = float(os.environ.get(name) or "")
    except ValueError:
        v = 0.0
    return v or default


def _round2(x: float) -> float:
    # Faithful to JS Math.round(x * 100) / 100 (round-half-up toward +inf).
    return math.floor(x * 100 + 0.5) / 100


def _rh(x: float) -> int:
    # Faithful to JS Math.round (round-half-up toward +inf).
    return math.floor(x + 0.5)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


# ----- temel parametreler (v3 ile ayni anlam) -----
BACKTEST_DAYS = max(7, _env_int("OPTIMIZER_BACKTEST_DAYS", 365))
MAX_SIGNALS = max(500, _env_int("OPTIMIZER_MAX_SIGNALS", 8000))
MAX_SYMBOLS = max(5, _env_int("OPTIMIZER_MAX_SYMBOLS", 40))
CYCLE_PAUSE_MS = max(500, _env_int("OPTIMIZER_CYCLE_PAUSE_MS", 2000))
POP_SIZE = max(4, _env_int("OPTIMIZER_POP_SIZE", 8))
WORKER_COUNT = max(1, min(POP_SIZE, _env_int("OPTIMIZER_WORKERS", 0) or max(2, (os.cpu_count() or 1) // 3)))
TOTAL_HEAP_MAX_BARS = max(100_000, _env_int("OPTIMIZER_HEAP_TOTAL_MAX_BARS", 8_000_000))
WORKER_HEAP_MAX_BARS = max(
    100_000,
    _env_int("OPTIMIZER_HEAP_MAX_BARS", 0) or TOTAL_HEAP_MAX_BARS // (WORKER_COUNT + 1),
)
OPTIMIZER_MIN_INTERVAL = (os.environ.get("OPTIMIZER_MIN_INTERVAL") or "5").strip()
MIN_TRADES = 5

# ----- (1) walk-forward validasyon -----
WF_FOLDS = max(1, _env_int("OPTIMIZER_WF_FOLDS", 3))
WF_EMBARGO_DAYS = max(0.0, _env_float("OPTIMIZER_WF_EMBARGO_DAYS", 2))
MIN_FOLD_TRADES = max(1, _env_int("OPTIMIZER_MIN_FOLD_TRADES", 5))
MIN_VALID_FOLDS_FRAC = _clamp(_env_float("OPTIMIZER_MIN_VALID_FOLDS_FRAC", 0.6), 0.0, 1.0)
ROBUST_LAMBDA = max(0.0, _env_float("OPTIMIZER_ROBUST_LAMBDA", 0.5))

# ----- (2) junk / metrik saglamlastirma -----
DD_FLOOR = max(0.0, _env_float("OPTIMIZER_DD_FLOOR", 1.0))        # % — calmar paydasi tabani
CALMAR_CAP = max(1.0, _env_float("OPTIMIZER_CALMAR_CAP", 10.0))   # sanitize edilmis calmar tavani
# Cok az islemli sonuclar sansa baglidir (coklu-test sismesi). conf = T/(T+K) ile fitness'i
# kuculturuz; T<<K iken skor ~0'a cekilir.
TRADE_CONF_K = max(0, _env_int("OPTIMIZER_TRADE_CONF_K", 20))
# Kalite harmani: calmar agirlikli + sharpe katkisi.
CALMAR_W = max(0.0, _env_float("OPTIMIZER_CALMAR_W", 0.7))
SHARPE_W = max(0.0, _env_float("OPTIMIZER_SHARPE_W", 0.3))
PF_GATE_PENALTY = max(0.0, _env_float("OPTIMIZER_PF_GATE_PENALTY", 1.0))

# Kaldirac cezasi (v3'ten korunur): yuksek kaldirac+yuksek getiri sismesini frenler.
FIT_LEV_FREE = max(1.0, _env_float("OPTIMIZER_LEV_FREE", 3))
FIT_LEV_COEFF = max(0.0, _env_float("OPTIMIZER_LEV_COEFF", 0.25))

# ----- (3) GA kalitesi -----
ELITE_COUNT = max(1, _env_int("OPTIMIZER_ELITE_COUNT", 4))
TOURNAMENT_K = max(2, _env_int("OPTIMIZER_TOURNAMENT_K", 3))
IMMIGRANT_FRAC = _clamp(_env_float("OPTIMIZER_IMMIGRANT_FRAC", 0.2), 0.0, 0.8)
BREED_POOL = max(POP_SIZE * 2, _env_int("OPTIMIZER_BREED_POOL", POP_SIZE * 6))
PERSIST_POPULATION = (os.environ.get("OPTIMIZER_PERSIST_POP") or "1").strip().lower() in ("1", "true", "yes", "on")

# ----- (4) paralellik -----
# auto: ilk gercek is parcasinda havuz denenir, hata olursa in-process'e duser. 1: zorla. 0: kapali.
PROCESS_POOL_MODE = (os.environ.get("OPTIMIZER_PROCESS_POOL") or "auto").strip().lower()

SOURCE_POOL = ["hammer", "sniper", "fr", "m1_a", "hammer+sniper", "sniper+fr", "hammer+sniper+fr", "hammer+sniper+fr+m1_a", "all"]
EMA_RULE_KEYS = ["rule_23_ema_cross_5m", "rule_24_ema_cross_15m"]
EMA_UNLOCK_GEN = max(1, _env_int("OPTIMIZER_EMA_UNLOCK_GEN", 3))
ATR_TF_POOL = ["5", "15", "60"]
JUNK_MIN_TRADES = max(1, _env_int("OPTIMIZER_JUNK_MIN_TRADES", 20))

STATUS_KEY = "optimizer_status"
CONTROL_KEY = "optimizer_control"
LOG_KEY = "optimizer_log"
POP_KEY = "optimizer_population"
STATUS_STALE_MS = 20_000


@dataclass
class Genome:
    name: str
    enabledRules: list
    longMinScore: float
    shortMinScore: float
    tpPercent: float
    slPercent: float
    leverage: int
    positionSizePct: float
    maxPositions: int
    signalSource: str
    useAtr: bool
    tpAtrMult: float
    slAtrMult: float
    atrTimeframe: str
    hourStart: int
    hourEnd: int
    allowedDays: list = field(default_factory=list)


@dataclass
class EvalResult(Genome):
    trades: int = 0
    wins: int = 0
    losses: int = 0
    totalPnl: float = 0.0
    winRate: float = 0.0
    profitFactor: float = 0.0
    sharpe: float = 0.0
    maxDrawdown: float = 0.0
    calmar: float = 0.0
    fitness: float = 0.0


# ----- mutable module state -----
running = False
generation = 1
population: list = []
idx = 0
evaluated = 0
current_name = ""
best_calmar = 0.0
loop_active = False
_optimizer_loop_task: asyncio.Task | None = None
_log_ring: list = []
# Memoization: (config_hash, fold_idx) -> fold metrikleri. Pencere kosu boyunca sabit
# oldugundan ayni config + fold her zaman ayni metrigi verir. loop() pencereyi yeniden
# sabitlerken temizlenir.
metrics_cache: dict = {}

# ProcessPool durumu
_pool = None
_pool_disabled = False


# ====================== app_config yardimcilari ======================
def write_app_config(key: str, value: str) -> None:
    try:
        execute(
            "INSERT INTO app_config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')",
            (key, value),
        )
    except Exception:  # noqa: BLE001
        pass


def read_app_config(key: str):
    try:
        r = query_one("SELECT value FROM app_config WHERE key = ?", (key,))
        return r["value"] if r else None
    except Exception:  # noqa: BLE001
        return None


def live_status() -> dict:
    return {
        "running": running, "generation": generation, "evaluated": evaluated, "currentName": current_name,
        "bestCalmar": _round2(best_calmar), "populationSize": len(population), "index": idx, "backtestDays": BACKTEST_DAYS,
    }


def persist_status() -> None:
    write_app_config(STATUS_KEY, json.dumps({**live_status(), "ts": _now_ms(), "pid": os.getpid()}))


def _iso_now() -> str:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def emit_log(level: str, message: str) -> None:
    log.info(message)
    entry = {"level": level, "message": message, "time": _iso_now()}
    event_bus.emit("optimizer:log", entry)
    _log_ring.append(entry)
    if len(_log_ring) > 60:
        _log_ring.pop(0)
    write_app_config(LOG_KEY, json.dumps(_log_ring))


# ====================== RNG / kural yardimcilari ======================
def rnd(lo: float, hi: float) -> float:
    return lo + random.random() * (hi - lo)


def pick(arr):
    return arr[math.floor(random.random() * len(arr))]


def all_keys() -> list:
    return get_all_rule_keys()


def clamp_rules(keys: list) -> list:
    valid = set(all_keys())
    out = list(dict.fromkeys(k for k in keys if k in valid))
    return out if len(out) > 0 else all_keys()[:6]


def pick_rule_for_gen(gen: int) -> str:
    keys = all_keys()
    ema_unlocked = gen >= EMA_UNLOCK_GEN and random.random() < min(0.6, 0.15 * (gen - EMA_UNLOCK_GEN + 1))
    pool = keys if ema_unlocked else [k for k in keys if k not in EMA_RULE_KEYS]
    return pick(pool if len(pool) else keys)


def mutate_time(base) -> dict:
    hour_start = base.hourStart
    hour_end = base.hourEnd
    allowed_days = list(base.allowedDays)
    if random.random() < 0.3:
        if hour_start < 0:
            hour_start = math.floor(rnd(0, 24))
            hour_end = (hour_start + math.floor(rnd(4, 12))) % 24
        else:
            hour_start = -1
            hour_end = -1
    elif hour_start >= 0 and random.random() < 0.5:
        hour_start = (hour_start + (1 if random.random() > 0.5 else 23)) % 24
        hour_end = (hour_end + (1 if random.random() > 0.5 else 23)) % 24
    if random.random() < 0.25:
        if len(allowed_days):
            allowed_days = []
        else:
            allowed_days = [1, 2, 3, 4, 5] if random.random() > 0.5 else [0, 6]
    return {"hourStart": hour_start, "hourEnd": hour_end, "allowedDays": allowed_days}


def no_time() -> dict:
    return {"hourStart": -1, "hourEnd": -1, "allowedDays": []}


def no_atr() -> dict:
    return {"useAtr": False, "tpAtrMult": 0, "slAtrMult": 0, "atrTimeframe": "15"}


# ====================== (1) WALK-FORWARD pencereleri ======================
def build_folds(start_ms: int, end_ms: int) -> list:
    """Pencereyi WF_FOLDS kat'a boler; aralarina embargo (purge) bosulugu koyar.

    Donen: [(fold_start_ms, fold_end_ms), ...]. WF_FOLDS=1 ise tek pencere (eski davranis).
    """
    if WF_FOLDS <= 1:
        return [(start_ms, end_ms)]
    embargo = int(WF_EMBARGO_DAYS * 86_400_000)
    total = end_ms - start_ms
    inner = total - embargo * (WF_FOLDS - 1)
    if inner <= 0:
        embargo = 0
        inner = total
    seg = inner // WF_FOLDS
    folds = []
    cursor = start_ms
    for i in range(WF_FOLDS):
        fs = cursor
        fe = fs + seg if i < WF_FOLDS - 1 else end_ms
        folds.append((int(fs), int(fe)))
        cursor = fe + embargo
    return folds


# ====================== (2) saglamlastirilmis kalite/fitness ======================
def fold_quality(m: dict) -> tuple:
    """Tek fold metrigi -> (kalite, gecerli_mi).

    - calmar=99 / maxDD=0 artifakti DD_FLOOR ile etkisizlestirilir, CALMAR_CAP ile sinirlanir.
    - kalite = CALMAR_W*calmar + SHARPE_W*sharpe; PF<1 ise yumusak ceza.
    - islem sayisi guven carpani (conf=T/(T+K)) ile coklu-test sismesi bastirilir.
    """
    trades = int(m.get("trades") or 0)
    if trades < MIN_FOLD_TRADES:
        return (0.0, False)
    pnl_pct = float(m.get("totalPnlPct") or 0.0)
    dd = max(float(m.get("maxDrawdown") or 0.0), DD_FLOOR)
    calmar = _clamp(pnl_pct / dd, -CALMAR_CAP, CALMAR_CAP)
    sharpe = _clamp(float(m.get("sharpe") or 0.0), -CALMAR_CAP, CALMAR_CAP)
    pf = float(m.get("profitFactor") or 0.0)
    base = CALMAR_W * calmar + SHARPE_W * sharpe
    if pf < 1:
        base -= PF_GATE_PENALTY
    conf = trades / (trades + TRADE_CONF_K) if (trades + TRADE_CONF_K) > 0 else 1.0
    return (base * conf, True)


def _mean(xs: list) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: list) -> float:
    if len(xs) < 2:
        return 0.0
    mu = _mean(xs)
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / len(xs))


def aggregate_folds(fold_metrics: list, g) -> tuple:
    """Fold metrik listesi -> (combined_display_metrics, wf_detail, fitness).

    fitness = (gecerli fold kaliteleri ortalamasi - lambda*std) * kaldirac_cezasi.
    Yeterli sayida gecerli fold yoksa -1 (reddedilir).
    """
    qualities = []
    valid_flags = []
    for m in fold_metrics:
        q, ok = fold_quality(m)
        valid_flags.append(ok)
        if ok:
            qualities.append(q)

    valid_count = sum(1 for v in valid_flags if v)
    n_folds = max(1, len(fold_metrics))

    # ----- birlesik (ekran) metrikleri: fold toplamlari -----
    trades = sum(int(m.get("trades") or 0) for m in fold_metrics)
    wins = sum(int(m.get("wins") or 0) for m in fold_metrics)
    losses = sum(int(m.get("losses") or 0) for m in fold_metrics)
    total_pnl = sum(float(m.get("totalPnl") or 0.0) for m in fold_metrics)
    max_dd = max([float(m.get("maxDrawdown") or 0.0) for m in fold_metrics] or [0.0])
    win_rate = (wins / trades * 100) if trades > 0 else 0.0

    def _wmean(key, cap):
        num = 0.0
        den = 0
        for m in fold_metrics:
            t = int(m.get("trades") or 0)
            if t <= 0:
                continue
            num += min(float(m.get(key) or 0.0), cap) * t
            den += t
        return (num / den) if den else 0.0

    profit_factor = _wmean("profitFactor", 99.0)
    sharpe = _wmean("sharpe", CALMAR_CAP)

    fold_calmars = []
    for m in fold_metrics:
        if int(m.get("trades") or 0) < MIN_FOLD_TRADES:
            continue
        dd = max(float(m.get("maxDrawdown") or 0.0), DD_FLOOR)
        fold_calmars.append(_clamp(float(m.get("totalPnlPct") or 0.0) / dd, -CALMAR_CAP, CALMAR_CAP))
    calmar = _round2(_mean(fold_calmars)) if fold_calmars else 0.0

    combined = {
        "trades": trades, "wins": wins, "losses": losses,
        "totalPnl": _round2(total_pnl), "winRate": _round2(win_rate),
        "profitFactor": _round2(profit_factor), "sharpe": _round2(sharpe),
        "maxDrawdown": _round2(max_dd), "calmar": calmar,
    }

    # ----- fitness -----
    if valid_count == 0 or valid_count / n_folds < MIN_VALID_FOLDS_FRAC:
        fitness = -1.0
    else:
        mean_q = _mean(qualities)
        std_q = _std(qualities)
        robust = mean_q - ROBUST_LAMBDA * std_q
        if robust > 0:
            lev = max(1.0, float(getattr(g, "leverage", 1) or 1))
            lev_penalty = 1 / (1 + FIT_LEV_COEFF * max(0.0, lev - FIT_LEV_FREE))
            robust *= lev_penalty
        fitness = robust

    wf_detail = {
        "folds": n_folds,
        "validFolds": valid_count,
        "robustFitness": _round2(fitness),
        "foldCalmar": [_round2(c) for c in fold_calmars],
        "meanQuality": _round2(_mean(qualities)),
        "stdQuality": _round2(_std(qualities)),
        "embargoDays": WF_EMBARGO_DAYS,
    }
    return combined, wf_detail, fitness


# Geriye donuk uyumluluk: tek metrik sozlugunden fitness (DB'den okunan eski satirlar icin).
def compute_fitness(m: dict, g) -> float:
    _, _, fit = aggregate_folds([m], g)
    return fit


# ====================== seed / genom uretimi ======================
def seed_population() -> list:
    all_ = [k for k in all_keys() if k not in EMA_RULE_KEYS]
    base = {**no_atr(), **no_time()}
    seeds = [
        Genome(name="MeanReversion_RSI", enabledRules=clamp_rules(["rule_01_extreme_rsi", "rule_04_stochrsi_extreme", "rule_08_all_rsi_extreme", "rule_06_tf_divergence", "rule_14_rsi_divergence", "rule_13_conviction"]), longMinScore=2, shortMinScore=-2, tpPercent=3, slPercent=1.5, leverage=2, positionSizePct=3, maxPositions=3, signalSource="hammer+sniper", **base),
        Genome(name="Momentum_Breakout", enabledRules=clamp_rules(["rule_05_volume", "rule_07_multi_tf", "rule_02_h1_trend", "rule_09_pump_dump", "rule_12_anti_chase", "rule_13_conviction"]), longMinScore=2, shortMinScore=-2, tpPercent=5, slPercent=2, leverage=3, positionSizePct=4, maxPositions=2, signalSource="hammer+sniper+fr", **base),
        Genome(name="FR_Arbitrage", enabledRules=clamp_rules(["rule_10_funding_rate", "rule_15_neg_fr_momentum", "rule_18_fr_extreme_guard", "rule_25_fr_squeeze_setup", "rule_13_conviction"]), longMinScore=1.5, shortMinScore=-1.5, tpPercent=4, slPercent=2, leverage=2, positionSizePct=3, maxPositions=3, signalSource="fr", **base),
        Genome(name="ADX_Trend_ATR", enabledRules=clamp_rules(["rule_26_adx_trend", "rule_02_h1_trend", "rule_07_multi_tf", "rule_12_anti_chase", "rule_13_conviction"]), longMinScore=2, shortMinScore=-2, tpPercent=4, slPercent=2, leverage=3, positionSizePct=3, maxPositions=3, signalSource="hammer+sniper+fr", **no_time(), useAtr=True, tpAtrMult=2.5, slAtrMult=1.5, atrTimeframe="15"),
        Genome(name="ATR_Breakout", enabledRules=clamp_rules(["rule_27_atr_breakout", "rule_26_adx_trend", "rule_05_volume", "rule_13_conviction"]), longMinScore=2, shortMinScore=-2, tpPercent=5, slPercent=2.5, leverage=3, positionSizePct=3, maxPositions=3, signalSource="hammer+sniper", **no_time(), useAtr=True, tpAtrMult=3, slAtrMult=1.5, atrTimeframe="15"),
        Genome(name="ADX_TimeWindow", enabledRules=clamp_rules(["rule_26_adx_trend", "rule_19_rsi_direction_filter", "rule_13_conviction"]), longMinScore=1.5, shortMinScore=-1.5, tpPercent=4, slPercent=2, leverage=3, positionSizePct=3, maxPositions=3, signalSource="hammer+sniper+fr", **no_atr(), hourStart=2, hourEnd=16, allowedDays=[1, 2, 3, 4, 5]),
        Genome(name="AllRules_Balanced", enabledRules=all_, longMinScore=3, shortMinScore=-3, tpPercent=4, slPercent=2, leverage=3, positionSizePct=3, maxPositions=4, signalSource="all", **base),
        Genome(name="Sniper_Tight", enabledRules=clamp_rules(["rule_01_extreme_rsi", "rule_19_rsi_direction_filter", "rule_20_boost_value_filter", "rule_07_multi_tf", "rule_13_conviction"]), longMinScore=2.5, shortMinScore=-2.5, tpPercent=3, slPercent=1.5, leverage=3, positionSizePct=3, maxPositions=3, signalSource="sniper", **base),
        Genome(name="Wide_RR", enabledRules=all_, longMinScore=3, shortMinScore=-3, tpPercent=8, slPercent=3, leverage=2, positionSizePct=3, maxPositions=3, signalSource="all", **base),
    ]
    return seeds[:POP_SIZE]


def random_genome(gen: int) -> Genome:
    """(3) Cesitlilik gocmeni: arama uzayindan tamamen rastgele birey."""
    keys = [k for k in all_keys() if k not in EMA_RULE_KEYS or gen >= EMA_UNLOCK_GEN]
    if not keys:
        keys = all_keys()
    n_rules = math.floor(rnd(3, min(9, len(keys) + 1)))
    rules = clamp_rules(random.sample(keys, min(max(1, n_rules), len(keys))))
    use_atr = random.random() < 0.5
    score = round(rnd(1.0, 4.0), 2)
    time_ = no_time() if random.random() < 0.6 else {
        "hourStart": math.floor(rnd(0, 24)), "hourEnd": math.floor(rnd(0, 24)),
        "allowedDays": [] if random.random() < 0.5 else ([1, 2, 3, 4, 5] if random.random() > 0.5 else [0, 6]),
    }
    return Genome(
        name=f"Immigrant_G{gen}_{math.floor(random.random() * 1000)}",
        enabledRules=rules,
        longMinScore=score, shortMinScore=-score,
        tpPercent=round(rnd(2, 8), 2), slPercent=round(rnd(1, 4), 2),
        leverage=math.floor(rnd(1, 6)), positionSizePct=round(rnd(2, 6), 2),
        maxPositions=math.floor(rnd(2, 6)), signalSource=pick(SOURCE_POOL),
        useAtr=use_atr, tpAtrMult=round(rnd(1.5, 4), 2) if use_atr else 0,
        slAtrMult=round(rnd(1, 2.5), 2) if use_atr else 0, atrTimeframe=pick(ATR_TF_POOL),
        **time_,
    )


# ====================== DB'den ureme havuzu ======================
def _row_to_eval(r) -> EvalResult:
    try:
        cfg = json.loads(r["config_json"] or "{}")
    except Exception:  # noqa: BLE001
        cfg = {}
    wf = cfg.get("_wf") if isinstance(cfg.get("_wf"), dict) else {}
    lev = cfg.get("leverage", 3)
    ev = EvalResult(
        name=r["strategy_name"], enabledRules=cfg.get("enabledRules", []), longMinScore=cfg.get("longMinScore", 2),
        shortMinScore=cfg.get("shortMinScore", -2), tpPercent=cfg.get("tpPercent", 4), slPercent=cfg.get("slPercent", 2),
        leverage=lev, positionSizePct=cfg.get("positionSizePct", 3), maxPositions=cfg.get("maxPositions", 3),
        signalSource=cfg.get("signalSource", "all"),
        useAtr=bool(cfg.get("tpAtrMult")) or bool(cfg.get("slAtrMult")), tpAtrMult=cfg.get("tpAtrMult", 0),
        slAtrMult=cfg.get("slAtrMult", 0), atrTimeframe=cfg.get("atrTimeframe", "15"),
        hourStart=cfg.get("hourStart", -1), hourEnd=cfg.get("hourEnd", -1),
        allowedDays=cfg.get("allowedDays") if isinstance(cfg.get("allowedDays"), list) else [],
        trades=r["trades"], wins=r["wins"], losses=r["losses"], totalPnl=r["total_pnl"], winRate=r["win_rate"],
        profitFactor=r["profit_factor"], sharpe=r["sharpe_estimate"], maxDrawdown=r["max_drawdown"], calmar=r["calmar"],
    )
    if "robustFitness" in wf:
        ev.fitness = float(wf.get("robustFitness") or -1)
    else:
        ev.fitness = compute_fitness(
            {"trades": r["trades"], "profitFactor": r["profit_factor"], "calmar": r["calmar"],
             "maxDrawdown": r["max_drawdown"], "sharpe": r["sharpe_estimate"],
             "totalPnlPct": (float(r["calmar"]) * float(r["max_drawdown"])) if r["max_drawdown"] else 0.0},
            ev,
        )
    return ev


def get_breeding_pool(limit: int = BREED_POOL) -> list:
    """(2)(3) Junk elenmis, robustFitness'a gore siralanmis ureme havuzu."""
    rows = query_all(
        "SELECT strategy_name, config_json, trades, wins, losses, total_pnl, win_rate, profit_factor, "
        "sharpe_estimate, max_drawdown, calmar FROM optimizer_results "
        "WHERE backtest_days = ? AND trades >= ? AND max_drawdown > ? "
        "ORDER BY calmar DESC LIMIT ?",
        (BACKTEST_DAYS, JUNK_MIN_TRADES, DD_FLOOR, limit),
    )
    evals = [_row_to_eval(r) for r in rows]
    # SQL filtresini Python tarafinda da uygula (savunma-derinligi): junk hicbir kosulda girmesin.
    evals = [e for e in evals if e.trades >= JUNK_MIN_TRADES and e.maxDrawdown > DD_FLOOR and e.fitness > -1]
    evals.sort(key=lambda e: e.fitness, reverse=True)
    return evals


# ====================== crossover / mutate / tournament ======================
def tournament(pool: list, k: int):
    if not pool:
        return None
    cand = [pick(pool) for _ in range(min(k, len(pool)))]
    return max(cand, key=lambda e: e.fitness)


def crossover(a, b, gen: int) -> Genome:
    rules = clamp_rules([k for k in dict.fromkeys([*a.enabledRules, *b.enabledRules]) if random.random() > 0.3])
    atr_parent = a if random.random() > 0.5 else b
    time_parent = a if random.random() > 0.5 else b
    return Genome(
        name=f"Evolved_G{gen}_{math.floor(random.random() * 1000)}",
        enabledRules=rules,
        longMinScore=(a.longMinScore + b.longMinScore) / 2,
        shortMinScore=(a.shortMinScore + b.shortMinScore) / 2,
        tpPercent=(a.tpPercent + b.tpPercent) / 2,
        slPercent=(a.slPercent + b.slPercent) / 2,
        leverage=_rh((a.leverage + b.leverage) / 2),
        positionSizePct=(a.positionSizePct + b.positionSizePct) / 2,
        maxPositions=_rh((a.maxPositions + b.maxPositions) / 2),
        signalSource=a.signalSource if random.random() > 0.5 else b.signalSource,
        useAtr=atr_parent.useAtr, tpAtrMult=atr_parent.tpAtrMult, slAtrMult=atr_parent.slAtrMult, atrTimeframe=atr_parent.atrTimeframe,
        hourStart=time_parent.hourStart, hourEnd=time_parent.hourEnd, allowedDays=list(time_parent.allowedDays),
    )


def mutate(base, gen: int) -> Genome:
    rules = list(base.enabledRules)
    if random.random() > 0.5 and len(rules) > 3:
        rules.pop(math.floor(random.random() * len(rules)))
    if random.random() > 0.5:
        rules.append(pick_rule_for_gen(gen))
    score = max(0.5, base.longMinScore * rnd(0.7, 1.3))

    use_atr = base.useAtr
    tp_atr_mult = base.tpAtrMult
    sl_atr_mult = base.slAtrMult
    atr_timeframe = base.atrTimeframe
    if random.random() < 0.25:
        use_atr = not use_atr
    if use_atr:
        if tp_atr_mult <= 0:
            tp_atr_mult = rnd(1.5, 4)
        if sl_atr_mult <= 0:
            sl_atr_mult = rnd(1, 2.5)
        tp_atr_mult = max(0.5, min(8, tp_atr_mult * rnd(0.7, 1.4)))
        sl_atr_mult = max(0.5, min(5, sl_atr_mult * rnd(0.7, 1.4)))
        if random.random() < 0.3:
            atr_timeframe = pick(ATR_TF_POOL)

    time_ = mutate_time(base)
    return Genome(
        name=f"Mutant_G{gen}_{math.floor(random.random() * 1000)}",
        enabledRules=clamp_rules(rules),
        longMinScore=score,
        shortMinScore=-score,
        tpPercent=max(1, base.tpPercent * rnd(0.7, 1.4)),
        slPercent=max(0.5, base.slPercent * rnd(0.7, 1.4)),
        leverage=max(1, min(10, base.leverage + (1 if random.random() > 0.5 else -1))),
        positionSizePct=max(1, min(10, base.positionSizePct * rnd(0.8, 1.2))),
        maxPositions=max(1, min(8, base.maxPositions + (1 if random.random() > 0.5 else -1))),
        signalSource=pick(SOURCE_POOL) if random.random() > 0.6 else base.signalSource,
        useAtr=use_atr, tpAtrMult=tp_atr_mult if use_atr else 0, slAtrMult=sl_atr_mult if use_atr else 0, atrTimeframe=atr_timeframe,
        **time_,
    )


def dedupe_genomes(genomes: list) -> list:
    seen = set()
    out = []
    for g in genomes:
        h = config_hash(g)
        if h in seen:
            continue
        seen.add(h)
        out.append(g)
    return out


def breed() -> list:
    """(3) Turnuva secimi + elit + rastgele gocmen; config_hash ile tekillestir."""
    pool = get_breeding_pool(BREED_POOL)
    if len(pool) < 2:
        return seed_population()
    elites = pool[:min(ELITE_COUNT, len(pool))]
    nxt = [replace(e, name=f"Elite_G{generation}_{e.name[:10]}") for e in elites]

    n_immigrants = _rh(IMMIGRANT_FRAC * POP_SIZE)
    target_total_bred = max(0, POP_SIZE - len(nxt) - n_immigrants)

    bred = 0
    guard = 0
    while bred < target_total_bred and guard < target_total_bred * 8 + 20:
        guard += 1
        if random.random() > 0.5 and len(pool) >= 2:
            a = tournament(pool, TOURNAMENT_K)
            b = tournament(pool, TOURNAMENT_K)
            child = crossover(a, b, generation)
        else:
            child = mutate(tournament(pool, TOURNAMENT_K), generation)
        nxt.append(child)
        bred += 1

    for _ in range(n_immigrants):
        nxt.append(random_genome(generation))

    nxt = dedupe_genomes(nxt)
    guard = 0
    while len(nxt) < POP_SIZE and guard < POP_SIZE * 8 + 20:
        guard += 1
        nxt = dedupe_genomes(nxt + [random_genome(generation)])
    return nxt[:POP_SIZE]


# ====================== config / hash / kayit ======================
def to_strategy_config(g) -> dict:
    cfg = {
        "enabledRules": g.enabledRules,
        "longMinScore": g.longMinScore,
        "shortMinScore": g.shortMinScore,
        "tpPercent": g.tpPercent,
        "slPercent": g.slPercent,
        "leverage": g.leverage,
        "positionSizePct": g.positionSizePct,
        "maxPositions": g.maxPositions,
        "signalSource": g.signalSource,
    }
    if g.useAtr and (g.tpAtrMult > 0 or g.slAtrMult > 0):
        cfg["tpAtrMult"] = _round2(g.tpAtrMult)
        cfg["slAtrMult"] = _round2(g.slAtrMult)
        cfg["atrTimeframe"] = g.atrTimeframe
    if g.hourStart >= 0 and g.hourEnd >= 0:
        cfg["hourStart"] = g.hourStart
        cfg["hourEnd"] = g.hourEnd
    if 0 < len(g.allowedDays) < 7:
        cfg["allowedDays"] = g.allowedDays
    return cfg


def config_hash(g) -> str:
    c = dict(to_strategy_config(g))
    if isinstance(c.get("enabledRules"), list):
        c["enabledRules"] = sorted(c["enabledRules"])
    if isinstance(c.get("allowedDays"), list):
        c["allowedDays"] = sorted(c["allowedDays"])
    return json.dumps(c, sort_keys=True)


def save_result(g, ev, wf_detail: dict) -> None:
    cfg = to_strategy_config(g)
    cfg["_wf"] = wf_detail  # robustluk detayi; deploy/apply bunu yok sayar
    execute(
        "INSERT INTO optimizer_results (strategy_name, config_json, trades, wins, losses, total_pnl, win_rate, avg_pnl, profit_factor, sharpe_estimate, avg_win, avg_loss, generation, max_drawdown, calmar, backtest_days) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?)",
        (
            g.name, json.dumps(cfg), ev.trades, ev.wins, ev.losses, ev.totalPnl, ev.winRate,
            (ev.totalPnl / ev.trades if ev.trades > 0 else 0), ev.profitFactor, ev.sharpe, generation, ev.maxDrawdown, ev.calmar, BACKTEST_DAYS,
        ),
    )


def insight(message: str, type_: str = "info") -> None:
    execute(
        "INSERT INTO optimizer_insights (strategy_name, message, type) VALUES (?, ?, ?)",
        (current_name or "optimizer", message, type_),
    )


def record_result(g, combined: dict, wf_detail: dict, fitness: float) -> None:
    global evaluated, best_calmar
    ev = EvalResult(
        **{f.name: getattr(g, f.name) for f in Genome.__dataclass_fields__.values()},
        trades=combined["trades"], wins=combined["wins"], losses=combined["losses"], totalPnl=combined["totalPnl"],
        winRate=combined["winRate"], profitFactor=combined["profitFactor"], sharpe=combined["sharpe"],
        maxDrawdown=combined["maxDrawdown"], calmar=combined["calmar"], fitness=fitness,
    )
    save_result(g, ev, wf_detail)
    evaluated += 1
    if combined["calmar"] > best_calmar and combined["trades"] >= MIN_TRADES and fitness > 0:
        best_calmar = combined["calmar"]
        insight(
            f"Yeni en iyi: {g.name} robFit={fitness:.2f} Calmar={combined['calmar']:.2f} "
            f"PnL={combined['totalPnl']:.0f} DD={combined['maxDrawdown']:.1f}% WR={combined['winRate']:.0f}% "
            f"({combined['trades']} islem, {wf_detail['validFolds']}/{wf_detail['folds']} fold)",
            "success",
        )
    emit_log("info", f"{g.name}: robFit={fitness:.2f} Calmar={combined['calmar']:.2f} PnL={combined['totalPnl']:.0f} "
                     f"DD={combined['maxDrawdown']:.1f}% WR={combined['winRate']:.0f}% T={combined['trades']} "
                     f"({wf_detail['validFolds']}/{wf_detail['folds']}f)")
    persist_status()


# Cikis bir sonraki bar acilisinda dolar (canli monitor: intrabar tespit + market-close).
# Backtest sonuclarini canliya sadik yapar; "ayni-barda-level'de cikma" iyimserligini giderir.
NEXT_BAR_EXIT = (os.environ.get("OPTIMIZER_NEXT_BAR_EXIT") or "1").strip().lower() in ("1", "true", "yes", "on")


def _params_for(g, start_ms: int, end_ms: int) -> dict:
    cfg = to_strategy_config(g)
    if NEXT_BAR_EXIT:
        cfg["_nextBarExit"] = True
        cfg["_nextBarEntry"] = True
        cfg["_reentryGapBars"] = 1
    return {
        "strategyConfig": cfg,
        "startMs": start_ms,
        "endMs": end_ms,
        "maxSignals": MAX_SIGNALS,
        "maxSymbols": MAX_SYMBOLS,
        "minInterval": OPTIMIZER_MIN_INTERVAL,
    }


# ====================== (4) ProcessPool altyapisi ======================
def _pool_init():
    # spawn ile cocuk taze baslar; yine de kalitsal DB handle'i sifirla ve heap cache'i ac.
    try:
        from ..db import database as _dbmod
        _dbmod._db = None
    except Exception:  # noqa: BLE001
        pass
    try:
        configure_kline_heap_cache(WORKER_HEAP_MAX_BARS)
        enable_kline_heap_cache()
    except Exception:  # noqa: BLE001
        pass


def _bt_metrics_worker(params: dict) -> dict:
    """Ayri process'te calisir: tek backtest -> yalnizca metrik (kucuk, picklable)."""
    import asyncio as _aio
    from ..engines.backtest_engine import run_backtest as _rb
    res = _aio.run(_rb(params))
    return res["metrics"]


def _get_pool():
    global _pool
    if _pool is None:
        ctx = multiprocessing.get_context("spawn")
        _pool = concurrent.futures.ProcessPoolExecutor(max_workers=WORKER_COUNT, mp_context=ctx, initializer=_pool_init)
    return _pool


def _shutdown_pool():
    global _pool
    pool = _pool
    _pool = None
    if pool is not None:
        try:
            terminate_workers = getattr(pool, "terminate_workers", None)
            if callable(terminate_workers):
                terminate_workers()
            else:
                pool.shutdown(wait=True, cancel_futures=True)
        except Exception as err:  # noqa: BLE001
            log.warn(f"ProcessPool shutdown failed: {err}")


def _pool_enabled() -> bool:
    if _pool_disabled or WORKER_COUNT <= 1:
        return False
    return PROCESS_POOL_MODE in ("auto", "1", "true", "yes", "on")


async def _backtest_metrics(params: dict) -> dict:
    """Tek backtest -> metrik. Havuz aciksa process'te, degilse in-process calisir.

    Havuzda hata olursa havuzu kalici kapatir ve in-process'e duser (forward progress).
    """
    global _pool_disabled
    if _pool_enabled():
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(_get_pool(), _bt_metrics_worker, params)
        except Exception as err:  # noqa: BLE001
            _pool_disabled = True
            _shutdown_pool()
            emit_log("warn", f"ProcessPool devre disi (in-process'e dusuldu): {err}")
    res = await run_backtest(params)
    return res["metrics"]


# ====================== degerlendirme dongusu ======================
async def warm_fold_cache(g0, folds: list) -> dict:
    """Gen-1: ilk genomu her fold'da seri (in-process) calistirarak SQLite kline/funding
    cache'ini doldur. Boylece sonraki paralel is parcalari (process'ler) diskten okur.
    """
    out = {}
    for fi, (fs, fe) in enumerate(folds):
        if not running:
            break
        res = await run_backtest(_params_for(g0, fs, fe))
        out[fi] = res["metrics"]
        metrics_cache[(config_hash(g0), fi)] = res["metrics"]
    return out


async def eval_genome(g, folds: list, prewarmed=None) -> None:
    fold_metrics = []
    for fi, (fs, fe) in enumerate(folds):
        if not running:
            return
        key = (config_hash(g), fi)
        if prewarmed is not None and fi in prewarmed:
            m = prewarmed[fi]
        elif key in metrics_cache:
            m = metrics_cache[key]
        else:
            try:
                m = await _backtest_metrics(_params_for(g, fs, fe))
            except Exception as err:  # noqa: BLE001
                emit_log("error", f"{g.name} fold{fi} backtest hatasi: {err}")
                m = {"trades": 0, "wins": 0, "losses": 0, "totalPnl": 0, "totalPnlPct": 0,
                     "winRate": 0, "profitFactor": 0, "sharpe": 0, "maxDrawdown": 0, "calmar": 0}
            metrics_cache[key] = m
        fold_metrics.append(m)
    combined, wf_detail, fitness = aggregate_folds(fold_metrics, g)
    record_result(g, combined, wf_detail, fitness)


async def evaluate_generation(genomes: list, folds: list) -> None:
    global current_name, idx
    if not genomes:
        return

    start = 0
    if generation == 1 and running:
        g0 = genomes[0]
        current_name = g0.name
        idx = 0
        event_bus.emit("optimizer:progress", {"generation": generation, "index": 0, "total": len(genomes), "name": g0.name})
        prewarmed0 = await warm_fold_cache(g0, folds)
        await eval_genome(g0, folds, prewarmed=prewarmed0)
        start = 1

    sem = asyncio.Semaphore(WORKER_COUNT)

    async def run_slot(i: int, g) -> None:
        global current_name, idx
        if not running:
            return
        async with sem:
            if not running:
                return
            current_name = g.name
            idx = i
            event_bus.emit("optimizer:progress", {"generation": generation, "index": i, "total": len(genomes), "name": g.name})
            await eval_genome(g, folds)

    await asyncio.gather(*[run_slot(i, genomes[i]) for i in range(start, len(genomes))])


# ====================== popülasyon kaliciligi (3) ======================
def _genome_to_dict(g) -> dict:
    return {f.name: getattr(g, f.name) for f in Genome.__dataclass_fields__.values()}


def persist_population() -> None:
    if not PERSIST_POPULATION:
        return
    try:
        write_app_config(POP_KEY, json.dumps({
            "generation": generation,
            "backtestDays": BACKTEST_DAYS,
            "genomes": [_genome_to_dict(g) for g in population],
        }))
    except Exception:  # noqa: BLE001
        pass


def load_population() -> bool:
    global population, generation
    if not PERSIST_POPULATION:
        return False
    raw = read_app_config(POP_KEY)
    if not raw:
        return False
    try:
        data = json.loads(raw)
        if data.get("backtestDays") != BACKTEST_DAYS:
            return False
        gs = data.get("genomes") or []
        valid_fields = set(Genome.__dataclass_fields__.keys())
        rebuilt = [Genome(**{k: v for k, v in d.items() if k in valid_fields}) for d in gs]
        if len(rebuilt) >= 2:
            population = rebuilt[:POP_SIZE]
            generation = max(1, int(data.get("generation") or 1))
            return True
    except Exception:  # noqa: BLE001
        return False
    return False


# ====================== ana dongu ======================
def _day(ms: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


async def loop() -> None:
    global loop_active, generation, population, running
    if loop_active:
        return
    loop_active = True
    window_end_ms = _now_ms()
    window_start_ms = window_end_ms - BACKTEST_DAYS * 86_400_000
    folds = build_folds(window_start_ms, window_end_ms)
    metrics_cache.clear()
    fold_desc = " | ".join(f"{_day(fs)}->{_day(fe)}" for fs, fe in folds)
    emit_log("info", f"Pencere {BACKTEST_DAYS}g, {len(folds)} fold (embargo {WF_EMBARGO_DAYS}g): {fold_desc}")
    if _pool_enabled():
        emit_log("info", f"ProcessPool: {WORKER_COUNT} worker (mod={PROCESS_POOL_MODE}).")
    try:
        while running:
            emit_log("info", f"Gen {generation} basladi ({len(population)} birey, {WORKER_COUNT} worker, {len(folds)} fold).")
            await evaluate_generation(population, folds)
            if not running:
                break
            emit_log("info", f"Gen {generation} tamamlandi.")
            event_bus.emit("optimizer:cycle-complete", {"generation": generation})
            generation += 1
            population = breed()
            persist_population()
            await asyncio.sleep(CYCLE_PAUSE_MS / 1000)
    finally:
        running = False
        loop_active = False
        _shutdown_pool()


def start_backtest_optimizer() -> None:
    global running, population, idx, _optimizer_loop_task
    if running:
        return
    if _optimizer_loop_task is not None and not _optimizer_loop_task.done():
        return
    running = True
    if len(population) == 0:
        if not load_population():
            population = seed_population()
        idx = 0
    emit_log("info", f"Backtest optimizer basladi (gen {generation}, {len(population)} birey, {BACKTEST_DAYS}g, "
                     f"{WF_FOLDS} fold).")
    persist_status()
    _optimizer_loop_task = asyncio.create_task(loop())


def stop_backtest_optimizer() -> None:
    global running
    running = False
    if _optimizer_loop_task is not None and not _optimizer_loop_task.done():
        _optimizer_loop_task.cancel()
    emit_log("info", "Backtest optimizer durduruldu.")
    persist_status()


async def wait_for_optimizer_shutdown() -> None:
    global _optimizer_loop_task
    task = _optimizer_loop_task
    if task is None:
        return
    await asyncio.gather(task, return_exceptions=True)
    if _optimizer_loop_task is task:
        _optimizer_loop_task = None


def request_optimizer_control(action: str) -> None:
    write_app_config(CONTROL_KEY, action)


def get_optimizer_status() -> dict:
    fallback = {"running": False, "generation": 1, "evaluated": 0, "currentName": "", "bestCalmar": 0, "populationSize": 0, "index": 0, "backtestDays": BACKTEST_DAYS}
    raw = read_app_config(STATUS_KEY)
    if not raw:
        return fallback
    try:
        s = json.loads(raw)
        stale = isinstance(s.get("ts"), (int, float)) and (_now_ms() - s["ts"] > STATUS_STALE_MS)
        return {
            "running": False if stale else bool(s.get("running")),
            "generation": s.get("generation", 1),
            "evaluated": s.get("evaluated", 0),
            "currentName": s.get("currentName", ""),
            "bestCalmar": s.get("bestCalmar", 0),
            "populationSize": s.get("populationSize", 0),
            "index": s.get("index", 0),
            "backtestDays": s.get("backtestDays", BACKTEST_DAYS),
        }
    except Exception:  # noqa: BLE001
        return fallback


def _result_conds(prefix: str, only_year: bool, hide_junk: bool) -> str:
    c = []
    if only_year:
        c.append(f"{prefix}backtest_days >= 365")
    if hide_junk:
        c.append(f"{prefix}max_drawdown > 0")
        c.append(f"{prefix}trades >= {JUNK_MIN_TRADES}")
    return "WHERE " + " AND ".join(c) if len(c) else ""


def get_optimizer_results(limit: int = 50, unique: bool = False, only_year: bool = False, hide_junk: bool = False) -> list:
    cols = ("r.id, r.strategy_name, r.config_json, r.trades, r.wins, r.losses, r.total_pnl, r.win_rate, "
            "r.profit_factor, r.sharpe_estimate, r.max_drawdown, r.calmar, r.generation, r.tested_at, r.backtest_days, "
            "r.deployed_account_id, a.id AS live_account_id, a.name AS live_account_name")
    if not unique:
        rows = query_all(
            f"SELECT {cols} FROM optimizer_results r LEFT JOIN accounts a ON a.id = r.deployed_account_id "
            f"{_result_conds('r.', only_year, hide_junk)} ORDER BY r.calmar DESC, r.total_pnl DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]
    rows = query_all(
        f"SELECT {cols} FROM optimizer_results r LEFT JOIN accounts a ON a.id = r.deployed_account_id "
        f"WHERE r.id IN ( SELECT id FROM ( "
        f"  SELECT id, ROW_NUMBER() OVER ( PARTITION BY trades, wins, losses, total_pnl, calmar, max_drawdown "
        f"    ORDER BY (deployed_account_id IS NOT NULL) DESC, generation ASC, id ASC ) AS rn "
        f"  FROM optimizer_results {_result_conds('', only_year, hide_junk)} ) WHERE rn = 1 ) "
        f"ORDER BY r.calmar DESC, r.total_pnl DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


def get_optimizer_insights(limit: int = 30) -> list:
    rows = query_all(
        "SELECT id, strategy_name, message, type, created_at FROM optimizer_insights ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


async def run_optimizer_standalone(auto_run: bool | None = None) -> None:
    configure_kline_heap_cache(WORKER_HEAP_MAX_BARS if _pool_enabled() else TOTAL_HEAP_MAX_BARS)
    enable_kline_heap_cache()
    emit_log("info", f"Optimizer poll dongusu basladi (pid {os.getpid()}).")
    if auto_run is None:
        auto_raw = (os.environ.get("AUTO_START_OPTIMIZER") or "true").strip().lower()
        auto_run = auto_raw in ("1", "true", "yes", "on")
    if read_app_config(CONTROL_KEY) is None:
        write_app_config(CONTROL_KEY, "run" if auto_run else "stop")

    def tick():
        flag = (read_app_config(CONTROL_KEY) or "run").strip()
        if flag == "run" and not running:
            start_backtest_optimizer()
        elif flag == "stop" and running:
            stop_backtest_optimizer()
        persist_status()

    tick()
    while True:
        await asyncio.sleep(3)
        tick()


def start_optimizer(auto_run: bool = False):
    configure_kline_heap_cache(WORKER_HEAP_MAX_BARS if _pool_enabled() else TOTAL_HEAP_MAX_BARS)
    enable_kline_heap_cache()
    return asyncio.create_task(run_optimizer_standalone(auto_run=auto_run))


def stop_optimizer() -> None:
    global running
    running = False
    write_app_config(CONTROL_KEY, "stop")
    stop_backtest_optimizer()
