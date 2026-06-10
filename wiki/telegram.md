# Telegram Ingestion

Telegram kanallarindan sinyalleri okuyup `alerts` tablosuna yazan alt sistem.

- `app/services/telegram_client.py` — Telethon `TelegramClient`, kanal eslesme, NewMessage handler
- `app/services/telegram_listener.py` — parse, ingest kaydi, enrichment
- `app/services/alert_parser.py` — regex parse
- `app/services/alert_signals.py` — `signal_source` -> kaynak tipleri eslemesi

## Kanallar ve kaynaklar
4 kaynak: `4s_sniper`/`sniper`, `hammer`, `fr`, `m1_a`. Config: `TELEGRAM_CHANNEL_SNIPER/HAMMER/FR/M1A`. Her kanal ID'si `-100{id}`, `-{id}`, ciplak-id varyantlariyla `CHANNEL_MAP`'e eklenir; gelen mesaj hangi bicimde gelirse gelsin eslesir. Telethon: `connection_retries=None` (sonsuz), `retry_delay=5s`, `auto_reconnect=True`, `flood_sleep_threshold=60`.

## Akis
1. NewMessage handler -> `process_incoming_alert(text, source)`.
2. `alert_parser`: symbol (`#?\$?([A-Z0-9]+)/USDT`), direction (UP/DOWN/LONG/SHORT/BUY/SELL), stars (yildiz sayimi), current/previous price, RSI/SRSI (timeframe-key'li), boost/drop %. `detect_source_type` `_local` gibi ekleri temizler.
3. `alerts` tablosuna insert (source_type, signal_type, rsi_data, srsi_data, price, boost_value, stars...).
4. **Enrichment (fire-and-forget):** `enrich_bybit_fr(alert_id, symbol)` Bybit guncel funding'i cekip `alerts.bybit_fr`'i doldurur.
5. **Ingest log:** `telegram_ingest_events(source_type, status, symbol, direction, error, raw_message)` — basarisiz parse gorunur kalir.

`reparse_old_alerts()` saklanan `raw_message`'lari yeniden parse eder (`AUTO_REPARSE_OLD_ALERTS`).

## signal_source eslemesi
`alert_signals.get_source_types("hammer+sniper+fr")` -> `["hammer","4s_sniper","sniper","fr"]`. `scanner+*` ve `all` on ekleri desteklenir. Bot bu kaynaklardan taze alert'leri aday yapar (bkz. [Mimari](mimari.md)).

## Replikalar
Telegram alert'lerini canli trade'den bagimsiz analiz edip karsilastiran alt sistem (`AUTO_START_REPLICAS/COMPARE/TUNER`):
- `agents/nw_sniper.py` — Nadaraya-Watson + RSI divergence (sniper/4H momentum)
- `agents/replica_channels.py` — kaynak/kanal bazli kural degerlendirme
- `agents/replica_buffer.py` — bellek-ici sinyal/scan buffer (kanal basina max ~2000)
- `agents/replica_compare.py` / `replica_tuner.py` / `replica_params.py` — performans karsilastirma + otomatik parametre tuning
- Route'lar: `/api/replica-compare`, `/api/replica-tuner` (bkz. [API + WebSocket](api-websocket.md))

## Saglik
`app/services/telegram_health.py` — 4 kaynak icin stale esikleri (sniper/hammer 180dk, fr 90dk, m1_a 15dk); 24s mesaj/parse sayilari `alerts` ve `telegram_ingest_events`'ten.
