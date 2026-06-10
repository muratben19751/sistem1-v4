"""Replica kural parametreleri icin mutable + kalici depo.

Replica modulleri (nw_sniper, replica_channels) esiklerini buradan okur.
Replica tuner ajani bu degerleri canli olarak ayarlar (4 kaynagi esitlemek icin).
Baslangic degerleri env'den gelir; tuner'in yazdiklari app_config'te (JSON) saklanir
ve restart'ta geri yuklenir.
"""
import json
import os

from ..core.logger import create_logger
from ..db.database import execute, query_one

log = create_logger("replica-params")

_CONFIG_KEY = "replica_tuned_params"


def _num_env(name: str, default: float, minimum: float) -> float:
    try:
        v = float(os.environ.get(name) or "")
    except ValueError:
        return default
    if v != v or v in (float("inf"), float("-inf")):
        return default
    return max(minimum, v)


# spec: (env_adi, varsayilan, alt_sinir, ust_sinir, adim, tighten_sign)
# tighten_sign: +1 => degeri ARTIRMAK sinyali AZALTIR (siki); -1 => degeri AZALTMAK sinyali azaltir
PARAM_SPECS: dict[str, tuple] = {
    "HAMMER_RSI_OB":    ("HAMMER_RSI_OB",    64.0,  55.0, 80.0, 1.0,   +1),
    "HAMMER_RSI_OS":    ("HAMMER_RSI_OS",    36.0,  20.0, 45.0, 1.0,   -1),
    "HAMMER_SRSI_OB":   ("HAMMER_SRSI_OB",   82.0,  60.0, 95.0, 1.0,   +1),
    "HAMMER_SRSI_OS":   ("HAMMER_SRSI_OS",   14.0,   5.0, 40.0, 1.0,   -1),
    "FR_THRESHOLD_PCT": ("FR_THRESHOLD_PCT",  0.08,  0.01, 0.5,  0.005, +1),
    "M1_MOVE_PCT":      ("M1_MOVE_PCT",       1.0,   0.3,  5.0,  0.05,  +1),
    "NW_SNIPER_RSI_OB":  ("NW_SNIPER_RSI_OB",  55.0, 50.0, 75.0, 1.0,   +1),
    "NW_SNIPER_RSI_OS":  ("NW_SNIPER_RSI_OS",  45.0, 25.0, 50.0, 1.0,   -1),
    "NW_SNIPER_SRSI_OB": ("NW_SNIPER_SRSI_OB", 48.0, 30.0, 80.0, 1.0,   +1),
    "NW_SNIPER_SRSI_OS": ("NW_SNIPER_SRSI_OS", 42.0, 10.0, 50.0, 1.0,   -1),
    "NW_SNIPER_POS_MIN": ("NW_SNIPER_POS_MIN", 0.3,  0.05, 0.9,  0.02,  +1),
}

# her kanalin tuner tarafindan ayarlanan parametreleri
CHANNEL_PARAMS: dict[str, list[str]] = {
    "hammer": ["HAMMER_RSI_OB", "HAMMER_RSI_OS", "HAMMER_SRSI_OB", "HAMMER_SRSI_OS"],
    "fr":     ["FR_THRESHOLD_PCT"],
    "m1_a":   ["M1_MOVE_PCT"],
    "sniper": ["NW_SNIPER_RSI_OB", "NW_SNIPER_RSI_OS", "NW_SNIPER_SRSI_OB", "NW_SNIPER_SRSI_OS", "NW_SNIPER_POS_MIN"],
}

_values: dict[str, float] = {}


def bounds(name: str) -> tuple[float, float, float]:
    """(min, max, step) dondurur."""
    _env, _d, lo, hi, step, _s = PARAM_SPECS[name]
    return lo, hi, step


def tighten_sign(name: str) -> int:
    return PARAM_SPECS[name][5]


def _clamp(name: str, value: float) -> float:
    lo, hi, _step = bounds(name)
    if value != value:  # NaN
        return PARAM_SPECS[name][1]
    return max(lo, min(hi, value))


def _load_persisted() -> dict[str, float]:
    try:
        r = query_one("SELECT value FROM app_config WHERE key = ?", (_CONFIG_KEY,))
        if not r:
            return {}
        data = json.loads(r["value"])
        return {k: float(v) for k, v in data.items() if k in PARAM_SPECS}
    except Exception:  # noqa: BLE001
        return {}


def _persist() -> None:
    try:
        execute(
            "INSERT INTO app_config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')",
            (_CONFIG_KEY, json.dumps(_values)),
        )
    except Exception:  # noqa: BLE001
        pass


def _ensure_loaded() -> None:
    if _values:
        return
    for name, (env, default, *_rest) in PARAM_SPECS.items():
        _values[name] = _clamp(name, _num_env(env, default, 0.0))
    persisted = _load_persisted()
    for name, v in persisted.items():
        _values[name] = _clamp(name, v)


def get(name: str) -> float:
    _ensure_loaded()
    return _values[name]


def set_value(name: str, value: float) -> float:
    """Deger atar (siniri uygular), kalici yazar, yeni degeri dondurur."""
    _ensure_loaded()
    clamped = _clamp(name, value)
    _values[name] = clamped
    _persist()
    return clamped


def adjust(name: str, steps: float) -> float:
    """Parametreyi `steps` adim kadar tasir (yon dahil), siniri uygular."""
    _ensure_loaded()
    _env, _d, _lo, _hi, step, _s = PARAM_SPECS[name]
    return set_value(name, _values[name] + steps * step)


def adjust_many(changes: dict[str, float]) -> dict[str, float]:
    """Apply several step changes and persist one coherent parameter snapshot."""
    _ensure_loaded()
    updated: dict[str, float] = {}
    for name, steps in changes.items():
        if name not in PARAM_SPECS:
            continue
        _env, _d, _lo, _hi, step, _s = PARAM_SPECS[name]
        _values[name] = _clamp(name, _values[name] + steps * step)
        updated[name] = _values[name]
    if updated:
        _persist()
    return updated


def reset() -> None:
    """Tum parametreleri env/varsayilan degerlere dondurur."""
    _values.clear()
    for name, (env, default, *_rest) in PARAM_SPECS.items():
        _values[name] = _clamp(name, _num_env(env, default, 0.0))
    _persist()
    log.info("Replica parametreleri varsayilana sifirlandi")


def snapshot() -> dict[str, float]:
    _ensure_loaded()
    return dict(_values)
