import { X, TrendingUp, TrendingDown, Minus } from 'lucide-react';

export type RuleSource = 'scanner' | 'sniper' | 'hammer' | 'fr';

export interface RuleDef {
  key: string; num: number; name: string; category: string;
  description: string; logic: string; scoreRange: string;
  thresholds: { condition: string; score: string; side: 'long' | 'short' | 'neutral' }[];
  timeframes: string[]; inputs: string[];
  sources?: RuleSource[];
}

export const RULES_DEFS: RuleDef[] = [
  { key: 'rule_01_extreme_rsi', num: 1, name: 'Extreme RSI + StochRSI', category: 'Momentum',
    description: 'Detects when RSI and StochRSI are simultaneously in overbought/oversold zones on 1m and 5m timeframes.',
    logic: 'Strong counter-trend signal when RSI and StochRSI are both extreme. Score increases when 1m and 5m align.',
    scoreRange: '+/-2 ~ +/-3',
    thresholds: [
      { condition: 'RSI1m<20 & SRSI1m<20 & RSI5m<30 & SRSI5m<30', score: '+3', side: 'long' },
      { condition: 'RSI1m<20 & SRSI1m<20', score: '+2', side: 'long' },
      { condition: 'RSI1m>80 & SRSI1m>80 & RSI5m>70 & SRSI5m>70', score: '-3', side: 'short' },
      { condition: 'RSI1m>80 & SRSI1m>80', score: '-2', side: 'short' },
    ],
    timeframes: ['1m', '5m'], inputs: ['RSI', 'StochRSI'],
  },
  { key: 'rule_02_h1_trend', num: 2, name: 'H1 RSI Trend', category: 'Trend',
    description: 'Determines the general trend direction based on the hourly RSI level.',
    logic: 'Produces trend / reversal signals across specific H1 RSI bands.',
    scoreRange: '+/-0.5 ~ +/-1.5',
    thresholds: [
      { condition: 'RSI_H1 < 30', score: '+1.5', side: 'long' },
      { condition: 'RSI_H1 60-65', score: '+1', side: 'long' },
      { condition: 'RSI_H1 55-60', score: '+0.5', side: 'long' },
      { condition: 'RSI_H1 > 70', score: '-1.5', side: 'short' },
      { condition: 'RSI_H1 40-45', score: '+0.5', side: 'long' },
      { condition: 'RSI_H1 35-40', score: '+1', side: 'long' },
    ],
    timeframes: ['1H'], inputs: ['RSI'],
  },
  { key: 'rule_03_5m_rsi', num: 3, name: '5m RSI Confirmation', category: 'Confirmation',
    description: 'Confirms the direction given by other rules using the 5-minute RSI.',
    logic: 'RSI>60 bullish, RSI<40 bearish. Extreme zones flip to counter-signal.',
    scoreRange: '+/-1',
    thresholds: [
      { condition: 'RSI_5m > 70', score: '-1', side: 'short' },
      { condition: 'RSI_5m > 60', score: '+1', side: 'long' },
      { condition: 'RSI_5m < 30', score: '+1', side: 'long' },
      { condition: 'RSI_5m < 40', score: '-1', side: 'short' },
    ],
    timeframes: ['5m'], inputs: ['RSI'],
  },
  { key: 'rule_04_stochrsi_extreme', num: 4, name: 'StochRSI Extreme', category: 'Momentum',
    description: 'Detects overbought / oversold extremes in 5m and 15m StochRSI.',
    logic: 'Strong signal when both 5m and 15m StochRSI are in extreme territory.',
    scoreRange: '+/-1 ~ +/-2',
    thresholds: [
      { condition: 'SRSI_5m>90 & SRSI_15m>80', score: '-2', side: 'short' },
      { condition: 'SRSI_5m>80', score: '-1', side: 'short' },
      { condition: 'SRSI_5m<10 & SRSI_15m<20', score: '+2', side: 'long' },
      { condition: 'SRSI_5m<20', score: '+1', side: 'long' },
    ],
    timeframes: ['5m', '15m'], inputs: ['StochRSI'],
  },
  { key: 'rule_05_volume', num: 5, name: 'Volume Spike', category: 'Volume',
    description: 'Compares 4H candle volume to the 20-day average. LONG/SHORT based on price direction.',
    logic: 'volume_ratio = 4H volume / (20D avg daily volume / 6). Ratio bands combined with price direction.',
    scoreRange: '+/-0.5 ~ +/-1.5',
    thresholds: [
      { condition: 'Ratio 3.5-6.0x & price up', score: '+1.5', side: 'long' },
      { condition: 'Ratio 3.5-6.0x & price down', score: '-1.5', side: 'short' },
      { condition: 'Ratio 2.0-3.5x & price up', score: '+1', side: 'long' },
      { condition: 'Ratio 2.0-3.5x & price down', score: '-1', side: 'short' },
      { condition: 'Ratio 1.3-2.0x & price up', score: '+0.5', side: 'long' },
      { condition: 'Ratio 1.3-2.0x & price down', score: '-0.5', side: 'short' },
      { condition: 'Ratio >= 6.0x (manipulation)', score: '+/-0.5', side: 'neutral' },
    ],
    timeframes: ['4H'], inputs: ['4H Volume', '20D Avg Volume', '4H Price Change'],
  },
  { key: 'rule_06_tf_divergence', num: 6, name: 'TF Divergence', category: 'Divergence',
    description: 'Detects mismatch between 5m and H1 RSI. Generates reversal signals.',
    logic: 'Bearish divergence when 5m RSI is overbought while H1 RSI is low (and vice versa).',
    scoreRange: '+/-1 ~ +/-1.5',
    thresholds: [
      { condition: 'RSI_5m>70 & RSI_H1<40', score: '-1.5', side: 'short' },
      { condition: 'RSI_5m>65 & RSI_H1<45', score: '-1', side: 'short' },
      { condition: 'RSI_5m<30 & RSI_H1>60', score: '+1.5', side: 'long' },
      { condition: 'RSI_5m<35 & RSI_H1>55', score: '+1', side: 'long' },
    ],
    timeframes: ['5m', '1H'], inputs: ['RSI'],
  },
  { key: 'rule_07_multi_tf', num: 7, name: 'Multi-TF Alignment', category: 'Trend',
    description: 'Strong trend signal when all timeframes align.',
    logic: 'Per-TF: RSI>55 bullish, RSI<45 bearish. 4/4 alignment is strongest.',
    scoreRange: '+/-1 ~ +/-2',
    thresholds: [
      { condition: '4/4 TFs bullish (RSI>55)', score: '+2', side: 'long' },
      { condition: '3/4 TFs bullish', score: '+1', side: 'long' },
      { condition: '4/4 TFs bearish (RSI<45)', score: '-2', side: 'short' },
      { condition: '3/4 TFs bearish', score: '-1', side: 'short' },
    ],
    timeframes: ['5m', '15m', '1H', '4H'], inputs: ['RSI'],
  },
  { key: 'rule_08_all_rsi_extreme', num: 8, name: 'All RSI Extreme', category: 'Momentum',
    description: 'Multiple timeframes show RSI in extreme territory simultaneously.',
    logic: 'Count of 1m / 5m / 15m / H1 RSI readings > 70 or < 30.',
    scoreRange: '+/-1 ~ +/-2',
    thresholds: [
      { condition: '3+ TFs RSI>70', score: '-2', side: 'short' },
      { condition: '2 TFs RSI>70', score: '-1', side: 'short' },
      { condition: '3+ TFs RSI<30', score: '+2', side: 'long' },
      { condition: '2 TFs RSI<30', score: '+1', side: 'long' },
    ],
    timeframes: ['1m', '5m', '15m', '1H'], inputs: ['RSI'],
  },
  { key: 'rule_09_pump_dump', num: 9, name: 'Pump/Dump Detection', category: 'Volatility',
    description: '15%+ move + extreme RSI = pump/dump detection.',
    logic: '15%+ up + RSI>80 = short. 15%+ down + RSI<20 = long.',
    scoreRange: '+/-2 ~ +/-3',
    thresholds: [
      { condition: 'Price > +15% & RSI_5m>80', score: '-3', side: 'short' },
      { condition: 'Price > +15% & RSI_5m>70', score: '-2', side: 'short' },
      { condition: 'Price < -15% & RSI_5m<20', score: '+3', side: 'long' },
      { condition: 'Price < -15% & RSI_5m<30', score: '+2', side: 'long' },
    ],
    timeframes: ['24H', '5m'], inputs: ['Price Change', 'RSI'],
  },
  { key: 'rule_10_funding_rate', num: 10, name: 'Funding Rate', category: 'Sentiment',
    description: 'Perpetual futures funding rate analysis.',
    logic: 'The higher the FR, the stronger the counter-trend signal. Three threshold tiers.',
    scoreRange: '+/-0.5 ~ +/-2',
    thresholds: [
      { condition: 'FR > 0.10%', score: '-2', side: 'short' },
      { condition: 'FR > 0.05%', score: '-1', side: 'short' },
      { condition: 'FR > 0.02%', score: '-0.5', side: 'short' },
      { condition: 'FR < -0.10%', score: '+2', side: 'long' },
      { condition: 'FR < -0.05%', score: '+1', side: 'long' },
      { condition: 'FR < -0.02%', score: '+0.5', side: 'long' },
    ],
    timeframes: ['8H cycle'], inputs: ['Funding Rate'],
  },
  { key: 'rule_11_open_interest', num: 11, name: 'Open Interest', category: 'Sentiment',
    description: 'Trend strength / weakness from OI change combined with price direction.',
    logic: 'OI up + price up = trend continuation.',
    scoreRange: '+/-0.5 ~ +/-1',
    thresholds: [
      { condition: 'OI > +5% & price up', score: '+1', side: 'long' },
      { condition: 'OI > +5% & price down', score: '-1', side: 'short' },
      { condition: 'OI > +3% & price up', score: '+0.5', side: 'long' },
      { condition: 'OI < -5% & price up', score: '-0.5', side: 'short' },
      { condition: 'OI < -5% & price down', score: '+0.5', side: 'long' },
    ],
    timeframes: ['24H'], inputs: ['Open Interest', 'Price Change'],
  },
  { key: 'rule_12_anti_chase', num: 12, name: 'Anti-Chase Penalty', category: 'Risk',
    description: 'ATR-based anti-chase penalty. Reduces score for entries against an already extended move.',
    logic: 'Normalizes 4H candle range by ATR. Short penalty > Long penalty (squeeze risk).',
    scoreRange: '-0.5 ~ -3',
    thresholds: [
      { condition: 'ATR ratio >= 6.0 (up, EXTREME_CHASE)', score: '-3', side: 'short' },
      { condition: 'ATR ratio 4.0-6.0 (up, DANGER)', score: '-2', side: 'short' },
      { condition: 'ATR ratio 2.5-4.0 (up, FOMO)', score: '-1.5', side: 'short' },
      { condition: 'ATR ratio 1.5-2.5 (up)', score: '-1', side: 'short' },
      { condition: 'ATR ratio >= 6.0 (down, FALLING_KNIFE)', score: '-2', side: 'long' },
      { condition: 'ATR ratio 4.0-6.0 (down, DANGER)', score: '-1.5', side: 'long' },
      { condition: 'ATR ratio 2.5-4.0 (down, FOMO)', score: '-1', side: 'long' },
      { condition: 'ATR ratio 1.5-2.5 (down)', score: '-0.5', side: 'long' },
    ],
    timeframes: ['4H'], inputs: ['4H Price Change', 'ATR(14)', 'Fallback: 8%/12%/18%/25%'],
  },
  { key: 'rule_13_conviction', num: 13, name: 'Conviction Bonus', category: 'Meta',
    description: 'Bonus score when 4+ rules agree on the same direction.',
    logic: 'Counts rules pointing to the same side and adds a bonus when the threshold is met.',
    scoreRange: '+/-1 ~ +/-2',
    thresholds: [
      { condition: '6+ rules long', score: '+2', side: 'long' },
      { condition: '4+ rules long', score: '+1', side: 'long' },
      { condition: '6+ rules short', score: '-2', side: 'short' },
      { condition: '4+ rules short', score: '-1', side: 'short' },
    ],
    timeframes: ['--'], inputs: ['Outputs of other rules'],
  },
  { key: 'rule_14_rsi_divergence', num: 14, name: 'RSI Divergence + NW + WT', category: 'Advanced',
    description: 'Composite rule: 4H RSI divergence + Nadaraya-Watson band + Wave Trend. Cumulative scoring.',
    logic: 'Base: confirmed div = 1.5, forming div = 0.75. Extra confirmations (1H/1D div, NW band, WT signal) add +0.25 ~ +0.5. Minimum score 0.5.',
    scoreRange: '+/-0.5 ~ +/-2.75',
    thresholds: [
      { condition: '4H confirmed divergence (base)', score: '+/-1.5', side: 'neutral' },
      { condition: '4H forming divergence (base)', score: '+/-0.75', side: 'neutral' },
      { condition: '1H same-direction divergence', score: '+0.25', side: 'neutral' },
      { condition: '1D same-direction divergence', score: '+0.25', side: 'neutral' },
      { condition: 'NW band strong touch (>0.7)', score: '+0.5', side: 'neutral' },
      { condition: 'NW band near (>0.4)', score: '+0.25', side: 'neutral' },
      { condition: 'WT signal (buy/sell)', score: '+0.5', side: 'neutral' },
      { condition: 'WT approaching signal / extreme zone', score: '+0.25', side: 'neutral' },
      { condition: 'Opposite-direction confirmation', score: '-0.25', side: 'neutral' },
    ],
    timeframes: ['1H', '4H', '1D'], inputs: ['RSI', 'Nadaraya-Watson', 'Wave Trend'],
    sources: ['sniper'],
  },
  { key: 'rule_15_neg_fr_momentum', num: 15, name: 'FR Momentum (Symmetric)', category: 'Sentiment',
    description: 'Detects funding rate momentum for BOTH positive and negative sides. Targets short squeezes in negative FR and long squeezes in positive FR.',
    logic: 'If extreme FR worsens -> Neutral (danger). If extreme FR improves -> Reversal Signal. Quick cycles + improving momentum adds bonus.',
    scoreRange: '-3 ~ +4',
    thresholds: [
      { condition: 'Extreme Neg FR (<-0.75%) & Improving', score: '+2', side: 'long' },
      { condition: 'Extreme Pos FR (>0.75%) & Dropping', score: '-2', side: 'short' },
      { condition: 'Extreme FR Worsening', score: '0', side: 'neutral' },
      { condition: 'Neg FR [-0.10, 0) + Price Up >10%', score: '+2', side: 'long' },
      { condition: 'Pos FR (0, 0.10] + Price Down >10%', score: '-2', side: 'short' },
    ],
    timeframes: ['FR cycle'], inputs: ['Funding Rate', 'FR History', 'Price Change'],
  },
  { key: 'rule_16_fr_settlement_timing', num: 16, name: 'FR Settlement Timing', category: 'Sentiment',
    description: 'Adjusts signal quality based on the funding rate settlement hour. Analysis of 5,000 signals: UTC 02:00 was best, UTC 08:00 was worst.',
    logic: 'FR effect is most pronounced near settlement hours. Best / worst hours derived from data.',
    scoreRange: '+/-1',
    thresholds: [
      { condition: 'UTC 02:00 (best hour)', score: '+1', side: 'long' },
      { condition: 'UTC 00:00-04:00', score: '+0.5', side: 'long' },
      { condition: 'UTC 08:00 (worst hour)', score: '-1', side: 'short' },
      { condition: 'UTC 06:00-10:00', score: '-0.5', side: 'short' },
    ],
    timeframes: ['Settlement cycle'], inputs: ['UTC Hour', 'Funding Rate'],
    sources: ['fr', 'scanner', 'hammer', 'sniper'],
  },
  { key: 'rule_17_weekend_bonus', num: 17, name: 'Weekend Penalty', category: 'Risk',
    description: 'Hafta sonu sinyallerine direction-aware ceza uygular. Backtest: hafta sonu WR 44.7% (1h), avg -4.51% (24h). Dusuk likidite ve yuksek manipulasyon riski.',
    logic: 'Sinyal yonu UP ise score negatif (LONG zayiflatilir), DOWN ise pozitif (SHORT zayiflatilir). Sinyal yonu yoksa priorResults toplamindan turetilir. Cuma >=18:00 UTC yarim ceza.',
    scoreRange: '-1 ~ +1',
    thresholds: [
      { condition: 'Cumartesi/Pazar + UP sinyal', score: '-1', side: 'short' },
      { condition: 'Cumartesi/Pazar + DOWN sinyal', score: '+1', side: 'long' },
      { condition: 'Cuma >=18:00 UTC + UP', score: '-0.5', side: 'short' },
      { condition: 'Cuma >=18:00 UTC + DOWN', score: '+0.5', side: 'long' },
      { condition: 'Yon belirsiz / hafta ici', score: '0', side: 'neutral' },
    ],
    timeframes: ['Daily'], inputs: ['Day of Week', 'Alert Direction', 'Prior Rules'],
    sources: ['fr', 'scanner', 'hammer', 'sniper'],
  },
  { key: 'rule_18_fr_extreme_guard', num: 18, name: 'FR Extreme Guard', category: 'Risk',
    description: 'Protection and entry mechanism at extreme funding rate levels. Based on analysis of 20,036 FR signals. Ultra-negative FR (<-1.5%) carries delisting / scam risk.',
    logic: 'FR -0.05% ~ -0.005% is the quality long zone (WR 76.5%). FR < -0.75% is extreme negative (WR 14.4%). Confluence applies bonus / penalty.',
    scoreRange: '-5 ~ +3.5',
    thresholds: [
      { condition: 'FR < -1.5% (delisting risk)', score: '-3', side: 'short' },
      { condition: 'FR < -0.75% (extreme neg)', score: '-2', side: 'short' },
      { condition: 'FR < -0.25% (high neg)', score: '-0.5', side: 'short' },
      { condition: 'FR -0.05% ~ -0.005% (quality)', score: '+2', side: 'long' },
      { condition: 'FR -0.005% ~ +0.005% (stable)', score: '+1', side: 'long' },
      { condition: 'FR > +0.10% (extreme pos)', score: '-2', side: 'short' },
      { condition: 'FR > +0.05% (high pos)', score: '-1', side: 'short' },
      { condition: 'Confluence >= +3 + positive score', score: '+1.5', side: 'long' },
      { condition: 'UP signal + extreme neg FR', score: '-1', side: 'short' },
    ],
    timeframes: ['FR cycle'], inputs: ['Funding Rate', 'Prior Rules'],
  },
  { key: 'rule_19_rsi_direction_filter', num: 19, name: 'RSI Direction Filter', category: 'Momentum',
    description: 'Scores signal quality by comparing alert direction with H1 RSI level. 60K-signal backtest: RSI>70+DOWN 65.2% WR (24h), +2.63% avg. RSI<30+UP only 39.8% WR.',
    logic: 'H1 RSI overbought + DOWN signal = strong reversal setup. H1 RSI oversold + UP signal = contrarian trap (poor). TP10/SL5 → +44.3% profit, 6% DD, PF 2.03.',
    scoreRange: '-2 ~ +3',
    thresholds: [
      { condition: 'H1 RSI > 80 + DOWN signal', score: '+3', side: 'long' },
      { condition: 'H1 RSI > 70 + DOWN signal', score: '+2', side: 'long' },
      { condition: 'H1 RSI < 20 + UP signal', score: '-2', side: 'short' },
      { condition: 'H1 RSI < 30 + UP signal', score: '-1.5', side: 'short' },
    ],
    timeframes: ['1H'], inputs: ['RSI H1', 'Alert Direction'],
    sources: ['hammer', 'sniper'],
  },
  { key: 'rule_20_boost_value_filter', num: 20, name: 'Boost Value Filter', category: 'Momentum',
    description: 'Measures signal strength from the alert boost value. 60K-signal backtest: Boost>20% 4h WR 61.4%, avg +3.16%. Boost<5% 4h WR 48.1%, avg -1.58%.',
    logic: 'High boost = strong momentum move. Low boost = weak signal. TP10/SL5 → +38.7% profit, 6.5% DD, PF 1.77.',
    scoreRange: '-1.5 ~ +2',
    thresholds: [
      { condition: 'Boost > 30%', score: '+2', side: 'long' },
      { condition: 'Boost > 20%', score: '+1.5', side: 'long' },
      { condition: 'Boost 10-20%', score: '+1', side: 'long' },
      { condition: 'Boost < 2%', score: '-1.5', side: 'short' },
      { condition: 'Boost < 5%', score: '-1', side: 'short' },
    ],
    timeframes: ['-'], inputs: ['Boost Value', 'Alert Direction'],
    sources: ['hammer', 'sniper'],
  },
  { key: 'rule_21_utbot_5m', num: 21, name: 'UT Bot 5m', category: 'Momentum',
    description: 'Applies a momentum filter based on the UT Bot (ATR trailing-stop) buy/sell signal on 5m candles.',
    logic: 'Watches the ATR trailing-stop break and 5m close direction; buy signal → long score, sell signal → short score.',
    scoreRange: '+/-1.5',
    thresholds: [
      { condition: '5m UT Bot BUY signal', score: '+1.5', side: 'long' },
      { condition: '5m UT Bot SELL signal', score: '-1.5', side: 'short' },
      { condition: 'No signal', score: '0', side: 'neutral' },
    ],
    timeframes: ['5m'], inputs: ['ATR', 'Trailing Stop', 'Close'],
    sources: ['scanner', 'hammer', 'sniper'],
  },
  { key: 'rule_22_rsi_drop_daily', num: 22, name: 'RSI Drop Strategy (Daily MR)', category: 'Momentum',
    description: 'QuantifiedStrategies.com RSI Drop strategy: daily long-term trend filter + oversold + 3 consecutive RSI drops = mean-reversion LONG. Backtest (S&P 500): WR 81%, PF 36, max DD 14%.',
    logic: 'On daily klines: (1) confirm uptrend via close > SMA(200). (2) RSI(2) < 20 for oversold. (3) RSI(2) must have fallen 3 days in a row. All three → long bounce signal. RSI(2) > 70 → mild short bias (overbought exit zone).',
    scoreRange: '+3 / -1',
    thresholds: [
      { condition: 'close>SMA200 + RSI(2)<20 + 3-day drop', score: '+3', side: 'long' },
      { condition: 'RSI(2) > 70 (overbought)', score: '-1', side: 'short' },
      { condition: 'Other states', score: '0', side: 'neutral' },
    ],
    timeframes: ['1D'], inputs: ['Close', 'SMA(200)', 'RSI(2)'],
    sources: ['scanner'],
  },
  { key: 'rule_23_ema_cross_5m', num: 23, name: 'EMA 5/9 Crossover (5m, TP2/SL1)', category: 'Trend',
    description: 'EMA(5) ve EMA(9) kesismelerini 5 dakikalik mum verisinde takip eder. Golden cross (EMA5>EMA9) LONG, death cross SHORT sinyali. Onerilen: TP %2 / SL %1 (2:1 R:R).',
    logic: 'Son mumda kesisme +/-2. Son 3 mum icinde kesisme +/-1. EMA5>EMA9 hizali +0.5 (uptrend), EMA5<EMA9 -0.5 (downtrend).',
    scoreRange: '+/-0.5 ~ +/-2',
    thresholds: [
      { condition: '5m EMA5/EMA9 golden cross (current bar)', score: '+2', side: 'long' },
      { condition: '5m EMA5/EMA9 death cross (current bar)', score: '-2', side: 'short' },
      { condition: 'Cross within last 3 bars (golden)', score: '+1', side: 'long' },
      { condition: 'Cross within last 3 bars (death)', score: '-1', side: 'short' },
      { condition: 'EMA5 above EMA9 (trend)', score: '+0.5', side: 'long' },
      { condition: 'EMA5 below EMA9 (trend)', score: '-0.5', side: 'short' },
    ],
    timeframes: ['5m'], inputs: ['EMA(5)', 'EMA(9)', 'Close'],
    sources: ['scanner', 'sniper', 'hammer'],
  },
  { key: 'rule_25_fr_squeeze_setup', num: 25, name: 'FR Squeeze Set Up', category: 'Sentiment',
    description: 'Telegram FR botu -0.05% altinda artis sinyali. Negatif FR + OI artis + hacim varsa short squeeze setup (LONG). Geri sayim azaldikca skor artar.',
    logic: 'FR<-0.05% & FR yukseliyor & OI artiyor & vol>1x. Base skor geri sayima gore (>4H +2, 1-4H +3, <1H +4). FR<-1% & <1H = +5. Bonus: FR<-0.10% +1, FR<-0.20% +2.',
    scoreRange: '+2 ~ +7',
    thresholds: [
      { condition: 'FR<-1% & OI artiyor & hacim & geri sayim <1H', score: '+5', side: 'long' },
      { condition: 'FR<-0.05% & OI artiyor & hacim & geri sayim <1H', score: '+4', side: 'long' },
      { condition: 'FR<-0.05% & OI artiyor & hacim & geri sayim 1-4H', score: '+3', side: 'long' },
      { condition: 'FR<-0.05% & OI artiyor & hacim & geri sayim >4H', score: '+2', side: 'long' },
      { condition: 'Bonus: FR<-0.20%', score: '+2', side: 'long' },
      { condition: 'Bonus: FR<-0.10%', score: '+1', side: 'long' },
      { condition: 'FR>=-0.05% veya FR dusuyor veya OI azaliyor veya hacim<1x', score: '0', side: 'neutral' },
    ],
    timeframes: ['FR cycle'], inputs: ['Funding Rate', 'FR History', 'Open Interest Change', 'Volume Change', 'FR Cycle Hours'],
    sources: ['fr'],
  },
  { key: 'rule_24_ema_cross_15m', num: 24, name: 'EMA 5/9 Crossover (15m, TP2/SL1)', category: 'Trend',
    description: 'EMA(5) ve EMA(9) kesismelerini 15 dakikalik mum verisinde takip eder. Golden cross LONG, death cross SHORT sinyali. Onerilen: TP %2 / SL %1 (2:1 R:R).',
    logic: 'Son mumda kesisme +/-2. Son 3 mum icinde kesisme +/-1. EMA5>EMA9 hizali +0.5 (uptrend), EMA5<EMA9 -0.5 (downtrend).',
    scoreRange: '+/-0.5 ~ +/-2',
    thresholds: [
      { condition: '15m EMA5/EMA9 golden cross (current bar)', score: '+2', side: 'long' },
      { condition: '15m EMA5/EMA9 death cross (current bar)', score: '-2', side: 'short' },
      { condition: 'Cross within last 3 bars (golden)', score: '+1', side: 'long' },
      { condition: 'Cross within last 3 bars (death)', score: '-1', side: 'short' },
      { condition: 'EMA5 above EMA9 (trend)', score: '+0.5', side: 'long' },
      { condition: 'EMA5 below EMA9 (trend)', score: '-0.5', side: 'short' },
    ],
    timeframes: ['15m'], inputs: ['EMA(5)', 'EMA(9)', 'Close'],
    sources: ['scanner', 'sniper'],
  },
  { key: 'rule_26_adx_trend', num: 26, name: 'ADX Trend Strength (1H)', category: 'Trend',
    description: '1H mumlarda ADX(14) trend gucunu, +DI/-DI ise yonu olcer. ADX > 25 guclu trend; +DI > -DI long, aksi short. ADX < 20 ise yatay piyasa, notr.',
    logic: 'ADX trend gucu, +DI/-DI yon. ADX>40 cok guclu (+/-2), >25 guclu (+/-1.5), >20 gelisen (+/-0.5), <20 notr.',
    scoreRange: '+/-0.5 ~ +/-2',
    thresholds: [
      { condition: 'ADX > 40 & +DI > -DI', score: '+2', side: 'long' },
      { condition: 'ADX > 25 & +DI > -DI', score: '+1.5', side: 'long' },
      { condition: 'ADX > 40 & -DI > +DI', score: '-2', side: 'short' },
      { condition: 'ADX > 25 & -DI > +DI', score: '-1.5', side: 'short' },
      { condition: 'ADX < 20 (yatay)', score: '0', side: 'neutral' },
    ],
    timeframes: ['1H'], inputs: ['ADX(14)', '+DI', '-DI'],
    sources: ['scanner', 'sniper', 'hammer', 'fr'],
  },
  { key: 'rule_27_atr_breakout', num: 27, name: 'ATR Volatility Breakout (15m)', category: 'Volatility',
    description: '15m kapanisin onceki 20 mumun yuksek/dusugunu ATR(14) katiyla asip asmadigina bakar. Statik yuzde yerine ATR ile olcekledigi icin her coinin oynakligina uyum saglar.',
    logic: 'close > priorHigh + 1*ATR guclu yukari kirilim (+2). close > priorHigh yukari kirilim (+1). Asagi icin simetrik.',
    scoreRange: '+/-1 ~ +/-2',
    thresholds: [
      { condition: 'close > priorHigh + 1*ATR', score: '+2', side: 'long' },
      { condition: 'close > priorHigh', score: '+1', side: 'long' },
      { condition: 'close < priorLow - 1*ATR', score: '-2', side: 'short' },
      { condition: 'close < priorLow', score: '-1', side: 'short' },
      { condition: 'Kanal icinde', score: '0', side: 'neutral' },
    ],
    timeframes: ['15m'], inputs: ['ATR(14)', '20-bar High/Low', 'Close'],
    sources: ['scanner', 'sniper', 'hammer'],
  },
];

