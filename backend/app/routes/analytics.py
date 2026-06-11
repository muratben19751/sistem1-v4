import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..core.errors import public_error
from ..db.database import query_one
from ..agents.strategy import analyze_symbol
from ..services.bybit_api import is_tradable_linear_symbol
from ..agents.scanner import (
    run_scan,
    get_last_scan_result,
    start_auto_scan,
    stop_auto_scan,
    is_scan_running,
    normalize_scan_interval_sec,
    normalize_scan_limit,
)
from ..strategies.rule_registry import get_all_rule_names

router = APIRouter()

SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,30}USDT$")
_INT_RE = re.compile(r"^\d+$")

_NOT_FOUND = object()


def parse_account_id(raw) -> int | None:
    text = str(raw if raw is not None else "").strip()
    if not _INT_RE.match(text):
        return None
    value = int(text)
    return value if value > 0 else None


def parse_rules_query(raw):
    if raw is None:
        return None
    text = str(raw)
    rules = [r.strip() for r in text.split(",") if r.strip()]
    return rules if len(rules) > 0 else None


def get_enabled_rules_for_account(account_id: int):
    row = query_one("SELECT enabled_rules FROM bot_configs WHERE account_id = ?", (account_id,))
    if not row:
        return _NOT_FOUND
    enabled = row["enabled_rules"]
    if enabled == "__none__":
        return []
    if enabled:
        return [r.strip() for r in enabled.split(",") if r.strip()]
    return None


async def _read_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return body if isinstance(body, dict) else {}


def _serialize_kline(k) -> dict:
    return {"time": k.time, "open": k.open, "high": k.high, "low": k.low, "close": k.close, "volume": k.volume}


def _serialize_market_data(md) -> dict:
    out = {
        "symbol": md.symbol,
        "klines": {key: [_serialize_kline(k) for k in kl] for key, kl in md.klines.items()},
        "ticker": md.ticker,
        "fundingRate": md.funding_rate,
        "openInterest": md.open_interest,
        "openInterestChange": md.open_interest_change,
        "rsi": md.rsi,
        "stochRsi": md.stoch_rsi,
        "volumeChange": md.volume_change,
        "fundingRateHistory": md.funding_rate_history or [],
        "fundingIntervalHours": md.funding_interval_hours,
    }
    if md.prior_results is not None:
        out["priorResults"] = [{"score": r.score, "side": r.side, "detail": r.detail} for r in md.prior_results]
    if md.trigger_source is not None:
        out["triggerSource"] = md.trigger_source
    if md.trigger_alert is not None:
        out["triggerAlert"] = md.trigger_alert
    return out


def _serialize_signal(signal) -> dict:
    return {
        "symbol": signal.symbol,
        "totalScore": signal.total_score,
        "side": signal.side,
        "rules": signal.rules,
        "marketData": _serialize_market_data(signal.market_data),
        "timestamp": signal.timestamp,
    }


@router.get("/analyze/{symbol}")
async def analyze(symbol: str, request: Request):
    try:
        raw_account_id = request.query_params.get("accountId")
        account_id = parse_account_id(raw_account_id) if raw_account_id is not None else None
        if raw_account_id is not None and account_id is None:
            return JSONResponse(status_code=400, content={"error": "Invalid accountId"})

        enabled_rules = parse_rules_query(request.query_params.get("rules"))
        if enabled_rules is None and account_id is not None:
            account_rules = get_enabled_rules_for_account(account_id)
            if account_rules is _NOT_FOUND:
                return JSONResponse(status_code=404, content={"error": "Account not found"})
            enabled_rules = account_rules

        sym = symbol.upper()
        if not SYMBOL_RE.match(sym):
            return JSONResponse(status_code=400, content={"error": "Invalid symbol"})
        if not await is_tradable_linear_symbol(sym):
            return JSONResponse(status_code=404, content={"error": "Symbol not tradable on Bybit linear USDT"})
        result = await analyze_symbol(sym, enabled_rules, account_id if account_id is not None else None)
        return _serialize_signal(result)
    except Exception as err:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": public_error(err, "analytics")})


@router.get("/rules")
async def rules():
    return get_all_rule_names()


@router.post("/scan")
async def scan(request: Request):
    try:
        body = await _read_body(request)
        limit = normalize_scan_limit(body.get("limit") or 20)
        result = await run_scan(limit)
        return result
    except Exception as err:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": public_error(err, "analytics")})


@router.get("/scan/last")
async def scan_last():
    result = get_last_scan_result()
    if not result:
        return {"timestamp": None, "symbols": [], "signals": []}
    return result


@router.post("/scan/start")
async def scan_start(request: Request):
    body = await _read_body(request)
    interval = normalize_scan_interval_sec(body.get("interval") or 30)
    start_auto_scan(interval)
    return {"success": True, "interval": interval}


@router.post("/scan/stop")
async def scan_stop():
    stop_auto_scan()
    return {"success": True}


@router.get("/scan/status")
async def scan_status():
    return {"running": is_scan_running()}
