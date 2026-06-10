import asyncio
import hashlib
import hmac
import json
import math
import os
import sys
import time
from urllib.parse import urlencode

import httpx

from ..core.event_bus import event_bus
from ..core.logger import create_logger
from ..core.secrets import decrypt_secret
from ..core.time import parse_db_time_ms
from ..db.database import get_db, query_one, query_all, execute, transaction
from ..services.bybit_api import get_instrument_meta, get_last_price, is_tradable_linear_symbol
from ..services.bybit_ws import (
    get_bybit_ws_positions,
    prepare_bybit_private_ws,
    prime_bybit_private_ws_positions,
    wait_for_bybit_ws_fill,
)
from .trade_engine import (
    TradeEngine, OrderParams, OrderResult, CloseResult, Position, Balance,
)

log = create_logger("bybit-engine")


def _int_env(name: str, default: int) -> int:
    # Mirror v3: Number.parseInt(env || '', 10) || default  (0/NaN -> default)
    try:
        v = int(os.environ.get(name) or 0)
    except ValueError:
        v = 0
    return v or default


BASE_URL = os.environ.get("BYBIT_REST_BASE_URL") or (
    "https://api-testnet.bybit.com" if os.environ.get("BYBIT_TESTNET") == "true" else "https://api.bybit.com"
)
DEMO_BASE_URL = os.environ.get("BYBIT_DEMO_REST_BASE_URL") or "https://api-demo.bybit.com"
REAL_PRIVATE_WS_URL = os.environ.get("BYBIT_PRIVATE_WS_URL") or (
    "wss://stream-testnet.bybit.com/v5/private" if os.environ.get("BYBIT_TESTNET") == "true"
    else "wss://stream.bybit.com/v5/private"
)
DEMO_PRIVATE_WS_URL = os.environ.get("BYBIT_DEMO_PRIVATE_WS_URL") or "wss://stream-demo.bybit.com/v5/private"
PRIVATE_RATE_LIMIT_DELAY = max(50, _int_env("BYBIT_PRIVATE_RATE_LIMIT_DELAY_MS", 500))
PRIVATE_REQUEST_TIMEOUT_MS = max(2_000, _int_env("BYBIT_PRIVATE_REQUEST_TIMEOUT_MS", 8_000))
PRIVATE_MAX_ADAPTIVE_COOLDOWN_MS = max(5_000, _int_env("BYBIT_PRIVATE_MAX_ADAPTIVE_COOLDOWN_MS", 60_000))
REMOTE_MISSING_CLOSE_THRESHOLD = max(1, _int_env("BYBIT_REMOTE_MISSING_CLOSE_THRESHOLD", 3))
ORPHAN_IMPORT_THRESHOLD = max(1, _int_env("BYBIT_ORPHAN_IMPORT_THRESHOLD", 2))
CLOSE_LOOKUP_WINDOW_MS = min(
    7 * 86_400_000,
    max(5 * 60_000, _int_env("BYBIT_CLOSE_LOOKUP_WINDOW_MS", 60 * 60_000)),
)
CLOSE_LOOKUP_FUTURE_SKEW_MS = 5 * 60_000
MAX_BYBIT_HISTORY_RANGE_MS = 7 * 86_400_000
POSITION_MODE = (os.environ.get("BYBIT_POSITION_MODE") or "oneway").strip().lower()

EPSILON = sys.float_info.epsilon  # 2.220446049250313e-16, matches JS Number.EPSILON

# --- adaptive private-rate-limit / cooldown state (module-level, like bybit_api) ---
_private_gate_lock = asyncio.Lock()
_last_private_request_time = 0.0
_private_adaptive_cooldown_until = 0.0
_private_stress_streak = 0

_missing_remote_positions: dict[str, int] = {}
_orphan_remote_positions: dict[str, int] = {}
_position_locks: dict[str, asyncio.Lock] = {}

_private_client: httpx.AsyncClient | None = None


def _prune_reconciliation_counters(
    account_id: int,
    local_position_ids: set[int],
    remote_keys: set[str],
    local_keys: set[str],
) -> None:
    prefix = f"{account_id}:"
    valid_missing = {f"{prefix}position:{position_id}" for position_id in local_position_ids}
    valid_orphans = {f"{prefix}{key}" for key in remote_keys - local_keys}

    for key in list(_missing_remote_positions):
        if key.startswith(prefix) and key not in valid_missing:
            _missing_remote_positions.pop(key, None)
    for key in list(_orphan_remote_positions):
        if key.startswith(prefix) and key not in valid_orphans:
            _orphan_remote_positions.pop(key, None)


def _missing_position_key(account_id: int, position_id: int) -> str:
    return f"{account_id}:position:{position_id}"


def _exchange_error_status(fill_confirmed: bool) -> str:
    return "reconcile_required" if fill_confirmed else "failed"


def _get_private_client() -> httpx.AsyncClient:
    global _private_client
    if _private_client is None:
        _private_client = httpx.AsyncClient(timeout=PRIVATE_REQUEST_TIMEOUT_MS / 1000.0)
    return _private_client


async def close_private_client() -> None:
    global _private_client
    if _private_client is None:
        return
    await _private_client.aclose()
    _private_client = None


def _now_monotonic_ms() -> float:
    return time.monotonic() * 1000.0


def _get_credentials(account_id: int, account_type: str) -> dict:
    row = query_one("SELECT api_key, api_secret FROM accounts WHERE id = ? AND type = ?", (account_id, account_type))
    if not row or not row["api_key"] or not row["api_secret"]:
        raise RuntimeError("No API credentials for this account")
    return {"api_key": decrypt_secret(row["api_key"]), "api_secret": decrypt_secret(row["api_secret"])}


def _generate_signature(api_secret: str, timestamp: str, api_key: str, recv_window: str, payload: str) -> str:
    param_str = timestamp + api_key + recv_window + payload
    return hmac.new(api_secret.encode(), param_str.encode(), hashlib.sha256).hexdigest()


# --- number/format helpers (ported EXACTLY from v3, incl. JS toString/regex semantics) ---

def _js_num_str(n) -> str:
    # Mimic JS Number.prototype.toString for the magnitudes we deal with:
    # integer-valued floats render without a trailing ".0" (e.g. 100.0 -> "100").
    f = float(n)
    if math.isfinite(f) and f == int(f) and abs(f) < 1e16:
        return str(int(f))
    return repr(f)


def _format_bybit_price(price: float) -> str:
    decimals = 2 if price >= 100 else 4 if price >= 1 else 6 if price >= 0.01 else 8 if price >= 0.001 else 10
    return f"{price:.{decimals}f}".rstrip("0").rstrip(".")


def _decimal_places(step: float) -> int:
    if not math.isfinite(step) or step <= 0:
        return 8
    text = _js_num_str(step).lower()
    if "e-" in text:
        return int(text.split("e-")[1])
    dot = text.find(".")
    return len(text) - dot - 1 if dot >= 0 else 0


def _floor_to_step(value: float, step: float) -> float:
    if not math.isfinite(step) or step <= 0:
        return value
    return math.floor((value + EPSILON) / step) * step


def _round_to_step(value: float, step: float) -> float:
    if not math.isfinite(step) or step <= 0:
        return value
    return math.floor(value / step + 0.5) * step  # Math.round -> floor(x+0.5)


def _format_stepped(value: float, step: float) -> str:
    decimals = _decimal_places(step)
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".")


def _normalize_qty(size: float, price: float, meta: dict):
    if not math.isfinite(size) or size <= 0:
        return {"error": "Invalid order size"}
    qty = _floor_to_step(size, meta["qtyStep"])
    if not math.isfinite(qty) or qty <= 0:
        return {"error": f"Order size is below qty step for {meta['symbol']}"}
    if meta["minOrderQty"] > 0 and qty < meta["minOrderQty"]:
        return {"error": f"Order size below min qty {meta['minOrderQty']} for {meta['symbol']}"}
    if meta["maxOrderQty"] > 0 and qty > meta["maxOrderQty"]:
        return {"error": f"Order size above max qty {meta['maxOrderQty']} for {meta['symbol']}"}
    notional = qty * price
    if meta["minNotionalValue"] > 0 and notional < meta["minNotionalValue"]:
        return {"error": f"Order notional ${notional:.2f} below min ${meta['minNotionalValue']} for {meta['symbol']}"}
    return {"qty": _format_stepped(qty, meta["qtyStep"]), "numeric": qty}


def _format_order_price(price: float, meta: dict) -> str:
    if meta["tickSize"] > 0:
        return _format_stepped(_round_to_step(price, meta["tickSize"]), meta["tickSize"])
    return _format_bybit_price(price)


def _parse_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _position_key(symbol: str, side: str) -> str:
    return f"{symbol}:{side}"


def _side_from_bybit(raw: str) -> str:
    return "long" if raw == "Buy" else "short"


def _is_one_way_mode() -> bool:
    return POSITION_MODE != "hedge"


def _position_idx_for_side(side: str) -> int:
    if POSITION_MODE == "hedge":
        return 1 if side == "long" else 2
    return 0


def _lock_key(account_id: int, symbol: str, side: str) -> str:
    return f"{account_id}:{symbol.upper()}:{'oneway' if _is_one_way_mode() else side}"


def _position_lock_for(key: str) -> asyncio.Lock:
    lk = _position_locks.get(key)
    if lk is None:
        lk = asyncio.Lock()
        _position_locks[key] = lk
    return lk


