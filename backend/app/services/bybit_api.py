import asyncio
import os
import time
from dataclasses import dataclass

import httpx

from ..core.logger import create_logger

log = create_logger("bybit-api")

BASE_URL = os.environ.get("BYBIT_REST_BASE_URL") or (
    "https://api-testnet.bybit.com" if os.environ.get("BYBIT_TESTNET") == "true" else "https://api.bybit.com"
)

INVALID_SYMBOL_TTL = 24 * 60 * 60 * 1000
RATE_LIMIT_DELAY = max(50, int(os.environ.get("BYBIT_RATE_LIMIT_DELAY_MS") or 500))
REQUEST_TIMEOUT_MS = max(2000, int(os.environ.get("BYBIT_REQUEST_TIMEOUT_MS") or 8000))
MAX_ADAPTIVE_COOLDOWN_MS = max(5000, int(os.environ.get("BYBIT_MAX_ADAPTIVE_COOLDOWN_MS") or 60000))
FULL_TICKERS_CACHE_TTL = max(5000, int(os.environ.get("BYBIT_TICKERS_CACHE_TTL_MS") or 15000))
TICKER_CACHE_TTL = max(5000, int(os.environ.get("BYBIT_TICKER_CACHE_TTL_MS") or 15000))
KLINE_CACHE_TTL = max(5000, int(os.environ.get("BYBIT_KLINE_CACHE_TTL_MS") or 30000))
FUNDING_HISTORY_CACHE_TTL = max(10000, int(os.environ.get("BYBIT_FUNDING_HISTORY_CACHE_TTL_MS") or 300000))
VALID_SYMBOLS_CACHE_TTL = max(60000, int(os.environ.get("BYBIT_VALID_SYMBOLS_CACHE_TTL_MS") or 6 * 60 * 60 * 1000))
OI_CHANGE_CACHE_TTL = max(10000, int(os.environ.get("BYBIT_OI_CHANGE_CACHE_TTL_MS") or 180000))


def _now() -> float:
    return time.monotonic() * 1000.0


def to_finite(value, fallback: float = 0.0) -> float:
    try:
        n = float(value)
        return n if n == n and n not in (float("inf"), float("-inf")) else fallback
    except (TypeError, ValueError):
        return fallback


def normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


_invalid_symbols: dict[str, float] = {}


def mark_invalid_symbol(symbol: str) -> None:
    _invalid_symbols[normalize_symbol(symbol)] = _now()


def kline_ttl(interval: str) -> int:
    return {
        "15": 60000, "30": 120000, "60": 180000, "120": 300000,
        "240": 600000, "D": 1800000, "W": 3600000,
    }.get(interval, KLINE_CACHE_TTL)


@dataclass
class _Gate:
    last: float = 0.0
    cooldown_until: float = 0.0


_gate = _Gate()
_gate_lock = asyncio.Lock()
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT_MS / 1000.0)
    return _client


async def close_client() -> None:
    global _client
    if _client is None:
        return
    await _client.aclose()
    _client = None


async def _rate_limit() -> None:
    async with _gate_lock:
        wait_until = max(_gate.last + RATE_LIMIT_DELAY, _gate.cooldown_until)
        wait = max(0.0, wait_until - _now())
        if wait > 0:
            await asyncio.sleep(wait / 1000.0)
        _gate.last = _now()


def _apply_cooldown(base_ms: float) -> None:
    _gate.cooldown_until = max(_gate.cooldown_until, _now() + min(MAX_ADAPTIVE_COOLDOWN_MS, base_ms))


def _is_rate_limit_msg(msg: str | None) -> bool:
    m = (msg or "").lower()
    return "too many visits" in m or "rate limit" in m


def _is_invalid_symbol_msg(msg: str | None) -> bool:
    m = (msg or "").lower()
    return "symbol invalid" in m or "invalid symbol" in m or "params error" in m


async def request(endpoint: str, params: dict | None = None, retries: int = 0):
    await _rate_limit()
    try:
        res = await _get_client().get(f"{BASE_URL}{endpoint}", params=params or {})
    except (httpx.TimeoutException, httpx.NetworkError) as err:
        if retries < 2:
            backoff = 1500 * (retries + 1)
            _apply_cooldown(backoff)
            await asyncio.sleep(backoff / 1000.0)
            return await request(endpoint, params, retries + 1)
        raise err

    if res.status_code != 200:
        if res.status_code == 429 and retries < 3:
            backoff = 5000 * (retries + 1)
            _apply_cooldown(backoff)
            await asyncio.sleep(backoff / 1000.0)
            return await request(endpoint, params, retries + 1)
        raise RuntimeError(f"Bybit API error: {res.status_code} {res.reason_phrase}")

    data = res.json()
    if data.get("retCode") != 0:
        if _is_rate_limit_msg(data.get("retMsg")) and retries < 3:
            backoff = 5000 * (retries + 1)
            _apply_cooldown(backoff)
            await asyncio.sleep(backoff / 1000.0)
            return await request(endpoint, params, retries + 1)
        raise RuntimeError(f"Bybit API error: {data.get('retMsg')}")

    _gate.cooldown_until = 0.0
    return data["result"]


