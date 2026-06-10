import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from .core.config import config
from .core.logger import create_logger
from .core.secrets import ensure_credential_encryption, get_invalid_credential_account_ids
from .db.migrations import run_migrations
from .db.database import close_db
from .db.seed import seed_accounts
from .middleware.auth import (
    require_auth, is_auth_token_valid, token_from_request, AUTH_COOKIE, ONE_MONTH_SEC, cookie_kwargs,
    validate_auth_config,
)
from .ws import close_event_bridge, init_event_bridge, websocket_endpoint, optimizer_log_bridge_loop
from .agents.monitor import (
    start_global_price_updater,
    stop_global_price_updater,
    start_realtime_position_stream,
    wait_for_monitor_tasks,
)
from .agents.execution import wait_for_inflight_exchange_operations
from .services.bot_manager import auto_start_bots, stop_all_bots, wait_for_bot_tasks
from .agents.backtest_optimizer import start_optimizer, stop_optimizer, wait_for_optimizer_shutdown
from .services.telegram_client import start_telegram_client, stop_telegram_client
from .services.telegram import close_telegram_notifications
from .services.telegram_listener import reparse_old_alerts, cancel_alert_enrichment_tasks
from .agents.nw_sniper import start_nw_sniper, stop_nw_sniper, wait_for_nw_sniper_shutdown
from .agents.replica_channels import (
    start_replica_channels,
    stop_replica_channels,
    wait_for_replica_channels_shutdown,
)
from .agents.replica_compare import (
    start_replica_compare,
    stop_replica_compare,
    wait_for_replica_compare_shutdown,
)
from .agents.replica_tuner import (
    start_replica_tuner,
    stop_replica_tuner,
    wait_for_replica_tuner_shutdown,
)
from .agents.scanner import stop_auto_scan, wait_for_auto_scan_shutdown
from .services.health_services import get_services_health
from .services.bybit_api import close_client as close_bybit_api_client
from .engines.bybit_engine import close_private_client as close_bybit_private_client
from .services.kline_cache import prune_kline_cache

from .routes.accounts import router as accounts_router
from .routes.bot import router as bot_router
from .routes.positions import router as positions_router
from .routes.trades import router as trades_router
from .routes.settings import router as settings_router
from .routes.trading import router as trading_router
from .routes.backtest import cancel_backtest_jobs, router as backtest_router
from .routes.optimizer import router as optimizer_router
from .routes.scanner import router as scanner_router
from .routes.analytics import router as analytics_router
from .routes.alerts import router as alerts_router
from .routes.market import router as market_router
from .routes.chat import router as chat_router
from .routes.rule_labels import router as rule_labels_router
from .routes.replica_compare import router as replica_compare_router
from .routes.replica_tuner import router as replica_tuner_router
from .routes.lean_oracle import router as lean_oracle_router

log = create_logger("server")

_bg_tasks: list[asyncio.Task] = []
_startup_maintenance_tasks: list[asyncio.Task] = []


