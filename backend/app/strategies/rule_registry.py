from .rules.rule_interface import TradingRule
from .rules.rule_01_extreme_rsi import rule_01_extreme_rsi
from .rules.rule_02_h1_trend import rule_02_h1_trend
from .rules.rule_03_5m_rsi import rule_03_5m_rsi
from .rules.rule_04_stochrsi_extreme import rule_04_stochrsi_extreme
from .rules.rule_05_volume_spike import rule_05_volume_spike
from .rules.rule_06_tf_divergence import rule_06_tf_divergence
from .rules.rule_07_multi_tf import rule_07_multi_tf
from .rules.rule_08_all_rsi_extreme import rule_08_all_rsi_extreme
from .rules.rule_09_pump_dump import rule_09_pump_dump
from .rules.rule_10_funding_rate import rule_10_funding_rate
from .rules.rule_11_open_interest import rule_11_open_interest
from .rules.rule_12_anti_chase import rule_12_anti_chase
from .rules.rule_13_conviction import rule_13_conviction
from .rules.rule_14_rsi_divergence_composite import rule_14_rsi_divergence_composite
from .rules.rule_15_negative_fr_momentum import rule_15_negative_fr_momentum
from .rules.rule_16_fr_settlement_timing import rule_16_fr_settlement_timing
from .rules.rule_17_weekend_bonus import rule_17_weekend_bonus
from .rules.rule_18_fr_extreme_guard import rule_18_fr_extreme_guard
from .rules.rule_19_rsi_direction_filter import rule_19_rsi_direction_filter
from .rules.rule_20_boost_value_filter import rule_20_boost_value_filter
from .rules.rule_21_utbot_5m import rule_21_utbot_5m
from .rules.rule_22_rsi_drop_daily import rule_22_rsi_drop_daily
from .rules.rule_23_ema_cross_5m import rule_23_ema_cross_5m
from .rules.rule_24_ema_cross_15m import rule_24_ema_cross_15m
from .rules.rule_25_fr_squeeze_setup import rule_25_fr_squeeze_setup
from .rules.rule_26_adx_trend import rule_26_adx_trend
from .rules.rule_27_atr_breakout import rule_27_atr_breakout

_static_rules: list[TradingRule] = [
    rule_01_extreme_rsi,
    rule_02_h1_trend,
    rule_03_5m_rsi,
    rule_04_stochrsi_extreme,
    rule_05_volume_spike,
    rule_06_tf_divergence,
    rule_07_multi_tf,
    rule_08_all_rsi_extreme,
    rule_09_pump_dump,
    rule_10_funding_rate,
    rule_11_open_interest,
    rule_12_anti_chase,
    rule_13_conviction,
    rule_14_rsi_divergence_composite,
    rule_15_negative_fr_momentum,
    rule_16_fr_settlement_timing,
    rule_17_weekend_bonus,
    rule_18_fr_extreme_guard,
    rule_19_rsi_direction_filter,
    rule_20_boost_value_filter,
    rule_21_utbot_5m,
    rule_22_rsi_drop_daily,
    rule_23_ema_cross_5m,
    rule_24_ema_cross_15m,
    rule_25_fr_squeeze_setup,
    rule_26_adx_trend,
    rule_27_atr_breakout,
]


def get_rules(enabled_keys: list[str] | None = None) -> list[TradingRule]:
    if enabled_keys is None:
        return _static_rules
    if len(enabled_keys) == 0:
        return []
    return [r for r in _static_rules if r.key in enabled_keys]


def get_rule(key: str) -> TradingRule | None:
    return next((r for r in _static_rules if r.key == key), None)


def get_all_rule_keys() -> list[str]:
    return [r.key for r in _static_rules]


def get_all_rule_names() -> list[dict]:
    return [{"key": r.key, "name": r.name, "sources": r.sources} for r in _static_rules]
