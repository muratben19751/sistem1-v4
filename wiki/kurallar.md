# Kurallar

**27 statik kural**, her biri `app/strategies/rules/rule_XX_*.py`'de. `rule_registry.py`'de kayitli. Her kural `evaluate(market_data) -> RuleResult{score, side, detail}` doner; `analyze_symbol` skoru ogrenilen `weight` ile carpip `total_score` toplar. Yon: `total_score > 0 -> long`, `< 0 -> short`, `0 -> neutral`.

## Registry
`app/strategies/rule_registry.py`: `get_rules(enabled_keys?)`, `get_rule(key)`, `get_all_rule_keys()`, `get_all_rule_names()` (key/name/sources). `TradingRule` dataclass: `key, name, evaluate, sources, recommended_tp/sl?`. `MarketData`: klines, ticker, funding_rate, open_interest, rsi, stoch_rsi, volume_change, funding_history, trigger_alert. `RuleResult`: score, side, detail.

## Tum kurallar
| # | key | Ne skorlar |
|---|---|---|
| 01 | rule_01_extreme_rsi | 1m/5m ekstrem RSI + StochRSI |
| 02 | rule_02_h1_trend | H1 RSI bolgeleri (oversold/reversal/uptrend/overbought) |
| 03 | rule_03_5m_rsi | 5m RSI ekstremleri |
| 04 | rule_04_stochrsi_extreme | 5m/15m StochRSI ekstrem |
| 05 | rule_05_volume | 4H hacim/20-gun ort + 1H teyit |
| 06 | rule_06_tf_divergence | 5m vs H1 RSI uyumsuzluk |
| 07 | rule_07_multi_tf | [5m,15m,60,240] RSI hizalanma |
| 08 | rule_08_all_rsi_extreme | [1m,5m,15m,60] RSI ekstrem sayimi |
| 09 | rule_09_pump_dump | 24h pump/dump + RSI |
| 10 | rule_10_funding_rate | FR esik/bolge (veri-odakli) |
| 11 | rule_11_open_interest | 1h OI degisim + fiyat yonu |
| 12 | rule_12_anti_chase | ATR'ye gore buyuk 4H hareketi cezalandir (FOMO) |
| 13 | rule_13_conviction | Meta: onceki kurallarin uyumu (`prior_results`) |
| 14 | rule_14_rsi_divergence | RSI divergence + Nadaraya-Watson + WaveTrend (D/60/240) |
| 15 | rule_15_neg_fr_momentum | FR momentum trendi (gecmisten) |
| 16 | rule_16_fr_settlement_timing | UTC settlement saati ceza/bonus |
| 17 | rule_17_weekend_bonus | Hafta sonu / Cuma gec ceza-bonus |
| 18 | rule_18_fr_extreme_guard | Asiri negatif (delist riski) / pozitif FR koruma |
| 19 | rule_19_rsi_direction_filter | Alert yonu vs H1 RSI (DOWN+yuksek RSI reversal, UP+dusuk RSI tuzak) |
| 20 | rule_20_boost_value_filter | Alert boost % skoru |
| 21 | rule_21_utbot_5m | UT Bot trailing (5m) al/sat |
| 22 | rule_22_rsi_drop_daily | Gunluk RSI(2) mean-reversion + SMA200 |
| 23 | rule_23_ema_cross_5m | EMA5/9 cross (5m, TP2/SL1) |
| 24 | rule_24_ema_cross_15m | EMA5/9 cross (15m, TP2/SL1) |
| 25 | rule_25_fr_squeeze_setup | Dusuk-FR squeeze, settlement yakin + hacim (TP5/SL3) |
| 26 | rule_26_adx_trend | ADX trend gucu (1H): >=40 cok guclu, >=25 guclu |
| 27 | rule_27_atr_breakout | 15m ATR volatilite kirilmasi |

## analyze_symbol akisi
`app/agents/strategy.py`:
1. Etkin kurallarin ihtiyac duydugu timeframe'leri belirler (`STATIC_RULE_TIMEFRAMES`; orn. rule_01 -> ["1","5"], rule_02 -> ["60"]) ve her biri icin 200 kline ceker.
2. RSI/StochRSI/volume_change hesaplar; gerekirse funding history + OI degisimi ceker.
3. Her kurali sirayla calistirir; `rule_13` icin onceki sonuclar (`prior_results`) verilir.
4. `weighted = score * weight`; `total_score = sum(weighted)`. `total_score != 0` ise `signal:generated` yayilir.

## Ogrenme (Learning)
Kapanan trade, `active_rules`'taki kurallarin `learning_weights` agirligini PnL'e gore ayarlar; `weight_history`'ye iz dusulur. Agirlik skorun carpani oldugundan karli kurallar zamanla baskinlasir. `app/agents/learning.py`.

## Yeni kural ekleme
`rules/` altina dosya ekle -> `rule_registry.py`'ye kaydet -> `STATIC_RULE_TIMEFRAMES`'e gerekli timeframe'leri yaz -> frontend tanimi. v3 ile sayisal parite korunmali.