# ---- caches ----
_ticker_cache: dict[str, dict] = {}
_tickers_cache: dict | None = None
_valid_symbols_cache: dict | None = None
_kline_cache: dict[str, dict] = {}
_funding_history_cache: dict[str, dict] = {}
_oi_change_cache: dict[str, dict] = {}
# Single-flight: eszamanli cagrilar tek toplu istegi paylasir (thundering herd onler)
_tickers_lock = asyncio.Lock()
# Kline single-flight: ayni sembol+interval icin ucusta olan tek istek paylasilir
_kline_inflight: dict[str, asyncio.Future] = {}


async def get_tickers() -> list[dict]:
    global _tickers_cache
    if _tickers_cache and _now() - _tickers_cache["at"] < FULL_TICKERS_CACHE_TTL:
        return _tickers_cache["list"]
    # Single-flight: ayni anda gelen onlarca cagri tek toplu istegi paylasir.
    async with _tickers_lock:
        if _tickers_cache and _now() - _tickers_cache["at"] < FULL_TICKERS_CACHE_TTL:
            return _tickers_cache["list"]
        result = await request("/v5/market/tickers", {"category": "linear"})
        now = _now()
        lst = result.get("list") or []
        _tickers_cache = {"list": lst, "at": now}
        for t in lst:
            _ticker_cache[normalize_symbol(t["symbol"])] = {"ticker": t, "at": now}
        return lst


async def get_instrument_cache() -> dict:
    global _valid_symbols_cache
    if _valid_symbols_cache and _now() - _valid_symbols_cache["at"] < VALID_SYMBOLS_CACHE_TTL:
        return _valid_symbols_cache
    symbols: set[str] = set()
    meta: dict[str, dict] = {}
    cursor = ""
    while True:
        params = {"category": "linear", "limit": "1000"}
        if cursor:
            params["cursor"] = cursor
        result = await request("/v5/market/instruments-info", params)
        for item in result.get("list") or []:
            symbol = normalize_symbol(item["symbol"])
            if not symbol.endswith("USDT"):
                continue
            if item.get("quoteCoin") and item["quoteCoin"] != "USDT":
                continue
            if item.get("settleCoin") and item["settleCoin"] != "USDT":
                continue
            if item.get("status") and item["status"] != "Trading":
                continue
            symbols.add(symbol)
            lot = item.get("lotSizeFilter") or {}
            price = item.get("priceFilter") or {}
            meta[symbol] = {
                "symbol": symbol,
                "minOrderQty": to_finite(lot.get("minOrderQty")),
                "maxOrderQty": to_finite(lot.get("maxOrderQty")),
                "qtyStep": to_finite(lot.get("qtyStep")),
                "minNotionalValue": to_finite(lot.get("minNotionalValue")),
                "tickSize": to_finite(price.get("tickSize")),
            }
        cursor = result.get("nextPageCursor") or ""
        if not cursor:
            break
    _valid_symbols_cache = {"symbols": symbols, "meta": meta, "at": _now()}
    return _valid_symbols_cache


async def get_tradable_linear_symbols() -> set[str]:
    return (await get_instrument_cache())["symbols"]


async def get_instrument_meta(symbol: str) -> dict | None:
    normalized = normalize_symbol(symbol)
    if not normalized:
        return None
    return (await get_instrument_cache())["meta"].get(normalized)


async def is_tradable_linear_symbol(symbol: str) -> bool:
    normalized = normalize_symbol(symbol)
    if not normalized:
        return False
    inv = _invalid_symbols.get(normalized)
    if inv and _now() - inv < INVALID_SYMBOL_TTL:
        return False
    if inv:
        _invalid_symbols.pop(normalized, None)
    try:
        symbols = await get_tradable_linear_symbols()
        ok = normalized in symbols
        if not ok:
            mark_invalid_symbol(normalized)
        return ok
    except Exception as err:  # noqa: BLE001
        log.warn(f"Failed to load Bybit instrument whitelist; rejecting {normalized}: {err}")
        return False


def get_cached_ticker(symbol: str) -> dict | None:
    hit = _ticker_cache.get(normalize_symbol(symbol))
    if not hit or _now() - hit["at"] > TICKER_CACHE_TTL:
        return None
    return hit["ticker"]