# Hesap basina uzlasma (update_mark_prices) tek seferde calissin: monitor tik'i ile global
# reconciler ayni hesabi eszamanli uzlastirinca ayni kismi-kapanis iki kez kaydedilebiliyordu.
_reconcile_in_progress: set[int] = set()


def _make_order_link_id(action: str, account_id: int) -> str:
    return f"s1{action[0]}{account_id}{_to_base36(int(time.time() * 1000))}{os.urandom(4).hex()}"


def _to_base36(n: int) -> str:
    if n == 0:
        return "0"
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while n > 0:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return out


# --- rate-limit gate / retry classification ---

async def _private_rate_limit() -> None:
    async with _private_gate_lock:
        global _last_private_request_time
        wait_until = max(_last_private_request_time + PRIVATE_RATE_LIMIT_DELAY, _private_adaptive_cooldown_until)
        wait = max(0.0, wait_until - _now_monotonic_ms())
        if wait > 0:
            await asyncio.sleep(wait / 1000.0)
        _last_private_request_time = _now_monotonic_ms()


def _apply_private_cooldown(base_ms: float) -> None:
    global _private_stress_streak, _private_adaptive_cooldown_until
    _private_stress_streak += 1
    cooldown = min(PRIVATE_MAX_ADAPTIVE_COOLDOWN_MS, base_ms * _private_stress_streak)
    _private_adaptive_cooldown_until = max(_private_adaptive_cooldown_until, _now_monotonic_ms() + cooldown)


def _is_rate_limit_error(data, status=None) -> bool:
    d = data or {}
    msg = str(d.get("retMsg") or d.get("message") or "").lower()
    return status == 429 or d.get("retCode") == 10006 or "too many visits" in msg or "rate limit" in msg


def _is_transient_network_error(err) -> bool:
    return isinstance(err, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError))


def _is_duplicate_order_error(err) -> bool:
    # Bybit 110072: "OrderLinkedID is duplicate" -> emir zaten gonderilmis (retry collision).
    msg = str(err).lower()
    return "110072" in msg or "orderlinkedid is duplicate" in msg or "duplicate" in msg and "orderlink" in msg


async def _private_request(base_url: str, creds: dict, method: str, endpoint: str,
                           params: dict | None = None, retries: int = 0):
    await _private_rate_limit()
    timestamp = str(int(time.time() * 1000))
    recv_window = "5000"
    url = f"{base_url}{endpoint}"
    body = ""

    if method == "GET" and params:
        qs = urlencode(params)
        url += f"?{qs}"
        body = qs
    elif method == "POST" and params:
        body = json.dumps(params, separators=(",", ":"))

    sign = _generate_signature(creds["api_secret"], timestamp, creds["api_key"], recv_window, body)

    headers = {
        "X-BAPI-API-KEY": creds["api_key"],
        "X-BAPI-SIGN": sign,
        "X-BAPI-TIMESTAMP": timestamp,
        "X-BAPI-RECV-WINDOW": recv_window,
    }
    if method == "POST":
        headers["Content-Type"] = "application/json"

    client = _get_private_client()
    try:
        if method == "POST":
            res = await client.post(url, content=body, headers=headers)
        else:
            res = await client.get(url, headers=headers)
    except Exception as err:  # noqa: BLE001
        if _is_transient_network_error(err) and retries < 2:
            backoff = 1500 * (retries + 1)
            _apply_private_cooldown(backoff)
            log.warn(f"Private Bybit network backoff {backoff}ms for {endpoint} (retry {retries + 1}/2)")
            await asyncio.sleep(backoff / 1000.0)
            return await _private_request(base_url, creds, method, endpoint, params, retries + 1)
        raise

    data = res.json()
    status = res.status_code
    ok = res.is_success
    if (not ok or _is_rate_limit_error(data, status)) and retries < 3:
        backoff = 5000 * (retries + 1)
        _apply_private_cooldown(backoff)
        log.warn(f"Private Bybit rate/error backoff {backoff / 1000}s for {endpoint} (retry {retries + 1}/3)")
        await asyncio.sleep(backoff / 1000.0)
        return await _private_request(base_url, creds, method, endpoint, params, retries + 1)
    if not ok:
        raise RuntimeError(f"Bybit HTTP error: {status} {res.reason_phrase}")
    if data.get("retCode") != 0:
        raise RuntimeError(f"Bybit API error: {data.get('retMsg')} (code: {data.get('retCode')})")
    global _private_stress_streak
    _private_stress_streak = 0
    return data["result"]


# --- exchange_orders bookkeeping ---

def _record_exchange_order(account_id, symbol, side, action, order_link_id, requested_qty):
    try:
        execute(
            """
            INSERT INTO exchange_orders (account_id, symbol, side, action, order_link_id, requested_qty, status)
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """,
            (account_id, symbol, side, action, order_link_id, requested_qty),
        )
    except Exception as err:  # noqa: BLE001
        log.error(f"Could not record exchange order {order_link_id}; exchange request aborted: {err}")
        raise RuntimeError(f"Exchange order audit record failed: {err}") from err


def _update_exchange_order(order_link_id, status, exchange_order_id=None, filled_qty=None,
                           avg_price=None, fee=None, error=None):
    try:
        execute(
            """
            UPDATE exchange_orders
            SET status = ?,
                exchange_order_id = COALESCE(?, exchange_order_id),
                filled_qty = COALESCE(?, filled_qty),
                avg_price = COALESCE(?, avg_price),
                fee = COALESCE(?, fee),
                error = ?,
                updated_at = datetime('now')
            WHERE order_link_id = ?
            """,
            (status, exchange_order_id, filled_qty, avg_price, fee, error, order_link_id),
        )
    except Exception as err:  # noqa: BLE001
        log.warn(f"Could not update exchange order {order_link_id}: {err}")


# --- fill confirmation (REST fallback paths; private WS stubbed) ---

def _fill_from_order(order, fallback_order_id):
    if not order:
        return None
    qty = _parse_float(order.get("cumExecQty") or order.get("qty") or "0")
    avg_price = _parse_float(order.get("avgPrice") or order.get("price") or "0")
    fee = _parse_float(order.get("cumExecFee") or "0")
    if not math.isfinite(qty) or qty <= 0 or not math.isfinite(avg_price) or avg_price <= 0:
        return None
    return {
        "orderId": str(order.get("orderId") or fallback_order_id),
        "qty": qty,
        "avgPrice": avg_price,
        "fee": fee if math.isfinite(fee) else 0,
    }


def _fill_from_executions(lst, fallback_order_id):
    qty = 0.0
    notional = 0.0
    fee = 0.0
    for exec_ in lst or []:
        exec_qty = _parse_float(exec_.get("execQty") or "0")
        exec_price = _parse_float(exec_.get("execPrice") or "0")
        exec_fee = _parse_float(exec_.get("execFee") or "0")
        if not math.isfinite(exec_qty) or exec_qty <= 0 or not math.isfinite(exec_price) or exec_price <= 0:
            continue
        qty += exec_qty
        notional += exec_qty * exec_price
        if math.isfinite(exec_fee):
            fee += exec_fee
    if qty <= 0 or notional <= 0:
        return None
    return {"orderId": fallback_order_id, "qty": qty, "avgPrice": notional / qty, "fee": fee}


async def _confirm_order_fill(base_url, private_ws_url, account_id, creds, symbol, order_id, order_link_id):
    id_params = {"orderId": order_id} if order_id else {"orderLinkId": order_link_id}
    fallback_order_id = order_id or order_link_id

    try:
        ws_fill = await wait_for_bybit_ws_fill(account_id, creds, order_id, order_link_id, 5_000, private_ws_url)
        if ws_fill and ws_fill.get("qty", 0) > 0 and ws_fill.get("avgPrice", 0) > 0:
            return {
                "orderId": ws_fill.get("orderId") or fallback_order_id,
                "qty": ws_fill["qty"],
                "avgPrice": ws_fill["avgPrice"],
                "fee": ws_fill.get("fee", 0),
            }
    except Exception as err:  # noqa: BLE001
        log.warn(f"Bybit WS fill wait failed for {symbol} {fallback_order_id}: {err}", {"accountId": account_id})

    for attempt in range(4):
        if attempt > 0:
            await asyncio.sleep(0.5 * attempt)

        try:
            realtime = await _private_request(base_url, creds, "GET", "/v5/order/realtime", {
                "category": "linear", "symbol": symbol, **id_params,
            })
            fill = _fill_from_order((realtime.get("list") or [None])[0], fallback_order_id)
            if fill:
                return fill
        except Exception as err:  # noqa: BLE001
            log.warn(f"Order realtime lookup failed for {symbol} {fallback_order_id}: {err}")

        try:
            history = await _private_request(base_url, creds, "GET", "/v5/order/history", {
                "category": "linear", "symbol": symbol, **id_params,
            })
            fill = _fill_from_order((history.get("list") or [None])[0], fallback_order_id)
            if fill:
                return fill
        except Exception as err:  # noqa: BLE001
            log.warn(f"Order history lookup failed for {symbol} {fallback_order_id}: {err}")

        try:
            executions = await _private_request(base_url, creds, "GET", "/v5/execution/list", {
                "category": "linear", "symbol": symbol, **id_params,
            })
            fill = _fill_from_executions(executions.get("list") or [], fallback_order_id)
            if fill:
                return fill
        except Exception as err:  # noqa: BLE001
            log.warn(f"Execution lookup failed for {symbol} {fallback_order_id}: {err}")

    return None


