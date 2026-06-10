# API + WebSocket

FastAPI route'lari `app/main.py`'de kayitli (tum `/api/*`, `/api/health` ve `/api/auth/*` ve `/ws` haric, `Depends(require_auth)`).

## Auth
`app/middleware/auth.py` — `sistem1_auth` cookie (30 gun) veya Bearer token; `is_auth_token_valid` token'i `AUTH_TOKEN` ile karsilastirir (min uzunluk `AUTH_TOKEN_MIN_LENGTH`, default 24). Endpoint'ler: `POST /api/auth/login` (cookie set), `POST /api/auth/logout`, `GET /api/auth/status`. Public: `GET /api/health`, `GET /api/health/services` (korumali).

## Route'lar
| Prefix | Dosya | Onemli endpoint'ler |
|---|---|---|
| `/api/accounts` | accounts.py | `GET /`, `GET /{id}`, `POST /`, `PUT /{id}/config`, `PUT /{id}/credentials`, `DELETE /{id}`, `POST /{id}/reset`, `POST /{id}/default`, `GET/PUT /{id}/equity` |
| `/api/bot` | bot.py | `GET /status`, `POST /start`, `POST /stop`, `GET /logs`, `GET /logs/count`, `GET /logs/export` |
| `/api/positions` | positions.py | `GET /` (`?accountId=`) |
| `/api/trades` | trades.py | `GET /`, `GET /signal-summary`, `GET /metrics`, `GET /{id}` |
| `/api/settings` | settings.py | `GET /`, `PUT /{key}` |
| `/api/trading` | trading.py | manuel emir |
| `/api/backtest` | backtest.py | `POST /`, `GET /status/{jobId}`, `GET /list`, `POST /cancel/{jobId}` |
| `/api/optimizer` | optimizer.py | `GET /status`, `POST /start`, `POST /stop`, `GET/POST /control` |
| `/api/scanner` | scanner.py | `GET /top-gainers`, `GET /ticker/{symbol}`, `GET /klines/{symbol}` |
| `/api/analysis` | analytics.py | sembol bazli strateji analizi |
| `/api/alerts` | alerts.py | `GET /`, `GET /range`, `/stats` |
| `/api/market` | market.py | `GET /tickers`, `GET /prices`, `GET /funding`, `GET /funding/{symbol}/history` |
| `/api/chat` | chat.py | 501 (uygulanmadi; Anthropic key gerekir) |
| `/api/rule-labels` | rule_labels.py | `GET /`, `PUT /{key}`, `DELETE /{key}`, `DELETE /` |
| `/api/replica-compare` | replica_compare.py | `GET /`, `POST /start`, `POST /stop` |
| `/api/replica-tuner` | replica_tuner.py | `GET /`, `POST /start`, `POST /stop`, `POST /run-once`, `POST /reset` |
| `/api/lean-oracle` | lean_oracle.py | `GET /status`, `GET /runs` (read-only) |

## WebSocket
`app/ws.py` — `GET /ws`. Global `_clients` set; broadcast `asyncio.Queue(maxsize=1000)` + `_broadcast_worker`. `event_bus.on(name, handler)` ile core modullerine abone olur. Mesaj: `{"type", "data", "timestamp": ISO8601Z}`. Client basina 2s send timeout; olu baglanti otomatik atilir; kuyruk tasmasi 100'de bir loglanir.

Event tipleri: `scan:complete`, `signal:generated`, `risk:approved/rejected/circuit_breaker`, `order:placed/filled`, `position:opened/closed/updated`, `alert:received`, `learning:updated`, `bot:log/started/stopped`, `delist:new/escalated`, `optimizer:log/progress/cycle-complete`.

Akis: core modul `event_bus.emit("order:placed", {...})` -> handler kuyruga koyar -> worker tum client'lara `send_text` -> frontend JSON parse edip UI gunceller.