async def get_ticker(symbol: str) -> dict | None:
    symbol = normalize_symbol(symbol)
    if not await is_tradable_linear_symbol(symbol):
        return None
    cached = get_cached_ticker(symbol)
    if cached:
        return cached
    # Cache miss: sembol-basina ayri istek YERINE tek toplu istekle (single-flight,
    # tum semboller icin paylasilir) tum ticker cache'ini isit. N bot x N sembol ->
    # ~1 toplu istek/15s. Bu, eszamanli yukteki Bybit timeout firtinasini onler.
    try:
        await get_tickers()
    except Exception as err:  # noqa: BLE001
        log.warn(f"Ticker bulk refresh failed for {symbol}: {err}")
    hit = _ticker_cache.get(symbol)
    if hit:
        return hit["ticker"]
    return None


async def get_klines(symbol: str, interval: str = "5", limit: int = 200) -> list[dict]:
    symbol = normalize_symbol(symbol)
    if not await is_tradable_linear_symbol(symbol):
        return []
    inv = _invalid_symbols.get(symbol)
    if inv and _now() - inv < INVALID_SYMBOL_TTL:
        return []
    if inv:
        _invalid_symbols.pop(symbol, None)
    key = f"{symbol}:{interval}:{limit}"
    cached = _kline_cache.get(key)
    if cached and _now() - cached["at"] < kline_ttl(interval):
        return cached["data"]
    # Single-flight: ayni key icin zaten ucusta bir istek varsa onun sonucunu paylas
    # (11 bot ayni sembolu eszamanli isteyince tek HTTP cagrisi yapilir).
    inflight = _kline_inflight.get(key)
    if inflight is not None:
        return await inflight
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    _kline_inflight[key] = fut
    outcome: list[dict] = []
    try:
        result = await request("/v5/market/kline", {"category": "linear", "symbol": symbol, "interval": interval, "limit": str(limit)})
        data = [
            {
                "time": int(int(k[0]) / 1000),
                "open": to_finite(k[1]),
                "high": to_finite(k[2]),
                "low": to_finite(k[3]),
                "close": to_finite(k[4]),
                "volume": to_finite(k[5]),
            }
            for k in result.get("list", [])
        ][::-1]
        _kline_cache[key] = {"data": data, "at": _now()}
        outcome = data
    except Exception as err:  # noqa: BLE001
        if _is_invalid_symbol_msg(str(err)):
            mark_invalid_symbol(symbol)
        else:
            stale = _kline_cache.get(key)
            if stale:
                outcome = stale["data"]
            else:
                log.warn(f"Kline unavailable for {symbol} {interval}: {err}")
    finally:
        # Bekleyenler sonsuza dek beklemesin (iptal/CancelledError dahil garanti)
        _kline_inflight.pop(key, None)
        if not fut.done():
            fut.set_result(outcome)
    return outcome


async def get_klines_range(symbol: str, interval: str, start_ms: int, end_ms: int) -> list[dict]:
    symbol = normalize_symbol(symbol)
    out: list[dict] = []
    seen: set[int] = set()
    cursor_end = end_ms
    for _ in range(4000):
        try:
            result = await request("/v5/market/kline", {
                "category": "linear", "symbol": symbol, "interval": interval,
                "start": str(max(0, int(start_ms))), "end": str(int(cursor_end)), "limit": "1000",
            })
            lst = result.get("list") or []
        except Exception as err:  # noqa: BLE001
            if _is_invalid_symbol_msg(str(err)):
                mark_invalid_symbol(symbol)
            log.warn(f"Range kline unavailable for {symbol} {interval}: {err}")
            break
        if not lst:
            break
        oldest = cursor_end
        for k in lst:
            t0 = int(k[0])
            if t0 < oldest:
                oldest = t0
            if t0 < start_ms or t0 in seen:
                continue
            seen.add(t0)
            out.append({
                "time": int(t0 / 1000), "open": to_finite(k[1]), "high": to_finite(k[2]),
                "low": to_finite(k[3]), "close": to_finite(k[4]), "volume": to_finite(k[5]),
            })
        if oldest <= start_ms:
            break
        next_end = oldest - 1
        if next_end >= cursor_end:
            break
        cursor_end = next_end
        if len(lst) < 1000:
            break
    out.sort(key=lambda x: x["time"])
    return out


async def get_last_price(symbol: str) -> float:
    ticker = await get_ticker(symbol)
    if not ticker:
        raise RuntimeError(f"Ticker not found for {symbol}")
    price = to_finite(ticker.get("lastPrice"), float("nan"))
    if not (price == price) or price <= 0:
        raise RuntimeError(f"Invalid last price for {symbol}")
    return price


