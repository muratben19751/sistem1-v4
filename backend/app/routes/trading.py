import math
import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db.database import query_one
from ..engines.registry import get_engine
from ..engines.trade_engine import OrderParams
from ..services.bybit_api import get_last_price
from ..agents.execution import complete_exchange_operation as _complete_exchange_operation
from ..agents.risk import evaluate_risk, account_gate

router = APIRouter()

_MISSING = object()


def _finite(n) -> bool:
    try:
        return math.isfinite(float(n))
    except (TypeError, ValueError):
        return False


def parse_account_id(raw) -> int | None:
    text = str(raw if raw is not None else "").strip()
    if not re.fullmatch(r"\d+", text):
        return None
    val = int(text)
    return val if val > 0 else None


def parse_positive_number(raw) -> float | None:
    if not _finite(raw):
        return None
    n = float(raw)
    return n if n > 0 else None


def parse_leverage(raw) -> int | None:
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return None
    if n != n or n in (float("inf"), float("-inf")):
        return None
    if n != int(n):
        return None
    n = int(n)
    return n if 1 <= n <= 125 else None


def parse_optional_number(raw):
    if raw is _MISSING or raw is None or raw == "":
        return None
    if not _finite(raw):
        return None
    return float(raw)


def parse_optional_percent(raw):
    n = parse_optional_number(raw)
    if n is None:
        return None
    return n if 0 <= n <= 100 else None


def parse_optional_price(raw):
    # Returns: ("undefined") -> _MISSING, null/'' -> None, valid>0 -> float, invalid -> _MISSING
    if raw is _MISSING:
        return _MISSING
    if raw is None or raw == "":
        return None
    if not _finite(raw):
        return _MISSING
    n = float(raw)
    return n if n > 0 else _MISSING


def parse_side(raw):
    return raw if raw in ("long", "short") else None


def normalize_symbol(raw):
    if not isinstance(raw, str):
        return None
    symbol = raw.strip().upper()
    return symbol if re.fullmatch(r"[A-Z0-9]{1,30}USDT", symbol) else None


def normalize_optional_text(raw, fallback: str, max_length: int = 120) -> str:
    if not isinstance(raw, str):
        return fallback
    text = raw.strip()
    return text[:max_length] if text else fallback


def get_engine_for_account(account_id: int):
    acc = query_one("SELECT engine FROM accounts WHERE id = ?", (account_id,))
    if not acc:
        return None
    return get_engine(acc["engine"])


def _order_result_dict(r) -> dict:
    out = {"success": r.success}
    if r.trade_id is not None:
        out["tradeId"] = r.trade_id
    if r.fill_price is not None:
        out["fillPrice"] = r.fill_price
    if r.error is not None:
        out["error"] = r.error
    return out


def _close_result_dict(r) -> dict:
    out = {"success": r.success}
    if r.pnl is not None:
        out["pnl"] = r.pnl
    if r.pnl_percent is not None:
        out["pnlPercent"] = r.pnl_percent
    if r.exit_price is not None:
        out["exitPrice"] = r.exit_price
    if r.error is not None:
        out["error"] = r.error
    return out


def _balance_dict(b) -> dict:
    return {
        "balance": b.balance,
        "equity": b.equity,
        "unrealizedPnl": b.unrealized_pnl,
        "availableBalance": b.available_balance,
    }


@router.post("/order")
async def place_order(request: Request):
    try:
        body = await request.json()
        account_id = parse_account_id(body.get("accountId"))
        symbol = normalize_symbol(body.get("symbol"))
        side = parse_side(body.get("side"))

        size_raw = body.get("size", _MISSING)
        notional_raw = body.get("notional", _MISSING)
        has_size = size_raw is not _MISSING and size_raw is not None and size_raw != ""
        has_notional = notional_raw is not _MISSING and notional_raw is not None and notional_raw != ""
        if not account_id or not symbol or not side or (not has_size and not has_notional):
            return JSONResponse(status_code=400, content={"error": "Missing required fields: accountId, symbol, side, size or notional"})

        engine = get_engine_for_account(account_id)
        if not engine:
            return JSONResponse(status_code=404, content={"error": "Account not found"})

        price = await get_last_price(symbol)
        leverage_raw = body.get("leverage")
        requested_leverage = parse_leverage(leverage_raw if leverage_raw is not None else 2)
        if not requested_leverage:
            return JSONResponse(status_code=400, content={"error": "Invalid leverage"})

        if has_notional:
            requested_notional = parse_positive_number(notional_raw)
        else:
            coin_size = parse_positive_number(size_raw)
            requested_notional = coin_size * price if coin_size else None
        if not requested_notional:
            return JSONResponse(status_code=400, content={"error": "Invalid size or notional"})

        # Hesap kilidi: risk-kontrol + emir-acma atomik (eszamanli istekler max_positions asamaz).
        async with account_gate(account_id):
            risk = await evaluate_risk({
                "accountId": account_id,
                "symbol": symbol,
                "side": side,
                "score": 0,
                "price": price,
                "requestedNotional": requested_notional,
                "requestedLeverage": requested_leverage,
                "skipScoreCheck": True,
            })
            if not risk["approved"]:
                return JSONResponse(status_code=400, content={"success": False, "error": risk.get("reason")})

            tp_raw = body.get("tpPercent", _MISSING)
            sl_raw = body.get("slPercent", _MISSING)
            score_raw = body.get("signalScore", _MISSING)
            parsed_tp = parse_optional_percent(tp_raw)
            parsed_sl = parse_optional_percent(sl_raw)
            parsed_score = parse_optional_number(score_raw)
            if tp_raw is not _MISSING and parsed_tp is None:
                return JSONResponse(status_code=400, content={"error": "Invalid TP percent"})
            if sl_raw is not _MISSING and parsed_sl is None:
                return JSONResponse(status_code=400, content={"error": "Invalid SL percent"})
            if score_raw is not _MISSING and score_raw is not None and score_raw != "" and parsed_score is None:
                return JSONResponse(status_code=400, content={"error": "Invalid signal score"})

            active_rules = body.get("activeRules")
            result = await _complete_exchange_operation(
                engine.place_order(OrderParams(
                    account_id=account_id,
                    symbol=symbol,
                    side=side,
                    size=risk["size"],
                    leverage=risk["leverage"],
                    tp_percent=parsed_tp,
                    sl_percent=parsed_sl,
                    signal_score=parsed_score,
                    active_rules=active_rules[:1000] if isinstance(active_rules, str) else None,
                    entry_reason=normalize_optional_text(body.get("entryReason"), "manual_order", 80),
                ))
            )

        payload = _order_result_dict(result)
        if not result.success:
            return JSONResponse(status_code=400, content=payload)
        return payload
    except Exception as err:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(err)})