async def _get_remote_position(base_url, creds, symbol, side):
    result = await _private_request(base_url, creds, "GET", "/v5/position/list", {
        "category": "linear", "symbol": symbol,
    })
    for p in result.get("list") or []:
        sz = _parse_float(p.get("size") or "0")
        if math.isfinite(sz) and sz > 0 and _side_from_bybit(p.get("side")) == side:
            return p
    return None


def _find_blocking_remote_position(lst, side):
    for p in lst or []:
        sz = _parse_float(p.get("size") or "0")
        if not math.isfinite(sz) or sz <= 0:
            continue
        if _is_one_way_mode() or _side_from_bybit(p.get("side")) == side:
            return p
    return None


# --- close-reason resolution ---

STOP_ORDER_REASON = {
    "TakeProfit": "take_profit",
    "PartialTakeProfit": "take_profit",
    "StopLoss": "stop_loss",
    "PartialStopLoss": "stop_loss",
    "TrailingStop": "trailing_stop",
    "Stop": "stop_loss",
}

CREATE_TYPE_REASON = {
    "CreateByTakeProfit": "take_profit",
    "CreateByPartialTakeProfit": "take_profit",
    "CreateByStopLoss": "stop_loss",
    "CreateByPartialStopLoss": "stop_loss",
    "CreateByTrailingStop": "trailing_stop",
    "CreateByTrailingProfit": "take_profit",
    "CreateByLiq": "liquidation",
    "CreateByTakeOver_PassThrough": "liquidation",
    "CreateByAdl_PassThrough": "adl",
    "CreateBySettle": "settlement",
}


def _bybit_number(value) -> float:
    n = _parse_float(value)
    return n if math.isfinite(n) else float("nan")


def _bybit_time(value) -> float:
    if value is None or value == "":
        n = 0.0
    else:
        try:
            n = float(value)
        except (TypeError, ValueError):
            n = float("nan")
    return n if (math.isfinite(n) and n > 0) else float("nan")


def _close_side_for(side: str) -> str:
    return "Sell" if side == "long" else "Buy"


def _close_lookup_range(match: dict) -> dict:
    reference_ms = match.get("referenceMs")
    if reference_ms is None or not math.isfinite(reference_ms):
        return {}
    end_time = max(0, math.floor(reference_ms + CLOSE_LOOKUP_FUTURE_SKEW_MS))
    start_time = max(0, math.floor(reference_ms - CLOSE_LOOKUP_WINDOW_MS))
    opened_ms = match.get("openedMs")
    if opened_ms is not None and math.isfinite(opened_ms):
        start_time = max(start_time, max(0, math.floor(opened_ms - 5 * 60_000)))
    if end_time - start_time > MAX_BYBIT_HISTORY_RANGE_MS:
        start_time = max(0, end_time - MAX_BYBIT_HISTORY_RANGE_MS)
    return {"startTime": int(start_time), "endTime": int(end_time)}


def _is_fin(x) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


def _close_size_matches(candidate_size, expected_size) -> bool:
    if not _is_fin(expected_size) or expected_size <= 0:
        return True
    if not _is_fin(candidate_size) or candidate_size <= 0:
        return False
    tolerance = max(1e-8, expected_size * 0.02)
    return abs(candidate_size - expected_size) <= tolerance


def _close_match_score(time_ms, candidate_size, candidate_entry, match: dict) -> float:
    score = 0.0
    ref = match.get("referenceMs")
    if _is_fin(ref):
        score += abs(time_ms - ref) / 60_000 if _is_fin(time_ms) else 1_000_000
    size = match.get("size")
    if _is_fin(size) and _is_fin(candidate_size):
        score += abs(candidate_size - size) / max(size, 1e-8) * 1_000
    entry = match.get("entryPrice")
    if _is_fin(entry) and _is_fin(candidate_entry) and entry > 0:
        score += abs(candidate_entry - entry) / entry * 100
    return score


def _pick_closed_pnl_record(lst, close_side, match: dict):
    candidates = [
        r for r in (lst or [])
        if r.get("side") == close_side
        and _close_size_matches(_bybit_number(r.get("closedSize") or r.get("qty")), match.get("size"))
    ]
    candidates.sort(key=lambda r: _close_match_score(
        _bybit_time(r.get("updatedTime") or r.get("createdTime")),
        _bybit_number(r.get("closedSize") or r.get("qty")),
        _bybit_number(r.get("avgEntryPrice")),
        match,
    ))
    return candidates[0] if candidates else None


def _pick_closing_execution(lst, close_side, match: dict):
    candidates = [
        e for e in (lst or [])
        if _bybit_number(e.get("closedSize")) > 0 and e.get("side") == close_side
        and _close_size_matches(_bybit_number(e.get("closedSize")), match.get("size"))
    ]
    candidates.sort(key=lambda e: _close_match_score(
        _bybit_time(e.get("execTime")),
        _bybit_number(e.get("closedSize")),
        float("nan"),
        match,
    ))
    return candidates[0] if candidates else None


def _close_reason_from_execution(exec_) -> str:
    sot = str((exec_ or {}).get("stopOrderType") or "")
    et = str((exec_ or {}).get("execType") or "")
    ct = str((exec_ or {}).get("createType") or "")
    if et == "BustTrade" or "liquidat" in sot.lower() or "liq" in ct.lower():
        return "liquidation"
    return CREATE_TYPE_REASON.get(ct) or STOP_ORDER_REASON.get(sot) or "exchange_closed"


# When a position disappears from Bybit, find out HOW it closed: pull the real
# avgExitPrice + realized PnL from closed-pnl and the close reason (TP/SL/TRAIL/LIQ)
# from execution history. Falls back to tp/sl price inference, then a generic sync tag.
async def _resolve_exchange_close(base_url, creds, symbol, side, fallback: dict, match: dict | None = None):
    match = match or {}
    exit_price = fallback["exitPrice"]
    pnl = fallback["pnl"]
    pnl_resolved = False
    open_fee = 0.0
    close_fee = 0.0
    reason = ""
    close_side = _close_side_for(side)
    rng = _close_lookup_range(match)

    try:
        cp = await _private_request(base_url, creds, "GET", "/v5/position/closed-pnl", {
            "category": "linear", "symbol": symbol, "limit": 100, **rng,
        })
        rec = _pick_closed_pnl_record(cp.get("list") or [], close_side, match)
        if rec:
            ax = _bybit_number(rec.get("avgExitPrice"))
            cpnl = _bybit_number(rec.get("closedPnl"))
            if math.isfinite(ax) and ax > 0:
                exit_price = ax
            if math.isfinite(cpnl):
                pnl = cpnl
                pnl_resolved = True
            candidate_open_fee = _bybit_number(rec.get("openFee"))
            candidate_close_fee = _bybit_number(rec.get("closeFee"))
            if math.isfinite(candidate_open_fee):
                open_fee = candidate_open_fee
            if math.isfinite(candidate_close_fee):
                close_fee = candidate_close_fee
        elif _is_fin(match.get("size")) or _is_fin(match.get("referenceMs")):
            log.warn(f"closed-pnl lookup had no matching {side} close for {symbol}; keeping fallback PnL")
    except Exception as err:  # noqa: BLE001
        log.warn(f"closed-pnl lookup failed for {symbol}: {err}")

    try:
        ex = await _private_request(base_url, creds, "GET", "/v5/execution/list", {
            "category": "linear", "symbol": symbol, "limit": 100, **rng,
        })
        last = _pick_closing_execution(ex.get("list") or [], close_side, match)
        if last:
            reason = _close_reason_from_execution(last)
    except Exception as err:  # noqa: BLE001
        log.warn(f"execution lookup failed for {symbol}: {err}")

    if not reason:
        tp = fallback.get("tpPrice")
        sl = fallback.get("slPrice")
        if tp and tp > 0 and ((side == "long" and exit_price >= tp * 0.999) or (side == "short" and exit_price <= tp * 1.001)):
            reason = "take_profit"
        elif sl and sl > 0 and ((side == "long" and exit_price <= sl * 1.001) or (side == "short" and exit_price >= sl * 0.999)):
            reason = "stop_loss"
        else:
            reason = "exchange_closed_sync"

    return {
        "exitPrice": exit_price,
        "pnl": pnl,
        "reason": reason,
        "pnlResolved": pnl_resolved,
        "openFee": open_fee,
        "closeFee": close_fee,
    }


