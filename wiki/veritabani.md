# Veritabani

SQLite, `app/db/database.py`. Tek global baglanti, `threading.RLock()` ile thread-safe. PRAGMA: `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=15s`, `temp_store=MEMORY`, `foreign_keys=ON`. Yol: `data/sistem1_v4.db` (`DATABASE_PATH` ile override).

Fonksiyonlar: `init_db`, `get_db`, `close_db` (WAL checkpoint + close), `query_one`, `query_all`, `execute`, `executemany`, `transaction()` (context manager).

## Migration'lar
`app/db/migrations.py` — `run_migrations()`, **35 migration** (v3 ile ayni isim/sira/SQL). `migrations` tablosu uygulananlari izler. Onemli kilometre taslari:

- `001-initial` — accounts, bot_configs, trades, open_positions, equity_snapshots, paper_wallets, alerts, learning_weights, user_preferences, app_config + index'ler
- `002-real-accounts` — api_key/api_secret/engine
- `003-alert-sources`, `009-fr-fields`, `014-alert-stars` — alert alanlari (RSI/SRSI/FR/stars)
- `004-signal-source`, `007-position-size-pct`, `008-bot-enabled`, `010-rule-sources` — bot_configs alanlari
- `006-weight-history` — agirlik degisim izi
- `011..013, 027, 029, 031, 034` — optimizer_results + metrikler (profit_factor, sharpe, calmar, max_drawdown, generation, backtest_days, deployed_account_id/at)
- `015-delist-warnings`, `016/021-bot-logs`, `018-rule-labels`, `019-position-intra-range`, `020-telegram-ingest-events`, `023-exchange-orders`
- `017/024` — Trade Genius eklenip kaldirildi; `022/032` — Trader Club eklenip kaldirildi
- `025-fix-trade-duration-utc`, `026-trade-trigger-meta` (trigger_source/stars/min_score_used/note)
- `027-backtest-optimizer` — kline_cache, kline_cache_meta, backtest_runs
- `030-funding-cache` — funding_cache, funding_cache_meta, alerts.bybit_fr
- `028/033/035` — performans index'leri

## Ana tablolar
- **accounts** — name, type (paper/real/demo), strategy, balance, initial_balance, leverage, color, is_default, is_active, engine, api_key, api_secret
- **bot_configs** (account_id unique) — long/short_min_score, leverage, max_positions, tp/sl_percent, max_drawdown, scan_interval, trailing_stop/percent, enabled_rules, rule_sources, signal_source, alert_freshness_minutes, alert_score_boost, position_size_pct, bot_enabled
- **trades** — symbol, side, size, entry/exit_price, leverage, pnl, pnl_percent, fee, status (open/closed), active_rules, signal_score, entry/exit_reason, trigger_source/stars, min_score_used, opened/closed_at, duration_seconds
- **open_positions** (account_id+symbol+side unique) — entry/mark_price, size, leverage, unrealized_pnl, tp/sl_price, trailing_*, intra_high/low
- **paper_wallets** (account_id unique) — balance, initial_balance, total_pnl, total/winning/losing_trades
- **equity_snapshots** — equity, balance, unrealized_pnl, drawdown, recorded_at
- **alerts** — symbol, direction, signal_type, source/source_type, raw_message, RSI/SRSI (1m..1d), boost_value, stars, price, funding_rate, bybit_fr, matched_with_bot
- **learning_weights** (account_id+rule_key unique) + **weight_history** — bkz. [Kurallar](kurallar.md) ogrenme
- **optimizer_results / _insights / _todos**, **backtest_runs** — bkz. [Backtest + Optimizer](backtest-optimizer.md)
- **kline_cache(_meta)**, **funding_cache(_meta)** — OHLCV ve funding cache (symbol/interval/ts)
- **delist_warnings**, **bot_logs**, **exchange_orders**, **rule_labels**, **telegram_ingest_events**, **user_preferences**, **app_config**

## Seed
`app/db/seed.py` — `seed_accounts()` (bos ise; `DISABLE_SEED` ile kapanir). 5 paper hesap: **Conservative** (default, lev 2, tp5/sl3, 30s), **Aggressive** (lev 5, tp8/sl5, 15s), **Scalper** (lev 3, tp2/sl1.5, 10s), **Trend Follower** (lev 2, tp10/sl5, 60s; enabled_rules: multi_tf+h1_trend+volume+conviction), **Custom** (varsayilan). Her hesaba account + bot_configs + paper_wallets satiri.
