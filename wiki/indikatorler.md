# Indikatorler

Hesaplama `app/lib/indicators.py`'de — v3 ile **sayisal parite** hedeflenir. `Kline` dataclass: time, open, high, low, close, volume.

## Fonksiyonlar
| Indikator | Fonksiyon | Cikti |
|---|---|---|
| RSI | `calc_rsi(closes, period=14)` | float (0-100) |
| RSI serisi | `calc_rsi_series(closes, period=14)` | her mum icin RSI listesi |
| StochRSI | `calc_stoch_rsi(closes, rsi_period=14, stoch_period=14, k_period=3, d_period=3)` | `{k, d}` |
| SMA | `sma(values, period)` | liste |
| EMA | `ema(values, period)` | liste |
| ATR | `calc_atr(klines, period=14)` | float \| None |
| ADX | `calc_adx(klines, period=14)` | `{adx, plusDI, minusDI}` \| None |
| Volume change | `calc_volume_change(klines, lookback=20)` | % (20-periyot ort'a gore) |
| RSI divergence | `detect_rsi_divergence(klines, rsi_period=14, swing_lookback=5)` | `{type, strength}` |
| Nadaraya-Watson | `calc_nadaraya_watson(klines, bandwidth=6, multiplier=3.0)` | `{regression, upper, lower, position, trend}` \| None |
| Wave Trend | `calc_wave_trend(klines, channel_len=10, avg_len=21, signal_len=4)` | `{wt1, wt2, signal, overbought, oversold}` \| None |

## Hangi kuralda
- **RSI / StochRSI** — rule 01-04, 06-09, 19, 22 (bkz. [Kurallar](kurallar.md))
- **ATR** — rule 12 (anti-chase), rule 27 (breakout)
- **ADX** — rule 26
- **EMA** — rule 23 (5m), rule 24 (15m); **SMA** — rule 22 (SMA200)
- **Volume change** — rule 05, rule 25
- **RSI divergence + Nadaraya-Watson + WaveTrend** — rule 14 (kompozit), ayrica `nw_sniper` replikasi

## Turev verileri (indikator disi)
- **Funding Rate** (+ gecmis + settlement saati) — rule 10, 15, 16, 18, 25
- **Open Interest** (1h degisim) — rule 11
- **Fiyat / 24h degisim** — rule 09, 12