async def _wait_for_startup_maintenance_tasks() -> None:
    if not _startup_maintenance_tasks:
        return
    await asyncio.gather(*_startup_maintenance_tasks, return_exceptions=True)
    _startup_maintenance_tasks.clear()


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_auth_config()
    run_migrations()
    migrated_credentials = ensure_credential_encryption()
    if migrated_credentials:
        log.info(f"Migrated encrypted credentials to the dedicated key: {migrated_credentials} account(s)")
    invalid_credentials = get_invalid_credential_account_ids()
    if invalid_credentials:
        log.error(
            "Disabled bot auto-start for accounts with undecryptable credentials: "
            f"{', '.join(str(account_id) for account_id in invalid_credentials)}. "
            "Re-enter API credentials for these accounts."
        )
    seed_accounts()
    init_event_bridge(asyncio.get_running_loop())
    _startup_maintenance_tasks.append(asyncio.create_task(asyncio.to_thread(prune_kline_cache)))

    log.info(f"Server running on {config.host}:{config.port}")
    if config.background.price_updater:
        start_global_price_updater(5000)
        start_realtime_position_stream()
    _bg_tasks.append(asyncio.create_task(optimizer_log_bridge_loop()))

    if config.background.auto_start_bots:
        auto_start_bots()
    else:
        log.info("Bot auto-start disabled by AUTO_START_BOTS")

    # Poll dongusu server icinde kossun ki UI Start/Stop (optimizer_control flag'i) islesin.
    # OPTIMIZER_IN_SERVER=false ise GA ayri process'te (optimizer_main.py) kosar; server yalnizca
    # /start /stop /status servis eder, GA dongusunu BASLATMAZ (cift-GA cakismasini onler).
    if config.background.optimizer_in_server:
        _bg_tasks.append(start_optimizer(auto_run=config.background.optimizer))
        if not config.background.optimizer:
            log.info("Optimizer auto-start disabled by AUTO_START_OPTIMIZER (poll loop aktif, UI'dan baslatilabilir)")
    else:
        log.info("Optimizer server-disi modda (OPTIMIZER_IN_SERVER=false): GA ayri process'te kosmali")

    if config.background.reparse_old_alerts:
        try:
            reparse_old_alerts()
        except Exception as err:  # noqa: BLE001
            log.warn(f"reparse error: {err}")

    if config.background.telegram_client:
        _bg_tasks.append(asyncio.create_task(start_telegram_client()))
    else:
        log.info("Telegram client disabled by AUTO_START_TELEGRAM_CLIENT")

    if config.background.replicas:
        start_nw_sniper()
        start_replica_channels()
    if config.background.replica_compare:
        start_replica_compare()
    if config.background.replica_tuner:
        # Tuner'in calismasi icin iki kaynak gerekir:
        #  - replica tarafi: replica_compare buffer'i doldurur (yoksa otomatik baslat)
        #  - gercek taraf: Telegram alert ingestion (kapaliysa tuner kanallari atlar)
        if not config.background.replica_compare:
            log.warn("Replica tuner acik ama replica_compare kapali -> buffer dolsun diye replica_compare baslatiliyor")
            start_replica_compare()
        if not config.background.telegram_client:
            log.warn("Replica tuner acik ama Telegram client kapali -> gercek kaynak akmayacak, "
                     "tuner yer-gercegi olmayan kanallari atlar (parite ogrenemez)")
        start_replica_tuner()

    yield

    try:
        stop_all_bots(preserve_enabled=True)
    except Exception as err:  # noqa: BLE001
        log.warn(f"stop bots error: {err}")
    try:
        stop_global_price_updater()
    except Exception:
        pass
    try:
        stop_optimizer()
    except Exception:
        pass
    try:
        await cancel_backtest_jobs()
    except Exception as err:  # noqa: BLE001
        log.warn(f"cancel backtest jobs error: {err}")
    for fn in (stop_auto_scan, stop_nw_sniper, stop_replica_channels, stop_replica_compare, stop_replica_tuner):
        try:
            fn()
        except Exception:
            pass
    try:
        await wait_for_inflight_exchange_operations()
    except Exception as err:  # noqa: BLE001
        log.warn(f"wait for exchange operations error: {err}")
    try:
        await wait_for_bot_tasks()
        await wait_for_monitor_tasks()
        await wait_for_optimizer_shutdown()
        await wait_for_auto_scan_shutdown()
        await wait_for_nw_sniper_shutdown()
        await wait_for_replica_channels_shutdown()
        await wait_for_replica_compare_shutdown()
        await wait_for_replica_tuner_shutdown()
    except Exception as err:  # noqa: BLE001
        log.warn(f"wait for background task shutdown error: {err}")
    try:
        await stop_telegram_client()
    except Exception:
        pass
    try:
        await cancel_alert_enrichment_tasks()
    except Exception:
        pass
    try:
        await close_telegram_notifications()
    except Exception:
        pass
    await _wait_for_startup_maintenance_tasks()
    for t in _bg_tasks:
        t.cancel()
    if _bg_tasks:
        await asyncio.gather(*_bg_tasks, return_exceptions=True)
        _bg_tasks.clear()
    try:
        await close_bybit_api_client()
    except Exception:
        pass
    try:
        await close_bybit_private_client()
    except Exception:
        pass
    try:
        await close_event_bridge()
    except Exception:
        pass
    close_db()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.cors_origin, "http://localhost:5200", "http://127.0.0.1:5200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/health/services", dependencies=[Depends(require_auth)])
async def health_services():
    try:
        return await get_services_health()
    except Exception as err:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(err)})


@app.post("/api/auth/login")
async def login(request: Request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    token = body.get("token") if isinstance(body, dict) else None
    if not isinstance(token, str) or not is_auth_token_valid(token):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    resp = JSONResponse(content={"success": True})
    resp.set_cookie(AUTH_COOKIE, token, max_age=ONE_MONTH_SEC, **cookie_kwargs(request))
    return resp


@app.post("/api/auth/logout")
async def logout(request: Request):
    resp = JSONResponse(content={"success": True})
    resp.set_cookie(AUTH_COOKIE, "", max_age=0, **cookie_kwargs(request))
    return resp


@app.get("/api/auth/status")
async def auth_status(request: Request):
    return {"authenticated": is_auth_token_valid(token_from_request(request))}


@app.websocket("/ws")
async def ws_route(websocket: WebSocket):
    await websocket_endpoint(websocket)


_auth = [Depends(require_auth)]
app.include_router(accounts_router, prefix="/api/accounts", dependencies=_auth)
app.include_router(bot_router, prefix="/api/bot", dependencies=_auth)
app.include_router(positions_router, prefix="/api/positions", dependencies=_auth)
app.include_router(trades_router, prefix="/api/trades", dependencies=_auth)
app.include_router(settings_router, prefix="/api/settings", dependencies=_auth)
app.include_router(trading_router, prefix="/api/trading", dependencies=_auth)
app.include_router(backtest_router, prefix="/api/backtest", dependencies=_auth)
app.include_router(optimizer_router, prefix="/api/optimizer", dependencies=_auth)
app.include_router(scanner_router, prefix="/api/scanner", dependencies=_auth)
app.include_router(analytics_router, prefix="/api/analysis", dependencies=_auth)
app.include_router(alerts_router, prefix="/api/alerts", dependencies=_auth)
app.include_router(market_router, prefix="/api/market", dependencies=_auth)
app.include_router(chat_router, prefix="/api/chat", dependencies=_auth)
app.include_router(rule_labels_router, prefix="/api/rule-labels", dependencies=_auth)
app.include_router(replica_compare_router, prefix="/api/replica-compare", dependencies=_auth)
app.include_router(replica_tuner_router, prefix="/api/replica-tuner", dependencies=_auth)
app.include_router(lean_oracle_router, prefix="/api/lean-oracle", dependencies=_auth)

_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"error": "API route not found"})
        candidate = (_DIST / full_path).resolve()
        # dist disina cikan path'ler (.., encoded dot-segment) index.html'e duser
        if full_path and candidate.is_relative_to(_DIST.resolve()) and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(_DIST / "index.html"))