@router.post("/close")
async def close_order(request: Request):
    try:
        body = await request.json()
        account_id = parse_account_id(body.get("accountId"))
        symbol = normalize_symbol(body.get("symbol"))
        side = parse_side(body.get("side"))

        if not account_id or not symbol or not side:
            return JSONResponse(status_code=400, content={"error": "Missing required fields: accountId, symbol, side"})

        engine = get_engine_for_account(account_id)
        if not engine:
            return JSONResponse(status_code=404, content={"error": "Account not found"})
        reason = body.get("reason")
        result = await _complete_exchange_operation(
            engine.close_position(
                account_id,
                symbol,
                side,
                reason if isinstance(reason, str) else "manual",
            )
        )

        payload = _close_result_dict(result)
        if not result.success:
            return JSONResponse(status_code=400, content=payload)
        return payload
    except Exception as err:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(err)})


@router.get("/balance/{account_id}")
async def get_balance(account_id: str):
    try:
        uid = parse_account_id(account_id)
        if not uid:
            return JSONResponse(status_code=400, content={"error": "Invalid accountId"})
        engine = get_engine_for_account(uid)
        if not engine:
            return JSONResponse(status_code=404, content={"error": "Account not found"})
        balance = await engine.get_balance(uid)
        return _balance_dict(balance)
    except Exception as err:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(err)})


@router.post("/tp-sl")
async def set_tp_sl(request: Request):
    try:
        body = await request.json()
        account_id = parse_account_id(body.get("accountId"))
        symbol = normalize_symbol(body.get("symbol"))
        side = parse_side(body.get("side"))
        if not account_id or not symbol or not side:
            return JSONResponse(status_code=400, content={"error": "Missing required fields: accountId, symbol, side"})
        tp_raw = body.get("tp", _MISSING)
        sl_raw = body.get("sl", _MISSING)
        next_tp = parse_optional_price(tp_raw)
        next_sl = parse_optional_price(sl_raw)
        if tp_raw is not _MISSING and tp_raw is not None and next_tp is _MISSING:
            return JSONResponse(status_code=400, content={"error": "Invalid TP"})
        if sl_raw is not _MISSING and sl_raw is not None and next_sl is _MISSING:
            return JSONResponse(status_code=400, content={"error": "Invalid SL"})
        engine = get_engine_for_account(account_id)
        if not engine:
            return JSONResponse(status_code=404, content={"error": "Account not found"})
        current = query_one(
            "SELECT tp_price, sl_price FROM open_positions WHERE account_id = ? AND symbol = ? AND side = ?",
            (account_id, symbol, side),
        )
        if not current:
            return JSONResponse(status_code=404, content={"error": "Position not found"})
        resolved_tp = current["tp_price"] if tp_raw is _MISSING else next_tp
        resolved_sl = current["sl_price"] if sl_raw is _MISSING else next_sl
        await _complete_exchange_operation(
            engine.set_tp_sl(
                account_id, symbol, side,
                None if resolved_tp is None else resolved_tp,
                None if resolved_sl is None else resolved_sl,
            )
        )
        return {"success": True}
    except Exception as err:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(err)})


@router.post("/update-prices/{account_id}")
async def update_prices(account_id: str):
    try:
        uid = parse_account_id(account_id)
        if not uid:
            return JSONResponse(status_code=400, content={"error": "Invalid accountId"})
        engine = get_engine_for_account(uid)
        if not engine:
            return JSONResponse(status_code=404, content={"error": "Account not found"})
        await engine.update_mark_prices(uid)
        return {"success": True}
    except Exception as err:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(err)})
