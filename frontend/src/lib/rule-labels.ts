import { getOverrideName, getOverrideNote } from '../store/rule-labels-store';

export const RULE_LABELS: Record<string, string> = {
  rule_01_extreme_rsi: 'Extreme RSI + StochRSI',
  rule_02_h1_trend: 'H1 RSI Trend',
  rule_03_5m_rsi: '5m RSI Confirmation',
  rule_04_stochrsi_extreme: 'StochRSI Extreme',
  rule_05_volume: 'Volume Spike',
  rule_06_tf_divergence: 'TF Divergence',
  rule_07_multi_tf: 'Multi-TF Alignment',
  rule_08_all_rsi_extreme: 'All RSI Extreme',
  rule_09_pump_dump: 'Pump/Dump Detection',
  rule_10_funding_rate: 'FR Bucket (Data-Driven)',
  rule_11_open_interest: 'Open Interest',
  rule_12_anti_chase: 'Anti-Chase Penalty',
  rule_13_conviction: 'Conviction Bonus',
  rule_14_rsi_divergence: 'RSI Divergence + NW + WT',
  rule_15_neg_fr_momentum: 'FR Momentum (Symmetric)',
  rule_16_fr_settlement_timing: 'FR Settlement Timing',
  rule_17_weekend_bonus: 'Weekend Signal Bonus',
  rule_18_fr_extreme_guard: 'FR Extreme Guard',
  rule_19_rsi_direction_filter: 'RSI Direction Filter',
  rule_20_boost_value_filter: 'Boost Value Filter',
  rule_21_utbot_5m: 'UT Bot 5m',
  rule_22_rsi_drop_daily: 'RSI Drop Strategy (Daily MR)',
  rule_23_ema_cross_5m: 'EMA 5/9 Crossover (5m)',
  rule_24_ema_cross_15m: 'EMA 5/9 Crossover (15m)',
};

export function ruleLabel(key: string): string {
  return getOverrideName(key) || RULE_LABELS[key] || key;
}

export function defaultRuleLabel(key: string): string {
  return RULE_LABELS[key] || key;
}

export function ruleNote(key: string): string | null {
  return getOverrideNote(key);
}
