import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..services.bybit_api import (
    get_top_gainers,
    get_ticker,
    get_klines,
    get_klines_range,
    is_tradable_linear_symbol,
)

router = APIRouter()

VALID_INTERVALS = {"1", "3", "5", "15", "30", "60", "120", "240", "D", "W"}
SYMBOL_RE = re.compile(r"^[A-Z0-9_-]{2,20}$")
_INT_RE = re.compile(r"^\d+$")


@router.get("/top-gainers")
async def top_gainers():
    try:
        gainers = await get_top_gainers(20)
        return gainers
    except Exception as err:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": public_error(err, "scanner")})


@router.get("/ticker/{symbol}")
async def ticker(symbol: str):
    try:
        sym = symbol.upper()
        if not SYMBOL_RE.match(sym):
            return JSONResponse(status_code=400, content={"error": "Invalid symbol"})
        if not await is_tradable_linear_symbol(sym):
            return JSONResponse(status_code=404, content={"error": "Symbol not tradable on Bybit linear USDT"})
        result = await get_ticker(sym)
        if not result:
            return JSONResponse(status_code=404, content={"error": "Symbol not found"})
        return result
    except Exception as err:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": public_error(err, "scanner")})


@router.get("/klines/{symbol}")
async def klines(symbol: str, request: Request):
    try:
        sym = symbol.upper()
        if not SYMBOL_RE.match(sym):
            return JSONResponse(status_code=400, content={"error": "Invalid symbol"})
        if not await is_tradable_linear_symbol(sym):
            return JSONResponse(status_code=404, content={"error": "Symbol not tradable on Bybit linear USDT"})
        interval = (request.query_params.get("interval") or "5").upper()
        if interval not in VALID_INTERVALS:
            return JSONResponse(status_code=400, content={"error": "Invalid interval"})
        start_text = str(request.query_params.get("start") or "").strip()
        end_text = str(request.query_params.get("end") or "").strip()
        start = int(start_text) if _INT_RE.match(start_text) else None
        end = int(end_text) if _INT_RE.match(end_text) else None
        if start is not None and end is not None and end > start:
            range_klines = await get_klines_range(sym, interval, start, end)
            return range_klines
        limit_text = str(request.query_params.get("limit") or "").strip()
        parsed_limit = int(limit_text) if _INT_RE.match(limit_text) else None
        limit = min(parsed_limit, 1000) if parsed_limit is not None and parsed_limit > 0 else 200
        return await get_klines(sym, interval, limit)
    except Exception as err:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": public_error(err, "scanner")})