def _record_partial_close(
    account_id: int,
    position,
    closed_qty: float,
    exit_price: float,
    close_fee: float,
    reason: str,
    *,
    resolved_pnl: float | None = None,
    resolved_fee: float | None = None,
) -> tuple[float, float, float]:
    """Split a partial fill into one closed trade leg and one remaining open leg."""
    original_size = float(position["size"])
    remaining = max(0.0, original_size - closed_qty)
    trade = query_one(
        """
        SELECT * FROM trades
        WHERE account_id = ? AND symbol = ? AND side = ? AND status = 'open'
        ORDER BY opened_at DESC, id DESC LIMIT 1
        """,
        (account_id, position["symbol"], position["side"]),
    )

    trade_size = float(trade["size"]) if trade and trade["size"] else original_size
    entry_fee = float(trade["fee"] or 0) if trade else 0.0
    closed_ratio = min(1.0, closed_qty / trade_size) if trade_size > 0 else 1.0
    closed_entry_fee = entry_fee * closed_ratio
    remaining_entry_fee = max(0.0, entry_fee - closed_entry_fee)
    remaining_ratio = remaining / original_size if original_size > 0 else 0.0
    remaining_unrealized = (
        float(position["unrealized_pnl"]) * remaining_ratio
        if position["unrealized_pnl"] is not None
        else None
    )

    gross_pnl = (
        (exit_price - position["entry_price"]) * closed_qty
        if position["side"] == "long"
        else (position["entry_price"] - exit_price) * closed_qty
    )
    recorded_fee = (
        resolved_fee
        if resolved_fee is not None and math.isfinite(resolved_fee)
        else closed_entry_fee + close_fee
    )
    net_pnl = resolved_pnl if resolved_pnl is not None else gross_pnl - recorded_fee
    leverage = position["leverage"] or 1
    margin = (position["entry_price"] * closed_qty) / leverage
    pnl_percent = (net_pnl / margin) * 100 if margin > 0 else 0.0
    opened_at = trade["opened_at"] if trade else position["opened_at"]
    opened_ms = parse_db_time_ms(opened_at)
    duration_seconds = (
        int((int(time.time() * 1000) - opened_ms) / 1000)
        if math.isfinite(opened_ms)
        else None
    )

    with transaction() as conn:
        conn.execute(
            "UPDATE open_positions SET size = ?, unrealized_pnl = ? WHERE id = ?",
            (remaining, remaining_unrealized, position["id"]),
        )
        if trade:
            conn.execute(
                "UPDATE trades SET size = ?, fee = ? WHERE id = ?",
                (remaining, remaining_entry_fee, trade["id"]),
            )
        conn.execute(
            """
            INSERT INTO trades (
              account_id, symbol, side, size, entry_price, exit_price, leverage,
              pnl, pnl_percent, fee, status, active_rules, signal_score,
              entry_reason, exit_reason, opened_at, closed_at, duration_seconds,
              trigger_source, trigger_stars, min_score_used, note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'closed', ?, ?, ?, ?,
                    ?, datetime('now'), ?, ?, ?, ?, ?)
            """,
            (
                account_id, position["symbol"], position["side"], closed_qty,
                position["entry_price"], exit_price, leverage, net_pnl, pnl_percent,
                recorded_fee,
                trade["active_rules"] if trade else None,
                trade["signal_score"] if trade else None,
                trade["entry_reason"] if trade else "exchange_opened_sync",
                reason, opened_at, duration_seconds,
                trade["trigger_source"] if trade else None,
                trade["trigger_stars"] if trade else None,
                trade["min_score_used"] if trade else None,
                trade["note"] if trade else None,
            ),
        )
    return net_pnl, pnl_percent, remaining


