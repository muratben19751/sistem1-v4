import math

from ..lib.indicators import calc_rsi, calc_stoch_rsi, calc_volume_change, calc_atr  # noqa: F401
from ..strategies.rule_registry import get_rules
from ..strategies.rules.rule_interface import MarketData, RuleResult  # noqa: F401
from ..services.kline_cache import get_cached_klines
from ..services.funding_cache import get_cached_funding_at, get_cached_funding_history

TIMEFRAMES = ["1", "5", "15", "60", "240", "D"]

TF_RANK: dict[str, int] = {
    "1": 1, "3": 3, "5": 5, "15": 15, "30": 30, "60": 60,
    "120": 120, "240": 240, "D": 1440, "W": 10080,
}


def _round2(x: float) -> float:
    # Faithful to JS Math.round(x * 100) / 100 (round-half-up toward +inf).
    return math.floor(x * 100 + 0.5) / 100


def floor_interval(tf: str, min_interval: str = "1") -> str:
    mn = TF_RANK.get(min_interval, 1)
    return min_interval if TF_RANK.get(tf, 1) < mn else tf


# Mirror of strategy.py STATIC_RULE_TIMEFRAMES (keep in sync).
STATIC_RULE_TIMEFRAMES: dict[str, list[str]] = {
    "rule_01_extreme_rsi": ["1", "5"],
    "rule_02_h1_trend": ["60"],
    "rule_03_5m_rsi": ["5"],
    "rule_04_stochrsi_extreme": ["5", "15"],
    "rule_05_volume": ["60", "240", "D"],
    "rule_06_tf_divergence": ["5", "60"],
    "rule_07_multi_tf": ["5", "15", "60", "240"],
    "rule_08_all_rsi_extreme": ["1", "5", "15", "60"],
    "rule_09_pump_dump": ["5"],
    "rule_10_funding_rate": [],
    "rule_11_open_interest": ["60"],
    "rule_12_anti_chase": ["240"],
    "rule_13_conviction": [],
    "rule_14_rsi_divergence": ["240", "60", "D"],
    "rule_15_neg_fr_momentum": [],
    "rule_16_fr_settlement_timing": [],
    "rule_17_weekend_bonus": [],
    "rule_18_fr_extreme_guard": [],
    "rule_19_rsi_direction_filter": ["60"],
    "rule_20_boost_value_filter": [],
    "rule_21_utbot_5m": ["5"],
    "rule_22_rsi_drop_daily": ["D"],
    "rule_23_ema_cross_5m": ["5"],
    "rule_24_ema_cross_15m": ["15"],
    "rule_25_fr_squeeze_setup": [],
    "rule_26_adx_trend": ["60"],
    "rule_27_atr_breakout": ["15"],
}


def required_timeframes(enabled_rules: list[str] | None) -> list[str]:
    if enabled_rules is None:
        return TIMEFRAMES
    rules = get_rules(enabled_rules)
    if len(rules) == 0:
        return []
    req: set[str] = set()
    for r in rules:
        f = STATIC_RULE_TIMEFRAMES.get(r.key)
        if f is None:
            return TIMEFRAMES
        for tf in f:
            req.add(tf)
    return [t for t in TIMEFRAMES if t in req]


def _map_trigger_source(source_type: str) -> str | None:
    if source_type == "4s_sniper":
        return "sniper"
    if source_type in ("scanner", "sniper", "hammer", "fr", "m1_a", "v3_a"):
        return source_type
    return None


def analyze_symbol_historical(
    signal: dict,
    enabled_rules: list[str] | None,
    as_of_ms: int,
    weight_map: dict[str, float] | None = None,
    min_interval: str = "1",
) -> dict:
    rules = get_rules(enabled_rules)
    needed = required_timeframes(enabled_rules)
    klines: dict[str, list] = {}
    rsi: dict[str, float] = {}
    stoch_rsi: dict[str, dict] = {}
    tf_with_data = 0

    for tf in needed:
        data = get_cached_klines(signal["symbol"], floor_interval(tf, min_interval), as_of_ms, 200)
        if len(data) > 0:
            klines[tf] = data
            closes = [k.close for k in data]
            rsi[tf] = calc_rsi(closes)
            stoch_rsi[tf] = calc_stoch_rsi(closes)
            tf_with_data += 1

    exec_klines = klines["5"] if "5" in klines else get_cached_klines(signal["symbol"], "5", as_of_ms, 50)
    last_close = exec_klines[-1].close if len(exec_klines) > 0 else 0
    sig_price = signal.get("price")
    ref_price = sig_price if (sig_price and sig_price > 0) else last_close

    # Bybit funding cache (look-ahead korumali: yalnizca asOfMs ve oncesi).
    funding_hist = get_cached_funding_history(signal["symbol"], as_of_ms, 30)
    cached_fr = get_cached_funding_at(signal["symbol"], as_of_ms)
    funding_interval_hours = 8
    if len(funding_hist) >= 2:
        diff_ms = funding_hist[-1]["fundingRateTimestamp"] - funding_hist[-2]["fundingRateTimestamp"]
        h = math.floor(diff_ms / 3_600_000 + 0.5)
        if 1 <= h <= 24:
            funding_interval_hours = h

    md = MarketData(
        symbol=signal["symbol"],
        klines=klines,
        ticker={
            "symbol": signal["symbol"], "lastPrice": ref_price, "price24hPcnt": 0,
            "highPrice24h": 0, "lowPrice24h": 0, "volume24h": 0, "turnover24h": 0,
        },
        funding_rate=cached_fr if cached_fr is not None else (signal.get("fundingRate") or 0),
        open_interest=0,
        open_interest_change=0,
        rsi=rsi,
        stoch_rsi=stoch_rsi,
        volume_change=calc_volume_change(klines["5"]) if klines.get("5") else 0,
        funding_rate_history=funding_hist,
        funding_interval_hours=funding_interval_hours,
        trigger_source=_map_trigger_source(signal["sourceType"]),
        eval_ms=as_of_ms,  # zaman bazli kurallar (16/17/25) sinyal anini kullansin
        trigger_alert={
            "signalType": signal["signalType"],
            "direction": signal["direction"],
            "rawMessage": signal["rawMessage"],
            "rsiData": signal["rsiData"],
            "srsiData": signal["srsiData"],
            "boostValue": signal["boostValue"],
            "stars": signal["stars"],
        },
    )

    total = 0.0
    prior: list[RuleResult] = []
    for rule in rules:
        try:
            if rule.key == "rule_13_conviction":
                md.prior_results = prior
            res = rule.evaluate(md)
            w = weight_map.get(rule.key, 1.0) if weight_map else 1.0
            total += res.score * w
            if rule.key != "rule_13_conviction":
                prior.append(res)
        except Exception:  # noqa: BLE001  rule failure -> skip
            pass
    total = _round2(total)
    return {
        "totalScore": total,
        "side": "long" if total > 0 else "short" if total < 0 else "neutral",
        "refPrice": ref_price,
        "tfWithData": tf_with_data,
        "tfNeeded": len(needed),
    }
