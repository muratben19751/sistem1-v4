# Backtest + Optimizer

Gecmis alert + kline verisi uzerinde strateji koşturup metrik ureten backtest motoru ve onu genetik algoritma ile optimize eden dongu.

- `app/engines/backtest_engine.py` — `run_backtest(params)`
- `app/agents/backtest_optimizer.py` — GA loop (680+ satir)
- Route'lar: `/api/backtest`, `/api/optimizer`
- Cache: `services/kline_cache.py`, `services/funding_cache.py`

## Backtest run
`run_backtest(params)`:
1. `alerts`'ten kaynak tipi + zaman penceresi `[start_ms, end_ms]` ile sinyalleri ceker; kaynak basina downsample (`maxSignals`), sembol evrenini frekansa gore sinirla (`maxSymbols=60`).
2. `ensure_kline_range()` + `ensure_funding_range()` cache'i doldurur.
3. Her sinyalde kural kosullari (enabled_rules), giris skoru = agirlikli kural oylari; pozisyon yonetimi (TP/SL: ATR-bazli veya %; max_positions; max_drawdown circuit-breaker).
4. Metrikler: PnL, win rate, profit factor, Sharpe, max drawdown, Calmar.

`backtest_runs` tablosuna yazilir; UI `/api/backtest/status/{jobId}` ile takip eder.

## Walk-forward dogrulama
Pencere `WF_FOLDS` (default 3) fold'a bolunur, fold'lar arasi `WF_EMBARGO_DAYS` (default 2) purge ile trade sizmasi engellenir. Her genome tum fold'larda bagimsiz test edilir; fitness = `mean(folds) - ROBUST_LAMBDA(0.5) * std(folds)` — sadece tek rejimde iyi olan overfit genome'lar cezalandirilir.

## Genetik algoritma
- **Genome** (`@dataclass`): name, enabledRules, long/shortMinScore, tp/slPercent, leverage, positionSizePct, maxPositions, signalSource, useAtr, tp/slAtrMult, atrTimeframe, hour/dayStart/End, allowedDays.
- **Populasyon:** `POP_SIZE` (default 8); `OPTIMIZER_PERSIST_POP=1` ise DB'ye serialize.
- **Secim:** turnuva (`TOURNAMENT_K=3`) + `ELITE_COUNT=4` elit korunur.
- **Ureme:** breed pool `POP_SIZE*6=48`; her nesil %20 immigrant (taze rastgele genome) ile cesitlilik korunur. Crossover + `mutate()` (saat/gun araliklari, kural ekle/cikar, parametre jitter).
- **Fitness:** Calmar-agirlikli kompozit (`CALMAR_W*calmar_capped + SHARPE_W*sharpe + leverage cezasi`). Junk (trade < `JUNK_MIN_TRADES=20`, DD < `DD_FLOOR=1%`) elenir; dusuk-trade sonuclar `TRADE_CONF_K=20` ile guven sonumlemesi (`fitness *= T/(T+K)`).

GA loop: her nesil tum genome'lari WF fold'larinda backtest eder, DB'ye yazar, elit sec + breed + mutate, `optimizer:progress` yayar, `CYCLE_PAUSE_MS` bekler.

## Concurrency
| Ayar | Default | Amac |
|---|---|---|
| `WORKER_COUNT` | `max(2, cpu//3)` | paralel genome degerlendirme |
| `asyncio.Semaphore(WORKER_COUNT)` | — | event loop'ta es zamanli backtest siniri |
| `ProcessPoolExecutor` | `OPTIMIZER_PROCESS_POOL=auto` | CPU-bound backtest icin gercek process (GIL bypass); auto/1/0 |
| `TOTAL_HEAP_MAX_BARS` | 8M | tum worker'larda bellek-ici kline tavani |
| `WORKER_HEAP_MAX_BARS` | TOTAL/(WORKER+1) | worker basina heap butcesi |

Heap-ici kolonsal kline cache (`HeapCols`: times/o/h/l/c/v `array('d')`) tekrarli SQLite gidip-gelmesini azaltir.

## Calistirma modu
`OPTIMIZER_IN_SERVER=1` (default) -> server icinde; `0` -> ayri process (`optimizer_main.py`, PM2 `sistem1-v4-optimizer`). Durum `app_config` key'lerinde: `optimizer_status`, `optimizer_log` (ring buffer), `optimizer_population`. Sonuclar `optimizer_results` (+ `_insights`, `_todos`); `deployed_account_id/at` ile canliya alinabilir.