class BybitEngine(TradeEngine):
    def __init__(self, base_url: str, account_type: str, name: str):
        # account_type matches the DB accounts.type column ('real' for the live
        # bybit engine, 'demo' for the demo engine); name is the engine label
        # used by the registry ('bybit' / 'demo').
        self.name = name
        self.base_url = base_url
        self.account_type = account_type
        self.private_ws_url = REAL_PRIVATE_WS_URL if account_type == "real" else DEMO_PRIVATE_WS_URL

    async def place_order(self, params: OrderParams) -> OrderResult:
        symbol = params.symbol.upper()
        async with _position_lock_for(_lock_key(params.account_id, symbol, params.side)):
            account_id = params.account_id
            side = params.side
            pending_order_link_id = None
            exchange_fill_confirmed = False

            try:
                if not await is_tradable_linear_symbol(symbol):
                    return OrderResult(success=False, error=f"{symbol} is not tradable on Bybit linear USDT")
                meta = await get_instrument_meta(symbol)
                if not meta:
                    return OrderResult(success=False, error=f"Instrument metadata not found for {symbol}")

                creds = _get_credentials(account_id, self.account_type)
                try:
                    prepare_bybit_private_ws(account_id, creds, 2_000, self.private_ws_url)
                except Exception as err:  # noqa: BLE001
                    log.warn(f"Bybit private WS not ready before order create: {err}", {"accountId": account_id})

                if _is_one_way_mode():
                    existing = query_one(
                        "SELECT id, side FROM open_positions WHERE account_id = ? AND symbol = ? LIMIT 1",
                        (account_id, symbol),
                    )
                else:
                    existing = query_one(
                        "SELECT id, side FROM open_positions WHERE account_id = ? AND symbol = ? AND side = ?",
                        (account_id, symbol, side),
                    )
                if existing:
                    return OrderResult(
                        success=False,
                        error=(
                            f"Position already exists locally for {symbol} ({existing['side']}); "
                            "one-way mode cannot open the opposite side safely"
                            if _is_one_way_mode() else "Position already exists"
                        ),
                    )

                try:
                    remote_result = await _private_request(self.base_url, creds, "GET", "/v5/position/list", {
                        "category": "linear", "symbol": symbol,
                    })
                    remote_open = _find_blocking_remote_position(remote_result.get("list") or [], side)
                    if remote_open:
                        return OrderResult(
                            success=False,
                            error=(
                                f"Position already exists on Bybit for {symbol} ({_side_from_bybit(remote_open.get('side'))}); "
                                "one-way mode cannot open the opposite side safely"
                                if _is_one_way_mode()
                                else f"Position already exists on Bybit (remote) for {symbol} {side}"
                            ),
                        )
                except Exception as err:  # noqa: BLE001
                    log.error(f"Remote position check failed for {symbol}; aborting order", {"accountId": account_id, "error": str(err)})
                    return OrderResult(success=False, error=f"Remote position check failed: {err}")

                await self.set_leverage(account_id, symbol, params.leverage)

                order_side = "Buy" if side == "long" else "Sell"
                tp_price = None
                sl_price = None
                last_price = await get_last_price(symbol)
                normalized_qty = _normalize_qty(params.size, last_price, meta)
                if "error" in normalized_qty:
                    return OrderResult(success=False, error=normalized_qty["error"])

                order_params = {
                    "category": "linear",
                    "symbol": symbol,
                    "side": order_side,
                    "orderType": "Market",
                    "qty": normalized_qty["qty"],
                    "timeInForce": "IOC",
                }

                # TP/SL percent interpreted as MARGIN ROI; required price move = TP% / leverage.
                lev = params.leverage if params.leverage > 0 else 1
                if params.tp_percent or params.sl_percent:
                    if params.tp_percent and last_price > 0:
                        price_pct = params.tp_percent / lev / 100
                        tp_price = last_price * (1 + price_pct) if side == "long" else last_price * (1 - price_pct)
                        order_params["takeProfit"] = _format_order_price(tp_price, meta)
                    if params.sl_percent and last_price > 0:
                        price_pct = params.sl_percent / lev / 100
                        sl_price = last_price * (1 - price_pct) if side == "long" else last_price * (1 + price_pct)
                        order_params["stopLoss"] = _format_order_price(sl_price, meta)

                order_link_id = _make_order_link_id("open", account_id)
                pending_order_link_id = order_link_id
                order_params["orderLinkId"] = order_link_id
                order_params["positionIdx"] = _position_idx_for_side(side)
                _record_exchange_order(account_id, symbol, side, "open", order_link_id, normalized_qty["numeric"])

                result = await _private_request(self.base_url, creds, "POST", "/v5/order/create", order_params)
                order_id = result.get("orderId")
                _update_exchange_order(order_link_id, status="submitted", exchange_order_id=order_id)

                fill = await _confirm_order_fill(self.base_url, self.private_ws_url, account_id, creds, symbol, order_id, order_link_id)
                if not fill:
                    try:
                        remote_open = await _get_remote_position(self.base_url, creds, symbol, side)
                        if remote_open:
                            remote_qty = _parse_float(remote_open.get("size") or "0")
                            remote_price = _parse_float(remote_open.get("avgPrice") or "0")
                            if math.isfinite(remote_qty) and remote_qty > 0 and math.isfinite(remote_price) and remote_price > 0:
                                fill = {"orderId": order_id, "qty": remote_qty, "avgPrice": remote_price, "fee": 0}
                                log.warn(f"Order fill inferred from remote position: {side} {symbol}", {"accountId": account_id, "orderId": order_id})
                    except Exception as err:  # noqa: BLE001
                        log.warn(f"Remote position fallback failed after order submit: {side} {symbol} {order_id} - {err}", {"accountId": account_id})
                if not fill:
                    _update_exchange_order(order_link_id, status="unconfirmed", exchange_order_id=order_id, error="fill not confirmed")
                    return OrderResult(success=False, error=f"Order sent to Bybit but fill could not be confirmed ({order_id}); check exchange_orders and Bybit before retrying")

                fill_price = fill["avgPrice"]
                filled_qty = fill["qty"]
                fee = fill["fee"]
                exchange_fill_confirmed = True
                _update_exchange_order(order_link_id, status="filled", exchange_order_id=fill["orderId"],
                                       filled_qty=filled_qty, avg_price=fill_price, fee=fee)

                entry_reason = params.entry_reason if params.entry_reason is not None else "bot_signal"
                with transaction() as conn:
                    cur = conn.execute(
                        """
                        INSERT INTO trades (account_id, symbol, side, size, entry_price, leverage, fee, status, signal_score, active_rules, entry_reason, trigger_source, trigger_stars, min_score_used)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?)
                        """,
                        (account_id, symbol, side, filled_qty, fill_price, params.leverage, fee,
                         params.signal_score, params.active_rules, entry_reason,
                         params.trigger_source, params.trigger_stars, params.min_score_used),
                    )
                    trade_id = cur.lastrowid
                    _bc = query_one("SELECT trailing_stop FROM bot_configs WHERE account_id = ?", (account_id,))
                    _trailing = 1 if (_bc and _bc["trailing_stop"]) else 0
                    conn.execute(
                        """
                        INSERT INTO open_positions (account_id, symbol, side, size, entry_price, mark_price, leverage, tp_price, sl_price, trailing_stop, trailing_highest, trailing_lowest)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (account_id, symbol, side, filled_qty, fill_price, fill_price, params.leverage, tp_price, sl_price,
                         _trailing, fill_price if (_trailing and side == "long") else None, fill_price if (_trailing and side == "short") else None),
                    )

                log.info(f"Order filled: {side} {filled_qty} {symbol} @ {fill_price}", {"accountId": account_id, "orderId": order_id})

                event_bus.emit("order:filled", {"symbol": symbol, "side": side, "size": filled_qty, "fillPrice": fill_price, "accountId": account_id})
                event_bus.emit("position:opened", {"symbol": symbol, "side": side, "size": filled_qty, "entryPrice": fill_price, "accountId": account_id})

                return OrderResult(success=True, trade_id=int(trade_id), fill_price=fill_price)
            except Exception as err:  # noqa: BLE001
                # Duplicate orderLinkId: _private_request bir POST'u tekrar gonderdi ama ILK
                # deneme borsaya ulasip emri ACMIS olabilir. Korumadan once gercekten dolup
                # dolmadigini dogrula; dolduysa pozisyonu kaydet (takipsiz canli pozisyon olmasin).
                if (not exchange_fill_confirmed and pending_order_link_id
                        and _is_duplicate_order_error(err)):
                    try:
                        recovered = await self._recover_filled_open(
                            account_id, creds, symbol, side, params,
                            tp_price, sl_price, pending_order_link_id,
                        )
                    except Exception as rec_err:  # noqa: BLE001
                        recovered = None
                        log.warn(f"Duplicate-order recovery failed for {symbol}: {rec_err}", {"accountId": account_id})
                    if recovered is not None:
                        return recovered
                if pending_order_link_id:
                    _update_exchange_order(
                        pending_order_link_id,
                        status=_exchange_error_status(exchange_fill_confirmed),
                        error=str(err),
                    )
                log.error(f"Order failed: {symbol} - {err}", {"accountId": account_id})
                return OrderResult(success=False, error=str(err))

    async def _recover_filled_open(self, account_id, creds, symbol, side, params,
                                   tp_price, sl_price, order_link_id):
        """Duplicate-order hatasinda: emir gercekte doldu mu? Dolduysa kaydet, yoksa None."""
        fill = await _confirm_order_fill(self.base_url, self.private_ws_url, account_id, creds, symbol, None, order_link_id)
        if not fill:
            remote_open = await _get_remote_position(self.base_url, creds, symbol, side)
            if not remote_open:
                return None
            remote_qty = _parse_float(remote_open.get("size") or "0")
            remote_price = _parse_float(remote_open.get("avgPrice") or "0")
            if not (math.isfinite(remote_qty) and remote_qty > 0 and math.isfinite(remote_price) and remote_price > 0):
                return None
            fill = {"orderId": order_link_id, "qty": remote_qty, "avgPrice": remote_price, "fee": 0}
        existing = query_one(
            "SELECT id FROM open_positions WHERE account_id = ? AND symbol = ? AND side = ?",
            (account_id, symbol, side),
        )
        if existing:
            return None  # zaten kayitli (baska yol uzlastirmis); cift kayit yapma
        fill_price = fill["avgPrice"]
        filled_qty = fill["qty"]
        fee = fill["fee"]
        _update_exchange_order(order_link_id, status="filled", exchange_order_id=fill["orderId"],
                               filled_qty=filled_qty, avg_price=fill_price, fee=fee)
        entry_reason = params.entry_reason if params.entry_reason is not None else "bot_signal"
        with transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO trades (account_id, symbol, side, size, entry_price, leverage, fee, status, signal_score, active_rules, entry_reason, trigger_source, trigger_stars, min_score_used)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?)
                """,
                (account_id, symbol, side, filled_qty, fill_price, params.leverage, fee,
                 params.signal_score, params.active_rules, entry_reason,
                 params.trigger_source, params.trigger_stars, params.min_score_used),
            )
            trade_id = cur.lastrowid
            _bc = query_one("SELECT trailing_stop FROM bot_configs WHERE account_id = ?", (account_id,))
            _trailing = 1 if (_bc and _bc["trailing_stop"]) else 0
            conn.execute(
                """
                INSERT INTO open_positions (account_id, symbol, side, size, entry_price, mark_price, leverage, tp_price, sl_price, trailing_stop, trailing_highest, trailing_lowest)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (account_id, symbol, side, filled_qty, fill_price, fill_price, params.leverage, tp_price, sl_price,
                 _trailing, fill_price if (_trailing and side == "long") else None, fill_price if (_trailing and side == "short") else None),
            )
        log.warn(f"Duplicate-order recovery: confirmed fill kaydedildi {side} {filled_qty} {symbol} @ {fill_price}", {"accountId": account_id})
        event_bus.emit("order:filled", {"symbol": symbol, "side": side, "size": filled_qty, "fillPrice": fill_price, "accountId": account_id})
        event_bus.emit("position:opened", {"symbol": symbol, "side": side, "size": filled_qty, "entryPrice": fill_price, "accountId": account_id})
        return OrderResult(success=True, trade_id=int(trade_id), fill_price=fill_price)

    async def close_position(self, account_id: int, symbol: str, side: str,
                             reason: str | None = None, fill_price_override: float | None = None) -> CloseResult:
        symbol = symbol.upper()
        async with _position_lock_for(_lock_key(account_id, symbol, side)):
            pending_order_link_id = None
            exchange_fill_confirmed = False
            try:
                creds = _get_credentials(account_id, self.account_type)
                try:
                    prepare_bybit_private_ws(account_id, creds, 2_000, self.private_ws_url)
                except Exception as err:  # noqa: BLE001
                    log.warn(f"Bybit private WS not ready before close order: {err}", {"accountId": account_id})

                position = query_one(
                    "SELECT * FROM open_positions WHERE account_id = ? AND symbol = ? AND side = ?",
                    (account_id, symbol, side),
                )
                if not position:
                    return CloseResult(success=False, error="Position not found in DB")

                close_side = "Sell" if side == "long" else "Buy"
                order_link_id = _make_order_link_id("close", account_id)
                pending_order_link_id = order_link_id
                _record_exchange_order(account_id, symbol, side, "close", order_link_id, position["size"])

                # Kapanis qty'sini borsa qtyStep'ine yuvarla; aksi halde kismi kapanis sonrasi
                # float artigi (orn. 0.10000000000000009) Bybit precision hatasi verir ve
                # kalan pozisyon kapatilamaz hale gelir.
                close_qty_str = _js_num_str(position["size"])
                try:
                    _meta = await get_instrument_meta(symbol)
                    _stepped = _floor_to_step(position["size"], _meta["qtyStep"])
                    if math.isfinite(_stepped) and _stepped > 0:
                        close_qty_str = _format_stepped(_stepped, _meta["qtyStep"])
                except Exception as err:  # noqa: BLE001 - meta yoksa ham degere dus
                    log.warn(f"Close qty step normalization failed for {symbol}: {err}", {"accountId": account_id})

                result = None
                fill = None
                try:
                    result = await _private_request(self.base_url, creds, "POST", "/v5/order/create", {
                        "category": "linear",
                        "symbol": symbol,
                        "side": close_side,
                        "orderType": "Market",
                        "qty": close_qty_str,
                        "timeInForce": "IOC",
                        "reduceOnly": True,
                        "positionIdx": _position_idx_for_side(side),
                        "orderLinkId": order_link_id,
                    })
                    _update_exchange_order(order_link_id, status="submitted", exchange_order_id=result.get("orderId"))
                except Exception as order_err:  # noqa: BLE001
                    # 110017: reduce-only qty fix failed -> pozisyon borsada zaten sifir (orphan).
                    msg = str(order_err)
                    lowered = msg.lower()
                    if not ("110017" in msg or "current position is zero" in lowered or "reduce-only order qty" in lowered):
                        raise
                    try:
                        remote_open = await _get_remote_position(self.base_url, creds, symbol, side)
                    except Exception:  # noqa: BLE001
                        remote_open = None
                    if remote_open:
                        raise
                    fallback_price = position["mark_price"] if (position["mark_price"] and position["mark_price"] > 0) else position["entry_price"]
                    fill = {"orderId": order_link_id, "qty": position["size"], "avgPrice": fallback_price, "fee": 0}
                    log.warn(f"Close rejected (110017, borsada zaten flat); yerel DB uzlastiriliyor: {side} {symbol}", {"accountId": account_id})

                if not fill:
                    fill = await _confirm_order_fill(self.base_url, self.private_ws_url, account_id, creds, symbol, result.get("orderId"), order_link_id)
                if not fill:
                    try:
                        remote_open = await _get_remote_position(self.base_url, creds, symbol, side)
                        if not remote_open:
                            fallback_price = position["mark_price"] if (position["mark_price"] and position["mark_price"] > 0) else position["entry_price"]
                            fill = {"orderId": result.get("orderId"), "qty": position["size"], "avgPrice": fallback_price, "fee": 0}
                            log.warn(f"Close fill inferred from missing remote position: {side} {symbol}", {"accountId": account_id, "orderId": result.get("orderId")})
                    except Exception as err:  # noqa: BLE001
                        log.warn(f"Remote position fallback failed after close submit: {side} {symbol} {result.get('orderId')} - {err}", {"accountId": account_id})
                if not fill or not math.isfinite(fill["avgPrice"]) or fill["avgPrice"] <= 0:
                    _update_exchange_order(order_link_id, status="unconfirmed", exchange_order_id=result.get("orderId") if result else None, error="close fill not confirmed")
                    return CloseResult(success=False, error=f"Close order sent to Bybit but fill could not be confirmed ({result.get('orderId') if result else None}); verify remote position before retrying")

                exit_price = fill["avgPrice"]
                close_fee = fill["fee"]
                exchange_fill_confirmed = True
                _update_exchange_order(order_link_id, status="filled", exchange_order_id=fill["orderId"],
                                       filled_qty=fill["qty"], avg_price=exit_price, fee=close_fee)

                # Kismi dolum korumasi: PnL ve kapanis YALNIZ dolan miktar uzerinden.
                # Kalan borsa pozisyonu yerelde KORUNUR (silinmez) -> veri kaybi onlenir.
                closed_qty = min(fill["qty"], position["size"])
                remaining = position["size"] - closed_qty
                partial = remaining > max(1e-9, position["size"] * 1e-6)

                if side == "long":
                    pnl = (exit_price - position["entry_price"]) * closed_qty
                else:
                    pnl = (position["entry_price"] - exit_price) * closed_qty

                entry_fee_row = query_one(
                    "SELECT fee FROM trades WHERE account_id = ? AND symbol = ? AND side = ? AND status = 'open' ORDER BY opened_at DESC, id DESC LIMIT 1",
                    (account_id, symbol, side),
                )
                entry_fee = float(entry_fee_row["fee"] or 0) if entry_fee_row else 0.0
                total_fee = entry_fee + close_fee
                net_pnl = pnl - total_fee
                margin = (position["entry_price"] * closed_qty) / position["leverage"]
                pnl_percent = (net_pnl / margin) * 100 if margin > 0 else 0.0

                opened_at = parse_db_time_ms(position["opened_at"])
                duration_seconds = int((int(time.time() * 1000) - opened_at) / 1000) if math.isfinite(opened_at) else None

                if partial:
                    net_pnl, pnl_percent, remaining = _record_partial_close(
                        account_id,
                        position,
                        closed_qty,
                        exit_price,
                        close_fee,
                        reason or "manual_partial",
                    )
                    log.warn(
                        f"Partial close fill: {closed_qty}/{position['size']} {side} {symbol}; {remaining} hala acik (tekrar kapatma denenecek)",
                        {"accountId": account_id, "orderId": fill["orderId"]},
                    )
                    event_bus.emit("position:updated", {
                        "symbol": symbol, "side": side, "size": remaining,
                        "markPrice": position["mark_price"],
                        "unrealizedPnl": (
                            float(position["unrealized_pnl"]) * remaining / float(position["size"])
                            if position["unrealized_pnl"] is not None and position["size"] > 0
                            else None
                        ),
                        "accountId": account_id, "positionId": position["id"],
                    })
                    event_bus.emit("position:closed", {
                        "symbol": symbol, "side": side, "size": closed_qty, "pnl": net_pnl,
                        "exitPrice": exit_price, "reason": reason or "manual_partial",
                        "accountId": account_id, "positionId": position["id"], "partial": True,
                    })
                    return CloseResult(
                        success=False,
                        error=f"Partial close: {closed_qty}/{position['size']} filled; {remaining} still open (retry to close remainder)",
                    )

                with transaction() as conn:
                    conn.execute("DELETE FROM open_positions WHERE id = ?", (position["id"],))
                    conn.execute(
                        """
                        UPDATE trades SET exit_price = ?, pnl = ?, pnl_percent = ?, fee = fee + ?,
                          status = 'closed', exit_reason = ?, closed_at = datetime('now'), duration_seconds = ?
                        WHERE id = (
                          SELECT id FROM trades WHERE account_id = ? AND symbol = ? AND side = ? AND status = 'open'
                          ORDER BY opened_at DESC, id DESC LIMIT 1
                        )
                        """,
                        (exit_price, net_pnl, pnl_percent, close_fee, reason or "manual", duration_seconds,
                         account_id, symbol, side),
                    )

                log.info(f"Position closed: {side} {symbol} PnL: {net_pnl:.2f}", {"accountId": account_id})

                event_bus.emit("position:closed", {
                    "symbol": symbol, "side": side, "pnl": net_pnl, "exitPrice": exit_price,
                    "reason": reason or "manual", "accountId": account_id, "positionId": position["id"],
                })

                return CloseResult(success=True, pnl=net_pnl, pnl_percent=pnl_percent, exit_price=exit_price)
            except Exception as err:  # noqa: BLE001
                if pending_order_link_id:
                    _update_exchange_order(
                        pending_order_link_id,
                        status=_exchange_error_status(exchange_fill_confirmed),
                        error=str(err),
                    )
                log.error(f"Close failed: {symbol} - {err}", {"accountId": account_id})
                return CloseResult(success=False, error=str(err))

    async def get_positions(self, account_id: int) -> list[Position]:
        try:
            creds = _get_credentials(account_id, self.account_type)
            try:
                prepare_bybit_private_ws(account_id, creds, 250, self.private_ws_url)
            except Exception:  # noqa: BLE001
                pass

            cached_positions = get_bybit_ws_positions(account_id, 15_000)
            if cached_positions:
                positions: list[Position] = []
                for p in cached_positions:
                    size = _parse_float(p.get("size") or "0")
                    if not math.isfinite(size) or size <= 0 or not p.get("side"):
                        continue
                    positions.append(Position(
                        id=0, account_id=account_id, symbol=p["symbol"], side=_side_from_bybit(p["side"]),
                        size=size, entry_price=_parse_float(p.get("avgPrice") or "0"),
                        mark_price=_parse_float(p.get("markPrice") or "0"),
                        leverage=int(_parse_float(p.get("leverage") or "1")),
                        unrealized_pnl=_parse_float(p.get("unrealisedPnl") or "0"),
                        tp_price=_parse_float(p.get("takeProfit") or "0") or None,
                        sl_price=_parse_float(p.get("stopLoss") or "0") or None,
                    ))
                return positions

            result = await _private_request(self.base_url, creds, "GET", "/v5/position/list", {
                "category": "linear", "settleCoin": "USDT",
            })
            prime_bybit_private_ws_positions(account_id, creds, result.get("list") or [], self.private_ws_url)

            positions = []
            for p in result.get("list") or []:
                size = _parse_float(p.get("size") or "0")
                if size == 0:
                    continue
                side = "long" if p.get("side") == "Buy" else "short"
                positions.append(Position(
                    id=0, account_id=account_id, symbol=p["symbol"], side=side, size=size,
                    entry_price=_parse_float(p.get("avgPrice") or "0"),
                    mark_price=_parse_float(p.get("markPrice") or "0"),
                    leverage=int(_parse_float(p.get("leverage") or "1")),
                    unrealized_pnl=_parse_float(p.get("unrealisedPnl") or "0"),
                    tp_price=_parse_float(p.get("takeProfit") or "0") or None,
                    sl_price=_parse_float(p.get("stopLoss") or "0") or None,
                ))
            return positions
        except Exception as err:  # noqa: BLE001
            log.error(f"Failed to get positions: {err}", {"accountId": account_id})
            rows = query_all("SELECT * FROM open_positions WHERE account_id = ?", (account_id,))
            return [
                Position(
                    id=r["id"], account_id=r["account_id"], symbol=r["symbol"], side=r["side"], size=r["size"],
                    entry_price=r["entry_price"], mark_price=r["mark_price"], leverage=r["leverage"],
                    unrealized_pnl=r["unrealized_pnl"] or 0, tp_price=r["tp_price"], sl_price=r["sl_price"],
                )
                for r in rows
            ]

    async def get_balance(self, account_id: int) -> Balance:
        try:
            creds = _get_credentials(account_id, self.account_type)
            result = await _private_request(self.base_url, creds, "GET", "/v5/account/wallet-balance", {
                "accountType": "UNIFIED", "coin": "USDT",
            })
            account = (result.get("list") or [None])[0]
            coin = None
            if account:
                coin = next((c for c in (account.get("coin") or []) if c.get("coin") == "USDT"), None)
            account = account or {}
            coin = coin or {}
            available = _parse_float(account.get("totalAvailableBalance") or coin.get("availableToWithdraw") or coin.get("walletBalance") or "0")
            return Balance(
                balance=_parse_float(coin.get("walletBalance") or "0"),
                equity=_parse_float(coin.get("equity") or account.get("totalEquity") or "0"),
                unrealized_pnl=_parse_float(coin.get("unrealisedPnl") or "0"),
                available_balance=available if math.isfinite(available) else 0,
            )
        except Exception as err:  # noqa: BLE001
            log.error(f"Failed to get balance: {err}", {"accountId": account_id})
            raise

    async def set_leverage(self, account_id: int, symbol: str, leverage: int) -> None:
        try:
            symbol = symbol.upper()
            if not await is_tradable_linear_symbol(symbol):
                raise RuntimeError(f"{symbol} is not tradable on Bybit linear USDT")
            creds = _get_credentials(account_id, self.account_type)
            await _private_request(self.base_url, creds, "POST", "/v5/position/set-leverage", {
                "category": "linear",
                "symbol": symbol,
                "buyLeverage": str(leverage),
                "sellLeverage": str(leverage),
            })
        except Exception as err:  # noqa: BLE001
            if "110043" in str(err):
                return
            log.warn(f"Set leverage failed: {symbol} {leverage}x - {err}")
            raise

    async def set_tp_sl(self, account_id: int, symbol: str, side: str,
                        tp: float | None, sl: float | None) -> None:
        try:
            # NOTE: v3 distinguishes undefined (skip) from null (clear to '0'); the
            # Python ABC only exposes Optional, so None here means "clear" (-> '0').
            symbol = symbol.upper()
            if not await is_tradable_linear_symbol(symbol):
                raise RuntimeError(f"{symbol} is not tradable on Bybit linear USDT")
            meta = await get_instrument_meta(symbol)
            if not meta:
                raise RuntimeError(f"Instrument metadata not found for {symbol}")
            creds = _get_credentials(account_id, self.account_type)
            params = {
                "category": "linear",
                "symbol": symbol,
                "positionIdx": _position_idx_for_side(side),
            }
            params["takeProfit"] = "0" if tp is None else _format_order_price(tp, meta)
            params["stopLoss"] = "0" if sl is None else _format_order_price(sl, meta)

            await _private_request(self.base_url, creds, "POST", "/v5/position/trading-stop", params)

            execute(
                "UPDATE open_positions SET tp_price = ?, sl_price = ? WHERE account_id = ? AND symbol = ? AND side = ?",
                (tp, sl, account_id, symbol, side),
            )
        except Exception as err:  # noqa: BLE001
            log.error(f"Set TP/SL failed: {symbol} - {err}", {"accountId": account_id})
            raise

    async def update_mark_prices(self, account_id: int) -> None:
        # Eszamanli uzlasmayi atla (asyncio: add/check arasinda await yok -> atomik).
        if account_id in _reconcile_in_progress:
            return
        _reconcile_in_progress.add(account_id)
        try:
            creds = _get_credentials(account_id, self.account_type)
            try:
                prepare_bybit_private_ws(account_id, creds, 250, self.private_ws_url)
            except Exception:  # noqa: BLE001
                pass

            cached_positions = get_bybit_ws_positions(account_id, 15_000)
            remote_rows = cached_positions if cached_positions is not None else []
            if cached_positions is None:
                result = await _private_request(self.base_url, creds, "GET", "/v5/position/list", {
                    "category": "linear", "settleCoin": "USDT",
                })
                remote_rows = result.get("list") or []
                prime_bybit_private_ws_positions(account_id, creds, remote_rows, self.private_ws_url)

            remote: dict[str, dict] = {}
            for p in remote_rows:
                size = _parse_float(p.get("size") or "0")
                if not math.isfinite(size) or size <= 0 or not p.get("side"):
                    continue
                side = _side_from_bybit(p["side"])
                remote[_position_key(p["symbol"], side)] = {
                    "symbol": p["symbol"], "side": side, "size": size,
                    "entryPrice": _parse_float(p.get("avgPrice") or "0"),
                    "leverage": _parse_float(p.get("leverage") or "0") or 1,
                    "markPrice": _parse_float(p.get("markPrice") or "0"),
                    "unrealizedPnl": _parse_float(p.get("unrealisedPnl") or "0"),
                    "tpPrice": _parse_float(p.get("takeProfit") or "0") or None,
                    "slPrice": _parse_float(p.get("stopLoss") or "0") or None,
                }

            local = query_all("SELECT * FROM open_positions WHERE account_id = ?", (account_id,))
            local_keys = {_position_key(p["symbol"], p["side"]) for p in local}
            local_position_ids = {int(p["id"]) for p in local}
            _prune_reconciliation_counters(
                account_id,
                local_position_ids,
                set(remote),
                local_keys,
            )
            for pos in local:
                hit = remote.get(_position_key(pos["symbol"], pos["side"]))
                miss_key = _missing_position_key(account_id, int(pos["id"]))
                if hit:
                    _missing_remote_positions.pop(miss_key, None)
                    if hit["size"] < pos["size"] * (1 - 1e-6):
                        closed_qty = pos["size"] - hit["size"]
                        fallback_exit = hit["markPrice"] if hit["markPrice"] > 0 else pos["mark_price"] or pos["entry_price"]
                        fallback_pnl = (
                            (fallback_exit - pos["entry_price"]) * closed_qty
                            if pos["side"] == "long"
                            else (pos["entry_price"] - fallback_exit) * closed_qty
                        )
                        resolved = await _resolve_exchange_close(
                            self.base_url,
                            creds,
                            pos["symbol"],
                            pos["side"],
                            {
                                "exitPrice": fallback_exit,
                                "pnl": fallback_pnl,
                                "tpPrice": pos["tp_price"],
                                "slPrice": pos["sl_price"],
                            },
                            {
                                "referenceMs": int(time.time() * 1000),
                                "openedMs": parse_db_time_ms(pos["opened_at"]),
                                "size": closed_qty,
                                "entryPrice": pos["entry_price"],
                            },
                        )
                        official_fee = resolved["openFee"] + resolved["closeFee"]
                        partial_pnl, _, _ = _record_partial_close(
                            account_id,
                            pos,
                            closed_qty,
                            resolved["exitPrice"],
                            resolved["closeFee"],
                            resolved["reason"] or "exchange_partial_sync",
                            resolved_pnl=resolved["pnl"] if resolved["pnlResolved"] else None,
                            resolved_fee=official_fee if official_fee > 0 else None,
                        )
                        log.warn(
                            f"Synced partial Bybit close: {pos['side']} {closed_qty} {pos['symbol']} pnl={partial_pnl:.2f}",
                            {"accountId": account_id},
                        )
                        event_bus.emit("position:closed", {
                            "symbol": pos["symbol"], "side": pos["side"], "size": closed_qty,
                            "pnl": partial_pnl, "exitPrice": resolved["exitPrice"],
                            "reason": resolved["reason"] or "exchange_partial_sync",
                            "accountId": account_id, "positionId": pos["id"], "partial": True,
                        })
                    synced_entry = hit["entryPrice"] if hit["entryPrice"] > 0 else pos["entry_price"]
                    synced_leverage = hit["leverage"] if hit["leverage"] > 0 else pos["leverage"]
                    execute(
                        """
                        UPDATE open_positions
                        SET size = ?, entry_price = ?, leverage = ?, mark_price = ?,
                            unrealized_pnl = ?, tp_price = ?, sl_price = ?
                        WHERE id = ?
                        """,
                        (
                            hit["size"], synced_entry, synced_leverage, hit["markPrice"],
                            hit["unrealizedPnl"], hit["tpPrice"], hit["slPrice"], pos["id"],
                        ),
                    )
                    execute(
                        """
                        UPDATE trades SET size = ?, entry_price = ?, leverage = ?
                        WHERE id = (
                          SELECT id FROM trades
                          WHERE account_id = ? AND symbol = ? AND side = ? AND status = 'open'
                          ORDER BY opened_at DESC, id DESC LIMIT 1
                        )
                        """,
                        (
                            hit["size"], synced_entry, synced_leverage,
                            account_id, pos["symbol"], pos["side"],
                        ),
                    )
                    event_bus.emit("position:updated", {
                        "symbol": pos["symbol"], "side": pos["side"], "size": hit["size"],
                        "unrealizedPnl": hit["unrealizedPnl"],
                        "markPrice": hit["markPrice"], "accountId": account_id, "positionId": pos["id"],
                    })
                    continue

                miss_count = _missing_remote_positions.get(miss_key, 0) + 1
                _missing_remote_positions[miss_key] = miss_count
                if miss_count < REMOTE_MISSING_CLOSE_THRESHOLD:
                    log.warn(f"Bybit position missing remotely ({miss_count}/{REMOTE_MISSING_CLOSE_THRESHOLD}): {pos['side']} {pos['symbol']}", {"accountId": account_id})
                    continue

                opened_at = parse_db_time_ms(pos["opened_at"])
                fallback_exit = pos["mark_price"] if (pos["mark_price"] and pos["mark_price"] > 0) else pos["entry_price"]
                fallback_pnl = pos["unrealized_pnl"] or (
                    (fallback_exit - pos["entry_price"]) * pos["size"]
                    if pos["side"] == "long"
                    else (pos["entry_price"] - fallback_exit) * pos["size"]
                )
                resolved = await _resolve_exchange_close(self.base_url, creds, pos["symbol"], pos["side"], {
                    "exitPrice": fallback_exit, "pnl": fallback_pnl,
                    "tpPrice": pos["tp_price"], "slPrice": pos["sl_price"],
                }, {
                    "referenceMs": int(time.time() * 1000),
                    "openedMs": opened_at,
                    "size": pos["size"],
                    "entryPrice": pos["entry_price"],
                })
                exit_price = resolved["exitPrice"]
                pnl = resolved["pnl"]
                exit_reason = resolved["reason"]
                current_trade = query_one(
                    """
                    SELECT fee FROM trades
                    WHERE account_id = ? AND symbol = ? AND side = ? AND status = 'open'
                    ORDER BY opened_at DESC, id DESC LIMIT 1
                    """,
                    (account_id, pos["symbol"], pos["side"]),
                )
                existing_fee = float(current_trade["fee"] or 0) if current_trade else 0.0
                official_fee = resolved["openFee"] + resolved["closeFee"]
                if not resolved["pnlResolved"]:
                    pnl -= official_fee if official_fee > 0 else existing_fee
                margin = (pos["entry_price"] * pos["size"]) / (pos["leverage"] or 1)
                pnl_percent = (pnl / margin) * 100 if margin > 0 else 0.0
                duration_seconds = int((int(time.time() * 1000) - opened_at) / 1000) if math.isfinite(opened_at) else None

                with transaction() as conn:
                    conn.execute("DELETE FROM open_positions WHERE id = ?", (pos["id"],))
                    conn.execute(
                        """
                        UPDATE trades SET exit_price = ?, pnl = ?, pnl_percent = ?,
                          fee = CASE WHEN ? > 0 THEN ? ELSE fee END,
                          status = 'closed', exit_reason = ?, closed_at = datetime('now'), duration_seconds = ?
                        WHERE id = (
                          SELECT id FROM trades WHERE account_id = ? AND symbol = ? AND side = ? AND status = 'open'
                          ORDER BY opened_at DESC, id DESC LIMIT 1
                        )
                        """,
                        (
                            exit_price, pnl, pnl_percent,
                            official_fee,
                            official_fee,
                            exit_reason, duration_seconds, account_id, pos["symbol"], pos["side"],
                        ),
                    )
                _missing_remote_positions.pop(miss_key, None)

                event_bus.emit("position:closed", {
                    "symbol": pos["symbol"], "side": pos["side"], "pnl": pnl, "exitPrice": exit_price,
                    "reason": exit_reason, "accountId": account_id, "positionId": pos["id"],
                })
                log.info(f"Synced closed Bybit position: {pos['side']} {pos['symbol']} pnl={pnl:.2f} reason={exit_reason}", {"accountId": account_id})

            # Orphan reconciliation: Bybit positions not tracked locally (filled but never
            # recorded, e.g. confirm timeout/restart). Import after a couple of ticks so we
            # don't race an in-flight open.
            for k, rp in remote.items():
                o_key = f"{account_id}:{k}"
                if k in local_keys:
                    _orphan_remote_positions.pop(o_key, None)
                    continue
                o_count = _orphan_remote_positions.get(o_key, 0) + 1
                _orphan_remote_positions[o_key] = o_count
                if o_count < ORPHAN_IMPORT_THRESHOLD:
                    log.warn(f"Orphan Bybit position seen ({o_count}/{ORPHAN_IMPORT_THRESHOLD}): {rp['side']} {rp['symbol']}", {"accountId": account_id})
                    continue
                _orphan_remote_positions.pop(o_key, None)
                entry = rp["entryPrice"] if rp["entryPrice"] > 0 else rp["markPrice"]
                mark = rp["markPrice"] if rp["markPrice"] > 0 else entry
                if not (entry > 0) or not (rp["size"] > 0):
                    continue
                with transaction() as conn:
                    conn.execute(
                        """
                        INSERT INTO trades (account_id, symbol, side, size, entry_price, leverage, fee, status, entry_reason)
                        VALUES (?, ?, ?, ?, ?, ?, 0, 'open', 'exchange_opened_sync')
                        """,
                        (account_id, rp["symbol"], rp["side"], rp["size"], entry, rp["leverage"] or 1),
                    )
                    conn.execute(
                        """
                        INSERT INTO open_positions (account_id, symbol, side, size, entry_price, mark_price, leverage, unrealized_pnl, tp_price, sl_price)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (account_id, rp["symbol"], rp["side"], rp["size"], entry, mark, rp["leverage"] or 1,
                         rp["unrealizedPnl"], rp["tpPrice"], rp["slPrice"]),
                    )
                event_bus.emit("position:opened", {"symbol": rp["symbol"], "side": rp["side"], "size": rp["size"], "entryPrice": entry, "accountId": account_id})
                log.warn(f"Orphan Bybit position imported: {rp['side']} {rp['size']} {rp['symbol']} @ {entry}", {"accountId": account_id})
        except Exception as err:  # noqa: BLE001
            log.warn(f"Bybit position sync failed: {err}", {"accountId": account_id})
        finally:
            _reconcile_in_progress.discard(account_id)

    async def _resolve_historical_close(self, creds, symbol, side, closed_ms, size=None, entry_price=None):
        close_side = _close_side_for(side)
        match = {"referenceMs": closed_ms, "size": size, "entryPrice": entry_price}
        rng = _close_lookup_range(match)
        exit_price = 0.0
        pnl = float("nan")
        reason = ""

        try:
            cp = await _private_request(self.base_url, creds, "GET", "/v5/position/closed-pnl", {
                "category": "linear", "symbol": symbol, "limit": 100, **rng,
            })
            rec = _pick_closed_pnl_record(cp.get("list") or [], close_side, match)
            if rec:
                ax = _bybit_number(rec.get("avgExitPrice"))
                cpnl = _bybit_number(rec.get("closedPnl"))
                if math.isfinite(ax) and ax > 0:
                    exit_price = ax
                if math.isfinite(cpnl):
                    pnl = cpnl
        except Exception as err:  # noqa: BLE001
            log.warn(f"backfill closed-pnl failed {symbol}: {err}")

        try:
            ex = await _private_request(self.base_url, creds, "GET", "/v5/execution/list", {
                "category": "linear", "symbol": symbol, "limit": 100, **rng,
            })
            last = _pick_closing_execution(ex.get("list") or [], close_side, match)
            if last:
                reason = _close_reason_from_execution(last)
        except Exception as err:  # noqa: BLE001
            log.warn(f"backfill execution failed {symbol}: {err}")

        if exit_price <= 0 and not reason:
            return None
        return {"exitPrice": exit_price, "pnl": pnl, "reason": reason}

    # One-off: re-resolve exit_reason / exit_price / pnl for trades closed by the
    # generic 'exchange_closed_sync' tag, using Bybit closed-pnl + execution history.
    async def backfill_close_reasons(self) -> dict:
        rows = query_all(
            """
            SELECT t.id, t.account_id, t.symbol, t.side, t.closed_at, t.exit_price, t.pnl,
                   t.entry_price, t.size, t.leverage
            FROM trades t JOIN accounts a ON a.id = t.account_id
            WHERE t.exit_reason = 'exchange_closed_sync' AND a.type = ?
            ORDER BY t.id DESC
            """,
            (self.account_type,),
        )
        if not rows:
            return {"scanned": 0, "updated": 0}
        log.info(f"Backfill close reasons ({self.account_type}): scanning {len(rows)} trades...")

        updated = 0
        for r in rows:
            try:
                creds = _get_credentials(r["account_id"], self.account_type)
                info = await self._resolve_historical_close(creds, r["symbol"], r["side"], parse_db_time_ms(r["closed_at"]), r["size"], r["entry_price"])
                if not info:
                    continue
                exit_price = info["exitPrice"] if info["exitPrice"] > 0 else r["exit_price"]
                pnl = info["pnl"] if math.isfinite(info["pnl"]) else r["pnl"]
                reason = info["reason"] or "exchange_closed_sync"
                if reason == "exchange_closed_sync" and exit_price == r["exit_price"] and pnl == r["pnl"]:
                    continue
                margin = (r["entry_price"] * r["size"]) / (r["leverage"] or 1)
                pnl_percent = (pnl / margin) * 100 if margin > 0 else 0.0
                execute(
                    "UPDATE trades SET exit_price = ?, pnl = ?, pnl_percent = ?, exit_reason = ? WHERE id = ?",
                    (exit_price, pnl, pnl_percent, reason, r["id"]),
                )
                updated += 1
            except Exception as err:  # noqa: BLE001
                log.warn(f"Backfill trade {r['id']} ({r['symbol']}) failed: {err}")
        log.info(f"Backfill close reasons ({self.account_type}): {updated}/{len(rows)} updated")
        return {"scanned": len(rows), "updated": updated}

    async def request_demo_funds(self, account_id: int, coin: str = "USDT", amount_str: str = "100000") -> None:
        creds = _get_credentials(account_id, self.account_type)
        await _private_request(self.base_url, creds, "POST", "/v5/account/demo-apply-money", {
            "adjustType": 0,
            "utaDemoApplyMoney": [{"coin": coin, "amountStr": amount_str}],
        })


bybit_engine = BybitEngine(BASE_URL, "real", "bybit")
demo_engine = BybitEngine(DEMO_BASE_URL, "demo", "demo")


def live_engine_for(engine_name: str | None):
    if engine_name == "bybit":
        return bybit_engine
    if engine_name == "demo":
        return demo_engine
    return None
