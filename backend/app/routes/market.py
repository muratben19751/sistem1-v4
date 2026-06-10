from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..services.bybit_api import get_tickers, get_funding_rate_history, to_finite

router = APIRouter()


@router.get("/tickers")
async def tickers():
    try:
        all_tickers = await get_tickers()
        usdt = [t for t in all_tickers if t["symbol"].endswith("USDT")]
        usdt.sort(key=lambda t: to_finite(t.get("turnover24h")), reverse=True)
        top = [
            {
                "symbol": t["symbol"],
                "lastPrice": to_finite(t.get("lastPrice")),
                "change24h": to_finite(t.get("price24hPcnt")) * 100,
                "volume24h": to_finite(t.get("turnover24h")),
                "high24h": to_finite(t.get("highPrice24h")),
                "low24h": to_finite(t.get("lowPrice24h")),
                "fundingRate": to_finite(t.get("fundingRate")),
            }
            for t in usdt[:15]
        ]
        return top
    except Exception as err:  # noqa: BLE001
        return JSONResponse(status_code=502, content={"error": str(err) or "Bybit API error"})


@router.get("/prices")
async def prices():
    try:
        all_tickers = await get_tickers()
        result: dict[str, float] = {}
        for t in all_tickers:
            price = to_finite(t.get("lastPrice"), float("nan"))
            if price == price and price > 0:
                result[t["symbol"]] = price
        return result
    except Exception as err:  # noqa: BLE001
        return JSONResponse(status_code=502, content={"error": str(err) or "Bybit API error"})


@router.get("/funding")
async def funding():
    try:
        all_tickers = await get_tickers()
        rows = []
        for t in all_tickers:
            if not t["symbol"].endswith("USDT"):
                continue
            nft_raw = t.get("nextFundingTime")
            try:
                nft = int(str(nft_raw).strip())
            except (TypeError, ValueError):
                nft = 0
            rows.append({
                "symbol": t["symbol"],
                "fundingRate": to_finite(t.get("fundingRate")),
                "nextFundingTime": nft or None,
                "lastPrice": to_finite(t.get("lastPrice")),
            })
        rows.sort(key=lambda r: r["fundingRate"])
        return rows[:80]
    except Exception as err:  # noqa: BLE001
        return JSONResponse(status_code=502, content={"error": str(err) or "Bybit API error"})


@router.get("/funding/{symbol}/history")
async def funding_history(symbol: str):
    try:
        sym = str(symbol).upper()
        hist = await get_funding_rate_history(sym, 30)
        return hist
    except Exception as err:  # noqa: BLE001
        return JSONResponse(status_code=502, content={"error": str(err) or "Bybit API error"})
