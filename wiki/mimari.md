# Mimari

## Izolasyon (v3'ten)
v4_PY, v3 ile hicbir sey paylasmaz: ayri Python kodu (FastAPI), ayri DB (`data/sistem1_v4.db`), ayri port (3500), ayri PM2 app'leri (`sistem1-v4`, `sistem1-v4-optimizer`), ayri git deposu.

## FastAPI baslangici
`app/main.py` — FastAPI `lifespan` ile baslar (port 3500, host `127.0.0.1` dev / `0.0.0.0` prod `APP_ENV=production`):

1. `validate_auth_config()` — auth token dogrulama
2. `run_migrations()` — 35 migration
3. `ensure_credential_encryption()` — kimlik bilgilerini `enc:v1`'e tasi
4. `seed_accounts()` — bos ise 5 paper hesap
5. `init_event_bridge()` — WS event kopru
6. `prune_kline_cache()` — bakim
7. Env flag'lerine gore kosullu: `start_global_price_updater(5000ms)` + realtime position stream (`ENABLE_PRICE_UPDATER`), `auto_start_bots()` (`AUTO_START_BOTS`), `start_optimizer()` (`AUTO_START_OPTIMIZER`+`OPTIMIZER_IN_SERVER`), `reparse_old_alerts()`, `start_telegram_client()`, replica agent'lari, delist checker.

Shutdown: tum bot/updater/optimizer/backtest/scanner/replica/telegram task'larini nazikce durdurur.

Frontend: `frontend/dist` varsa `/assets` mount edilir, API disindaki tum yollar SPA `index.html`'e fallback eder.

## Agent Pipeline
Bagimsiz agent'lar `app/core/event_bus.py` (pub-sub, async-farkinda) ile haberlesir.

```
Scanner -> Strategy (27 kural) -> Risk -> Execution -> Monitor
   ^                                                      |
   +------------------- Learning (feedback) --------------+
```

Agent'lar (`app/agents/`):
- **strategy.py** — `analyze_symbol`: timeframe klines ceker, kurallari calistirir, agirlikla skor toplar
- **scanner.py** — top gainers tarar (default 20), kosullu sinyal uretir
- **risk.py** — cooldown, max-positions, hesap kilidi (atomik pozisyon acma)
- **execution.py** — emri engine'e yonlendirir (paper/bybit), in-flight islem yonetimi
- **monitor.py** — canli pozisyon takibi, TP/SL/trailing ile otomatik kapatma, cooldown
- **learning.py** — DB'den ogrenilen kural agirliklari (`get_weights`)
- **historical_strategy.py** — backtest icin cache'li kline uzerinde strateji
- **nw_sniper.py / replica_*.py** — Telegram alert replikalari (kanal bazli analiz, karsilastirma, tuning)
- **backtest_optimizer.py** — GA optimizer (bkz. [Backtest + Optimizer](backtest-optimizer.md))

## Event Bus
`app/core/event_bus.py` — `event_bus` singleton; `on/off/emit`. Coroutine handler'lari `run_coroutine_threadsafe` ile cagrilir. Event isimleri (`app/ws.py`): `scan:complete`, `signal:generated`, `risk:approved/rejected/circuit_breaker`, `order:placed/filled`, `position:opened/closed/updated`, `alert:received`, `learning:updated`, `bot:log/started/stopped`, `delist:new/escalated`, `optimizer:log/progress/cycle-complete`. WS yayini icin bkz. [API + WebSocket](api-websocket.md).

## Engine'ler
`app/engines/trade_engine.py` — `TradeEngine` ABC: `place_order`, `close_position`, `get_positions`, `get_balance`, `set_leverage`, `set_tp_sl`, `update_mark_prices`. `registry.py` hesabin `engine` alanina gore secer.

- **paper_engine.py** (`name="paper"`, default) — sanal cuzdan, gercek fiyat (`get_last_price`), slippage + taker fee, pozisyon basina kilit, TP/SL kaldiraca gore.
- **bybit_engine.py** (real + demo) — HMAC SHA256 imza, REST (private WS yok -> REST fill-fallback), oneway pozisyon modu, adaptif rate-limit cooldown, remote/orphan pozisyon mutabakati. Kimlik bilgileri `enc:v1` AES-GCM ile sifreli (`core/secrets.py`); eski plaintext geriye donuk okunur.

## Hata izolasyonu
Logger UTF-8 (Windows pm2 cp1254 emoji sorununa fallback). Bybit REST adaptif cooldown (429'da 60s'e kadar). Telegram telethon sonsuz reconnect.

## Veri akisi
Detay: [Veritabani](veritabani.md), [Kurallar](kurallar.md). Market verisi `services/bybit_api.py` (REST + TTL cache: ticker 15s, kline ~30s, funding 5dk); WS-first cache stub (`bybit_ws.py`) henuz no-op.
