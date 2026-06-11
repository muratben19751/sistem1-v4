# CLAUDE.md — sistem1-v4_PY

sistem1-v3 (TypeScript/Node/React) projesinin **Python** ile birebir yeniden yazimi.
**Tamamen izole:** v3 ile hicbir kod/DB/port/process paylasilmaz.

## Izolasyon
- Backend: Python (FastAPI), kendi `.venv`'i
- DB: kendi SQLite dosyasi `backend/data/sistem1_v4.db` (v3'ten ayri)
- Port: backend **3500** (v3: 3401, v2: 3400)
- Frontend: korunan React (Vite), dev portu **5200**, prod'da FastAPI statik servis eder
- pm2: `sistem1-v4`, `sistem1-v4-optimizer` (v3'ten ayri)
- Ayri git deposu

## Yapi
```
backend/
  app/
    core/        config.py, logger.py, event_bus.py
    db/          database.py (sqlite3+WAL), migrations.py (39 migration), seed.py
    lib/         indicators.py (RSI/StochRSI/SMA/EMA/ATR/ADX/divergence/NadarayaWatson/WaveTrend)
    services/    bybit_api, telegram, alert_parser, kline_cache, ...
    engines/     trade_engine (ABC), paper_engine, bybit_engine
    strategies/  rules/rule_01..rule_28, rule_registry.py
    agents/      scanner, strategy, risk, execution, monitor, learning, optimizer, ...
    routes/      FastAPI router'lar (accounts, bot, positions, trades, lean_oracle, replica_tuner, ...)
    main.py      FastAPI app (v3 index.ts karsiligi)
    optimizer_main.py
  tools/
    lean_oracle/ LEAN dogrulama kahini (export -> gercek LEAN/Docker -> compare); izole .venv
  requirements.txt, .env
frontend/        v3'ten kopyalanan React (Vite proxy -> 3500); sayfalar: ..., LeanOracle (/lean)
```

## Calistirma
```bash
cd backend
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 3500 --reload
```

## Port kurallari (v3 birebir port)
- Her agent/kural kendi dosyasinda, tek sorumluluk
- DB migration'lar v3 ile ayni isim/sira/SQL (birebir sema)
- Indikatorler birebir ayni hesaplama (sayisal parite)
- Davranis v3 ile karsilastirilabilir olmali

## Asama durumu
- [x] Faz 1: cekirdek (config, logger, event_bus, db, migrations, indicators)
- [x] Faz 2: bybit_api, paper_engine, trade_engine, seed
- [x] Faz 3: 27 kural + rule_registry, strategy/risk/execution/monitor/scanner/bot_manager
- [x] Faz 4: REST API route'lari (15) + WS + main.py -> CALISIR dashboard (uctan uca test edildi)
- [x] Faz 5: backtest engine + optimizer (GA, asyncio.Semaphore in-process) + kline_cache + funding_cache (run_backtest + optimizer uctan uca calisir)
- [x] Faz 6: telegram (telethon client + alert_parser + listener) + replikalar (nw_sniper/channels/buffer/compare) (alert ingestion + replica-compare uctan uca calisir)
- [x] Real bybit/demo engine (bybit_engine.py, HMAC imza + REST fill-fallback; registry bybit/demo/paper secer). Kimlik bilgileri `enc:v1` AES-GCM ile saklanir; eski plaintext de geriye donuk okunur. Private WS yok (REST fallback).
- [x] Faz 7: LEAN dogrulama kahini (oracle) + gercekci backtest motoru (bkz. asagidaki bolum)
- [ ] Opsiyonel kalan: chat route (anthropic API key gerekir), private WS (real-time fill/pozisyon akisi)

## LEAN Oracle + Gercekci Backtest Motoru (Faz 7)

**Amac:** Kendi `run_backtest()` motorumun **icra matematigini** (giris->TP/SL/cikis, fee, slippage,
kaldirac, portfoy, drawdown) QuantConnect **LEAN**'in kanitlanmis motoruyla **bagimsiz** dogrulamak.
Sinyal/skorlama (27 kural) LEAN'de YENIDEN YAZILMAZ — kendi motorumun urettigi girisler LEAN'e beslenir;
LEAN yalnizca icra simulasyonu yapar. Boylece en cok gizli-bug barindiran mekanik icra kiyaslanir.

- **`tools/lean_oracle/`** (izole, salt-okunur DB): `export.py` (run_backtest -> signals/config/data CSV),
  `algorithm/main.py` (LEAN QCAlgorithm, girisleri replay eder), `compare.py` (metrik-bazli parite +
  mechanical/modeling/definitional siniflandirma -> PASS/MINOR/INVESTIGATE), `run.py` (`--mode lean|stub`,
  `--strategy`, `--top N` batch). Gercek kosum: lean CLI + Docker.
- **Route:** `/api/lean-oracle/{status,runs,report,run,run-status}` (salt-okunur + `POST /run` UI'dan tetikler).
- **Sayfa `/lean`:** parite raporu; OptimizerLab LEAN kolonuna tiklayinca `?strategy=<ad>` ile acilir;
  kosum yoksa **"Kosum Yap"** butonu (Docker varsa lean, yoksa stub).
- **Leaderboard:** her stratejide `leanParity` kolonu (UYUMLU/KISMI/INCELE).

**Gercekci icra modlari** (motorda bayrak, **varsayilan KAPALI** -> mevcut sonuclari bozmaz; oracle export
+ optimizer'da **ACIK** -> backtest canliya sadik). Backtest-iyimserliginin uc kaynagini giderir:
- `_nextBarExit` — cikis, TP/SL'in gectigi barda degil **sonraki bar acilisinda** dolar (canli monitor gibi).
- `_nextBarEntry` — giris, sinyal barinda degil **sonraki bar acilisinda** dolar (LEAN/canli market-fill).
- `_reentryGapBars` — ayni sembol kapandiktan sonra **N bar** gecmeden yeniden girilmez (settlement).

Pratik bulgu: win-rate paritesi top stratejilerde siki (≤%2-4); kalan PnL/Total-Trades farki **tanimsal/
modelleme** (DD realized-vs-marked, metrik formulleri, fill granularitesi) — bug degil. Canli PnL beklentisi
icin LEAN'in (daha muhafazakar) rakamina yaslan. Optimizer `OPTIMIZER_NEXT_BAR_EXIT` env ile kapatilabilir.

## Calistirma (dogrulandi)
```bash
cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 3500
# -> 39 migration + 5 paper hesap seed; FastAPI 3500'de React dist + REST API + WS + canli Bybit servis eder
cd frontend && npm run dev   # dev modu (vite 5200 -> proxy 3500)
```

Opsiyonel kalan stub'lar: chat route ve Bybit private/public WebSocket transportu. Canli emir yolu REST fallback kullanir.

## Surec yonetimi (pm2 watchdog)
- Backend'i **pm2 daemon'i** yonetir (`sistem1-v4`, fork mode): uvicorn oldurulurse pm2 saniyeler icinde
  yeniden baslatir. pm2 PATH'te DEGIL; yerel kurulumdan cagrilir:
  `node C:\myAI_Projects\sistem1\node_modules\pm2\bin\pm2 list|restart sistem1-v4|logs sistem1-v4`
- Kod degisikligini canliya almak icin uvicorn process'ini oldurmek yeterli (pm2 yeni kodla acar)
  ya da `pm2 restart sistem1-v4`.
- Optimizer process'i (`python -m app.optimizer_main`) pm2'de KAYITLI DEGIL; elle baslatilir, watchdog'u yok.
- DIKKAT: eski `sistem1` (v1) uygulamasi da IPv6 `::`:3500'u dinler -> tarayicida her zaman
  `127.0.0.1:3500` kullan, `localhost:3500` yanlis uygulamaya gidebilir.

## Bakim
- `services/db_maintenance.py`: gunluk budama — bot_logs 14g, telegram_ingest_events 90g, alerts 430g,
  kline_cache icin mevcut `prune_kline_cache` (400g + stale) yeniden kosulur. equity_snapshots BILEREK
  budanmaz (max-drawdown peak'i tum gecmisten hesaplanir). Pencereler `DB_KEEP_*` env'leriyle ayarlanir.
