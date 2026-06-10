# Calistirma

## Portlar (v3 ile birebir, izole)
- Backend FastAPI: **3500** (v3: 3401, v2: 3400)
- Frontend Vite dev: **5200** (proxy `/api` ve `/ws` -> 3500)
- Prod: FastAPI `frontend/dist`'i statik servis eder (ayri frontend sunucusu gerekmez)
- PM2: `sistem1-v4`, `sistem1-v4-optimizer`

## Dev
```bash
cd backend
python -m venv .venv && .venv/Scripts/activate     # Windows
pip install -r requirements.txt
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 3500 --reload
# ayri terminal:
cd frontend && npm run dev                          # vite 5200 -> proxy 3500
```
Baslangicta 35 migration + 5 paper hesap seed; FastAPI 3500'de REST + WS + canli Bybit servis eder.

## Prod
`APP_ENV=production` ile host `0.0.0.0`. Frontend once `npm run build` (-> `frontend/dist`), sonra backend uvicorn. PM2 app'leri ayri (`sistem1-v4`, `sistem1-v4-optimizer`).

## Test
```bash
cd backend && .venv/Scripts/python.exe -m pytest -q
```
`pytest.ini`: `asyncio_mode=auto`, `testpaths=tests`. (Son calismada 327 test gecti.)

## Onemli env degiskenleri
```env
APP_ENV=                 # production -> 0.0.0.0
PORT=3500
HOST=
AUTH_TOKEN=dev-token     # min uzunluk AUTH_TOKEN_MIN_LENGTH (24)
CORS_ORIGIN=http://localhost:5200
DATABASE_PATH=           # default data/sistem1_v4.db
DISABLE_SEED=            # seed'i kapat

# Baslangic flag'leri (lifespan'da kosullu)
ENABLE_PRICE_UPDATER=true
AUTO_START_BOTS=
AUTO_START_TELEGRAM_CLIENT=
AUTO_REPARSE_OLD_ALERTS=
AUTO_START_OPTIMIZER=
OPTIMIZER_IN_SERVER=true   # false -> optimizer_main.py ayri process
AUTO_START_REPLICAS=
AUTO_START_REPLICA_COMPARE=
AUTO_START_REPLICA_TUNER=
AUTO_START_DELIST_CHECKER=

# Paper
PAPER_INITIAL_BALANCE=10000
PAPER_SLIPPAGE=0.05
PAPER_MAKER_FEE=0.02
PAPER_TAKER_FEE=0.055

# Bybit (real/demo opsiyonel)
BYBIT_API_KEY=
BYBIT_API_SECRET=
BYBIT_TESTNET=
BYBIT_POSITION_MODE=oneway
BYBIT_RATE_LIMIT_DELAY_MS=150
BYBIT_PRIVATE_RATE_LIMIT_DELAY_MS=500

# Kimlik sifreleme (enc:v1 AES-GCM)
CREDENTIAL_ENCRYPTION_KEY=
CREDENTIAL_KEY_FILE=      # default data/.credential-key

# Telegram
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_SESSION_STRING=
TELEGRAM_CHANNEL_SNIPER=
TELEGRAM_CHANNEL_HAMMER=
TELEGRAM_CHANNEL_FR=
TELEGRAM_CHANNEL_M1A=

# Chat (opsiyonel)
ANTHROPIC_API_KEY=
```

## Kimlik bilgisi sifreleme
`core/secrets.py` — `enc:v1` AES-GCM. Anahtar onceligi: `CREDENTIAL_ENCRYPTION_KEY` -> `CREDENTIAL_KEY_FILE` (`data/.credential-key`, 0o600) -> `AUTH_TOKEN` -> "dev-token"; `SHA256(material)` -> 32-byte. `ensure_credential_encryption()` baslangicta eski plaintext/farkli sifreli kayitlari tasir; cozulemeyen kimlikli hesabin botu otomatik kapatilir.
