# sistem1-v4_PY Wiki

sistem1-v3 (TypeScript/Node/React) projesinin **Python (FastAPI)** ile birebir yeniden yazimi. Tamamen izole: v3 ile hicbir kod/DB/port/process paylasmaz. Default **Paper Engine** (Bybit'ten gercek fiyat, sanal cuzdan); gercek/demo Bybit opsiyonel.

Son guncelleme: 2026-06-10

## Sayfalar

- [Mimari](mimari.md) — FastAPI baslangici, agent pipeline, engine'ler, event bus, izolasyon
- [Veritabani](veritabani.md) — SQLite (WAL), 35 migration, ana tablolar, seed
- [Kurallar](kurallar.md) — 27 strateji kurali, skorlama, kaynak filtreleri
- [Indikatorler](indikatorler.md) — RSI/StochRSI/ATR/ADX/EMA/SMA/divergence/NW/WaveTrend
- [Telegram Ingestion](telegram.md) — telethon client, parse, enrich, replikalar
- [Backtest + Optimizer](backtest-optimizer.md) — GA, walk-forward, concurrency, kline/funding cache
- [API + WebSocket](api-websocket.md) — REST route'lari, auth, canli event akisi
- [Calistirma](calistirma.md) — dev/prod, env degiskenleri, port kurallari

## Hizli Bakis

- **Tech:** Python 3.14 + FastAPI + SQLite (sqlite3 + WAL) + Telethon + httpx + React/Vite (frontend) + asyncio
- **Portlar:** backend **3500** (v3: 3401, v2: 3400), frontend dev **5200**, prod'da FastAPI `frontend/dist`'i statik servis eder
- **DB:** `backend/data/sistem1_v4.db` (v3'ten ayri)
- **PM2:** `sistem1-v4`, `sistem1-v4-optimizer`
- **Pipeline:** Scanner -> Strategy (27 kural) -> Risk -> Execution -> Monitor; Learning feedback dongusu
- Detayli mimari/komutlar icin proje kokundeki `CLAUDE.md`.

## Tasarim ilkesi
v3 ile **sayisal parite**: migration'lar ayni isim/sira/SQL, indikatorler ayni hesaplama, kural davranisi karsilastirilabilir.
