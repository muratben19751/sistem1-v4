import asyncio
import math
from dataclasses import dataclass
from datetime import datetime, timezone

from ..core.logger import create_logger
from ..core.event_bus import event_bus
from ..services.bybit_api import get_klines, get_ticker, get_funding_rate_history, get_open_interest_change, to_finite
from ..lib.indicators import calc_rsi, calc_stoch_rsi, calc_volume_change, Kline
from ..strategies.rule_registry import get_rules
from ..strategies.rules.rule_interface import MarketData, TradingRule
from .learning import get_weights


def _round2(x: float) -> float:
    # JS Math.round paritesi (half-up, +inf'e dogru): backtest motoru (historical_strategy)
    # ile ayni; Python round() banker's rounding oldugundan yarim-cent sinirlarinda sapardi.
    return math.floor(x * 100 + 0.5) / 100

log = create_logger("strategy")


@dataclass
class SignalResult:
    symbol: str
    total_score: float
    side: str
    rules: list[dict]
    market_data: MarketData
    timestamp: str


TIMEFRAMES = [
    {"interval": "1", "key": "1"},
    {"interval": "5", "key": "5"},
    {"interval": "15", "key": "15"},
    {"interval": "60", "key": "60"},
    {"interval": "240", "key": "240"},
    {"interval": "D", "key": "D"},
]

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


def _required_timeframes(enabled_rules, rules: list[TradingRule]):
    if enabled_rules is None:
        return TIMEFRAMES
    if len(rules) == 0:
        return []
    required = set()
    for rule in rules:
        static_frames = STATIC_RULE_TIMEFRAMES.get(rule.key)
        if static_frames is not None:
            for tf in static_frames:
                required.add(tf)
            continue
        return TIMEFRAMES
    return [tf for tf in TIMEFRAMES if tf["key"] in required]


def _requires_funding_history(enabled_rules, rules: list[TradingRule]) -> bool:
    if enabled_rules is None:
        return True
    return any(r.key in ("rule_15_neg_fr_momentum", "rule_25_fr_squeeze_setup") for r in rules)


def _requires_oi_change(enabled_rules, rules: list[TradingRule]) -> bool:
    if enabled_rules is None:
        return True
    return any(r.key in ("rule_11_open_interest", "rule_25_fr_squeeze_setup") for r in rules)


def _to_klines(rows: list[dict]) -> list[Kline]:
    return [Kline(time=k["time"], open=k["open"], high=k["high"], low=k["low"], close=k["close"], volume=k["volume"]) for k in rows]