export const CATEGORY_COLORS: Record<string, string> = {
  Momentum: 'text-purple-400 bg-purple-400/10 border-purple-400/30',
  Trend: 'text-blue-400 bg-blue-400/10 border-blue-400/30',
  Confirmation: 'text-cyan-400 bg-cyan-400/10 border-cyan-400/30',
  Volume: 'text-yellow-400 bg-yellow-400/10 border-yellow-400/30',
  Divergence: 'text-orange-400 bg-orange-400/10 border-orange-400/30',
  Volatility: 'text-red-400 bg-red-400/10 border-red-400/30',
  Sentiment: 'text-teal-400 bg-teal-400/10 border-teal-400/30',
  Risk: 'text-rose-400 bg-rose-400/10 border-rose-400/30',
  Meta: 'text-indigo-400 bg-indigo-400/10 border-indigo-400/30',
  Advanced: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/30',
};

export function RuleModal({ rule, onClose }: { rule: RuleDef; onClose: () => void }) {
  const catClass = CATEGORY_COLORS[rule.category] || 'text-ink-400 bg-ink-800 border-white/10';
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60" />
      <div className="relative bg-ink-900 border border-white/10 w-[560px] max-h-[80vh] overflow-auto shadow-2xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-ink-850 sticky top-0 z-10">
          <div className="flex items-center gap-3">
            <span className="text-ink-50 font-medium text-[13px]">Rule{rule.num}: {rule.name}</span>
            <span className={`px-2 py-0.5 text-[9px] tracking-widest border ${catClass}`}>
              {rule.category.toUpperCase()}
            </span>
          </div>
          <button onClick={onClose} className="text-ink-400 hover:text-ink-100 transition-colors p-1">
            <X size={16} />
          </button>
        </div>
        <div className="p-4 space-y-4">
          <p className="text-[12px] text-ink-200 leading-relaxed">{rule.description}</p>
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-ink-850 border border-white/5 p-3">
              <p className="text-[9px] text-ink-400 tracking-[0.2em] mb-1.5">MANTIK</p>
              <p className="text-[11px] text-ink-100 leading-relaxed">{rule.logic}</p>
            </div>
            <div className="bg-ink-850 border border-white/5 p-3">
              <div className="mb-2">
                <p className="text-[9px] text-ink-400 tracking-[0.2em] mb-1">TIMEFRAMES</p>
                <div className="flex flex-wrap gap-1">
                  {rule.timeframes.map((tf) => (
                    <span key={tf} className="px-1.5 py-0.5 bg-ink-800 border border-white/5 text-[10px] text-ink-100">{tf}</span>
                  ))}
                </div>
              </div>
              <div className="mb-2">
                <p className="text-[9px] text-ink-400 tracking-[0.2em] mb-1">INPUTS</p>
                <div className="flex flex-wrap gap-1">
                  {rule.inputs.map((inp) => (
                    <span key={inp} className="px-1.5 py-0.5 bg-ink-800 border border-white/5 text-[10px] text-ink-100">{inp}</span>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-[9px] text-ink-400 tracking-[0.2em] mb-1">SOURCES</p>
                <div className="flex flex-wrap gap-1">
                  {(rule.sources && rule.sources.length > 0) ? rule.sources.map((s) => (
                    <span key={s} className="px-1.5 py-0.5 bg-info/10 border border-info/30 text-[10px] text-info uppercase">{s}</span>
                  )) : (
                    <span className="px-1.5 py-0.5 bg-ink-800 border border-white/5 text-[10px] text-ink-300">ALL</span>
                  )}
                </div>
              </div>
            </div>
          </div>
          <div className="bg-ink-850 border border-white/5">
            <div className="flex items-center justify-between px-3 py-2 border-b border-white/5">
              <p className="text-[9px] text-ink-400 tracking-[0.2em]">THRESHOLDS</p>
              <span className="text-[10px] text-ink-300 num">{rule.scoreRange}</span>
            </div>
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-white/5 text-ink-400">
                  <th className="text-left px-3 py-1.5 font-medium text-[9px] tracking-widest">CONDITION</th>
                  <th className="text-center px-3 py-1.5 font-medium text-[9px] tracking-widest w-20">SCORE</th>
                  <th className="text-center px-3 py-1.5 font-medium text-[9px] tracking-widest w-16">SIDE</th>
                </tr>
              </thead>
              <tbody>
                {rule.thresholds.map((t, i) => (
                  <tr key={i} className="border-b border-white/[0.03]">
                    <td className="px-3 py-2 text-ink-200 font-mono text-[10px]">{t.condition}</td>
                    <td className={`px-3 py-2 text-center num font-semibold ${
                      t.score.startsWith('+') ? 'text-up' : t.score.startsWith('-') ? 'text-down' : 'text-ink-200'
                    }`}>{t.score}</td>
                    <td className="px-3 py-2 text-center">
                      <span className="inline-flex items-center gap-1">
                        {t.side === 'long' ? <TrendingUp size={11} className="text-up" /> :
                         t.side === 'short' ? <TrendingDown size={11} className="text-down" /> :
                         <Minus size={11} className="text-ink-400" />}
                        <span className={`text-[9px] tracking-wider font-medium ${
                          t.side === 'long' ? 'text-up' : t.side === 'short' ? 'text-down' : 'text-ink-300'
                        }`}>{t.side.toUpperCase()}</span>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