async def get_top_gainers(limit: int = 20) -> list[dict]:
    tickers = await get_tickers()
    usdt = [t for t in tickers if t["symbol"].endswith("USDT") and to_finite(t.get("turnover24h")) > 10_000_000]
    usdt.sort(key=lambda t: abs(to_finite(t.get("price24hPcnt"))), reverse=True)
    return usdt[:limit]


async def get_funding_rate(symbol: str) -> float:
    ticker = await get_ticker(symbol)
    if not ticker:
        return 0.0
    return to_finite(ticker.get("fundingRate"))


async def get_funding_rate_history(symbol: str, limit: int = 20) -> list[dict]:
    symbol = normalize_symbol(symbol)
    if not await is_tradable_linear_symbol(symbol):
        return []
    key = f"{symbol}:{limit}"
    cached = _funding_history_cache.get(key)
    if cached and _now() - cached["at"] < FUNDING_HISTORY_CACHE_TTL:
        return cached["data"]
    try:
        result = await request("/v5/market/funding/history", {"category": "linear", "symbol": symbol, "limit": str(limit)})
        data = [
            {"symbol": it["symbol"], "fundingRate": to_finite(it["fundingRate"]), "fundingRateTimestamp": int(it["fundingRateTimestamp"])}
            for it in result.get("list", [])
        ]
        _funding_history_cache[key] = {"data": data, "at": _now()}
        return data
    except Exception as err:  # noqa: BLE001
        stale = _funding_history_cache.get(key)
        if stale:
            return stale["data"]
        log.warn(f"Failed to get funding rate history for {symbol}: {err}")
        return []


async def get_funding_rate_history_range(symbol: str, start_ms: int, end_ms: int) -> list[dict]:
    symbol = normalize_symbol(symbol)
    if not await is_tradable_linear_symbol(symbol):
        return []
    out: list[dict] = []
    seen: set[int] = set()
    cursor_end = end_ms
    for _ in range(200):
        try:
            result = await request("/v5/market/funding/history", {
                "category": "linear", "symbol": symbol,
                "startTime": str(max(0, int(start_ms))), "endTime": str(int(cursor_end)), "limit": "200",
            })
            lst = result.get("list") or []
        except Exception as err:  # noqa: BLE001
            if _is_invalid_symbol_msg(str(err)):
                mark_invalid_symbol(symbol)
            log.warn(f"Range funding unavailable for {symbol}: {err}")
            break
        if not lst:
            break
        oldest = cursor_end
        for it in lst:
            try:
                ts = int(it["fundingRateTimestamp"])
                finite = True
            except (TypeError, ValueError, KeyError):
                ts = 0
                finite = False
            if finite and ts < oldest:
                oldest = ts
            if not finite or ts < start_ms or ts in seen:
                continue
            seen.add(ts)
            out.append({"symbol": it["symbol"], "fundingRate": to_finite(it["fundingRate"]), "fundingRateTimestamp": ts})
        if oldest <= start_ms:
            break
        next_end = oldest - 1
        if next_end >= cursor_end:
            break
        cursor_end = next_end
        if len(lst) < 200:
            break
    out.sort(key=lambda x: x["fundingRateTimestamp"])
    return out


async def get_open_interest(symbol: str) -> dict:
    ticker = await get_ticker(symbol)
    if not ticker:
        return {"oi": 0.0, "oiValue": 0.0}
    return {"oi": to_finite(ticker.get("openInterest")), "oiValue": to_finite(ticker.get("openInterestValue"))}


async def get_open_interest_change(symbol: str, interval_time: str = "1h") -> float:
    symbol = normalize_symbol(symbol)
    if not await is_tradable_linear_symbol(symbol):
        return 0.0
    key = f"{symbol}:{interval_time}"
    cached = _oi_change_cache.get(key)
    if cached and _now() - cached["at"] < OI_CHANGE_CACHE_TTL:
        return cached["value"]
    try:
        result = await request("/v5/market/open-interest", {"category": "linear", "symbol": symbol, "intervalTime": interval_time, "limit": "2"})
        lst = result.get("list") or []
        latest = to_finite(lst[0]["openInterest"]) if len(lst) >= 1 else 0.0
        prior = to_finite(lst[1]["openInterest"]) if len(lst) >= 2 else 0.0
        change = ((latest - prior) / prior) * 100 if len(lst) >= 2 and prior > 0 else 0.0
        _oi_change_cache[key] = {"value": change, "at": _now()}
        return change
    except Exception as err:  # noqa: BLE001
        stale = _oi_change_cache.get(key)
        if stale:
            return stale["value"]
        log.warn(f"Failed to get OI change for {symbol}: {err}")
        return 0.0