async def analyze_symbol(symbol: str, enabled_rules: list[str] | None = None,
                         account_id: int | None = None, trigger: dict | None = None) -> SignalResult:
    rules = get_rules(enabled_rules)
    required_timeframes = _required_timeframes(enabled_rules, rules)
    fetch_funding_history = _requires_funding_history(enabled_rules, rules)
    fetch_oi_change = _requires_oi_change(enabled_rules, rules)

    klines: dict[str, list[Kline]] = {}
    rsi_values: dict[str, float] = {}
    stoch_rsi_values: dict[str, dict] = {}

    async def fetch_tf(interval: str, key: str):
        try:
            data = await get_klines(symbol, interval, 200)
            kl = _to_klines(data)
            klines[key] = kl
            closes = [k.close for k in kl]
            rsi_values[key] = calc_rsi(closes)
            stoch_rsi_values[key] = calc_stoch_rsi(closes)
        except Exception as err:  # noqa: BLE001
            log.error(f"Failed to get {interval} klines for {symbol}: {err}")

    results = await asyncio.gather(
        get_ticker(symbol),
        get_funding_rate_history(symbol, 20) if fetch_funding_history else _async_value([]),
        get_open_interest_change(symbol, "1h") if fetch_oi_change else _async_value(0),
        *[fetch_tf(tf["interval"], tf["key"]) for tf in required_timeframes],
    )
    ticker_raw = results[0]
    fr_history = results[1]
    oi_change = results[2]

    funding_rate = to_finite(ticker_raw.get("fundingRate")) if ticker_raw else 0.0
    oi = to_finite(ticker_raw.get("openInterest")) if ticker_raw else 0.0

    if ticker_raw:
        ticker = {
            "symbol": ticker_raw["symbol"],
            "lastPrice": to_finite(ticker_raw.get("lastPrice")),
            "price24hPcnt": to_finite(ticker_raw.get("price24hPcnt")),
            "highPrice24h": to_finite(ticker_raw.get("highPrice24h")),
            "lowPrice24h": to_finite(ticker_raw.get("lowPrice24h")),
            "volume24h": to_finite(ticker_raw.get("volume24h")),
            "turnover24h": to_finite(ticker_raw.get("turnover24h")),
        }
    else:
        ticker = {"symbol": symbol, "lastPrice": 0, "price24hPcnt": 0, "highPrice24h": 0,
                  "lowPrice24h": 0, "volume24h": 0, "turnover24h": 0}

    volume_change = calc_volume_change(klines["5"]) if klines.get("5") else 0.0

    funding_interval_hours = 8
    if fr_history and len(fr_history) >= 2:
        srt = sorted(fr_history, key=lambda h: h["fundingRateTimestamp"], reverse=True)
        diff = srt[0]["fundingRateTimestamp"] - srt[1]["fundingRateTimestamp"]
        hours = math.floor(diff / (1000 * 60 * 60) + 0.5)
        if hours > 0:
            funding_interval_hours = hours

    market_data = MarketData(
        symbol=symbol,
        klines=klines,
        ticker=ticker,
        funding_rate=funding_rate,
        open_interest=oi,
        open_interest_change=oi_change or 0.0,
        rsi=rsi_values,
        stoch_rsi=stoch_rsi_values,
        volume_change=volume_change,
        funding_rate_history=[{"fundingRate": h["fundingRate"], "fundingRateTimestamp": h["fundingRateTimestamp"]} for h in (fr_history or [])],
        funding_interval_hours=funding_interval_hours,
        trigger_source=trigger.get("source") if trigger else None,
        trigger_alert=({
            "signalType": trigger.get("signalType"),
            "direction": trigger.get("direction"),
            "rawMessage": trigger.get("rawMessage"),
            "rsiData": trigger.get("rsiData"),
            "srsiData": trigger.get("srsiData"),
            "boostValue": trigger.get("boostValue"),
            "stars": trigger.get("stars"),
        } if trigger else None),
    )

    rule_results: list[dict] = []
    total_score = 0.0

    weight_map: dict[str, float] = {}
    if account_id:
        for w in get_weights(account_id):
            weight_map[w["rule_key"]] = w["weight"]

    prior_results = []
    for rule in rules:
        try:
            if rule.key == "rule_13_conviction":
                market_data.prior_results = prior_results
            result = rule.evaluate(market_data)
            weight = weight_map.get(rule.key, 1.0)
            weighted_score = result.score * weight
            rule_results.append({
                "key": rule.key, "name": rule.name,
                "score": _round2(weighted_score),
                "side": result.side, "detail": result.detail,
            })
            total_score += weighted_score
            if rule.key != "rule_13_conviction":
                prior_results.append(result)
        except Exception as err:  # noqa: BLE001
            log.error(f"Rule {rule.key} failed for {symbol}: {err}")

    total_score = _round2(total_score)
    side = "long" if total_score > 0 else "short" if total_score < 0 else "neutral"

    signal = SignalResult(
        symbol=symbol, total_score=total_score, side=side, rules=rule_results,
        market_data=market_data, timestamp=datetime.now(timezone.utc).isoformat(),
    )

    if total_score != 0:
        event_bus.emit("signal:generated", {
            "symbol": symbol, "score": total_score, "side": side,
            "rules": [r for r in rule_results if r["score"] != 0],
        })

    return signal


async def _async_value(v):
    return v
