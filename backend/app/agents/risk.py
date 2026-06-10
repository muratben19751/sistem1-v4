import asyncio
import math
from contextlib import asynccontextmanager

from ..core.logger import create_logger
from ..core.event_bus import event_bus
from ..core.time import now_ms
from ..db.database import query_one
from ..engines.registry import get_engine

log = create_logger("risk")

_cooldown_map: dict[str, float] = {}
COOLDOWN_MS = 15 * 60 * 1000
MIN_POSITION_NOTIONAL_USD = 5

# Hesap-seviyesi kilit: risk-kontrol + emir-acma'yi atomik yapar ki eszamanli istekler
# (farkli sembollerde bile) max_positions'i asamasin. Sembol-seviyesi engine kilitleri
# bunu saglamaz.
_account_locks: dict[int, asyncio.Lock] = {}


def _account_lock(account_id: int) -> asyncio.Lock:
    lock = _account_locks.get(account_id)
    if lock is None:
        lock = asyncio.Lock()
        _account_locks[account_id] = lock
    return lock


@asynccontextmanager
async def account_gate(account_id: int):
    async with _account_lock(account_id):
        yield


def _finite(v) -> bool:
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _first_finite(*values, default=float("nan")) -> float:
    for value in values:
        if _finite(value):
            return float(value)
    return default


async def evaluate_risk(params: dict) -> dict:
    account_id = params["accountId"]
    symbol = params["symbol"]
    side = params["side"]
    score = params["score"]
    price = params["price"]

    account = query_one("SELECT initial_balance, engine FROM accounts WHERE id = ?", (account_id,))
    if not account:
        return {"approved": False, "size": 0, "leverage": 0, "reason": "Account not found"}

    bot_config = query_one("SELECT * FROM bot_configs WHERE account_id = ?", (account_id,))
    if not bot_config:
        return {"approved": False, "size": 0, "leverage": 0, "reason": "No bot config"}

    engine = get_engine(account["engine"])
    wallet = query_one("SELECT * FROM paper_wallets WHERE account_id = ?", (account_id,))
    paper_totals = None
    if engine.name == "paper":
        paper_totals = query_one(
            """
            SELECT
              COALESCE(SUM(entry_price * size / CASE WHEN leverage > 0 THEN leverage ELSE 1 END), 0) as reserved_margin,
              COALESCE(SUM(COALESCE(unrealized_pnl, 0)), 0) as unrealized_pnl
            FROM open_positions WHERE account_id = ?
            """,
            (account_id,),
        )
    live_balance = None if engine.name == "paper" else await engine.get_balance(account_id)

    if engine.name == "paper":
        available_balance = wallet["balance"] if wallet else float("nan")
        equity = (
            (wallet["balance"] if wallet else 0)
            + (paper_totals["reserved_margin"] if paper_totals else 0)
            + (paper_totals["unrealized_pnl"] if paper_totals else 0)
        )
    else:
        available_balance = _first_finite(
            live_balance.available_balance,
            live_balance.balance,
            live_balance.equity,
        )
        equity = _first_finite(live_balance.equity, live_balance.balance, available_balance)

    candidates = [c for c in [
        wallet["initial_balance"] if wallet else None,
        account["initial_balance"],
        equity,
        available_balance,
    ] if _finite(c) and float(c) > 0]
    initial_balance = candidates[0] if candidates else 0

    if not _finite(available_balance):
        return {"approved": False, "size": 0, "leverage": 0, "reason": "No usable balance"}
    if available_balance <= 0:
        return {"approved": False, "size": 0, "leverage": 0, "reason": "Balance depleted"}

    if not params.get("skipScoreCheck") and side == "long" and score < bot_config["long_min_score"]:
        return {"approved": False, "size": 0, "leverage": 0, "reason": f"Score {score} < min long {bot_config['long_min_score']}"}
    if not params.get("skipScoreCheck") and side == "short" and score > bot_config["short_min_score"]:
        return {"approved": False, "size": 0, "leverage": 0, "reason": f"Score {score} > min short {bot_config['short_min_score']}"}

    open_positions = query_one("SELECT COUNT(*) as cnt FROM open_positions WHERE account_id = ?", (account_id,))
    if open_positions["cnt"] >= bot_config["max_positions"]:
        return {"approved": False, "size": 0, "leverage": 0, "reason": f"Max positions reached ({open_positions['cnt']}/{bot_config['max_positions']})"}

    existing = query_one("SELECT * FROM open_positions WHERE account_id = ? AND symbol = ?", (account_id, symbol))
    if existing:
        return {"approved": False, "size": 0, "leverage": 0, "reason": f"Already has position on {symbol}"}

    cooldown_key = f"{account_id}:{symbol}"
    last_cooldown = _cooldown_map.get(cooldown_key)
    if last_cooldown and now_ms() - last_cooldown < COOLDOWN_MS:
        remaining = math.ceil((COOLDOWN_MS - (now_ms() - last_cooldown)) / 60000)
        return {"approved": False, "size": 0, "leverage": 0, "reason": f"{symbol} cooldown ({remaining}m left)"}

    if bot_config["max_drawdown_enabled"]:
        peak_row = query_one("SELECT MAX(equity) as peak FROM equity_snapshots WHERE account_id = ?", (account_id,))
        current_equity = equity if _finite(equity) else available_balance
        peak_balance = max(initial_balance, (peak_row["peak"] if peak_row and peak_row["peak"] else 0), current_equity)
        drawdown_pcnt = ((peak_balance - current_equity) / peak_balance) * 100 if peak_balance > 0 else 0
        if drawdown_pcnt > bot_config["max_drawdown"]:
            event_bus.emit("risk:circuit_breaker", {"accountId": account_id, "drawdown": drawdown_pcnt})
            return {"approved": False, "size": 0, "leverage": 0, "reason": f"Circuit breaker: drawdown {drawdown_pcnt:.1f}% > max {bot_config['max_drawdown']}%"}

    configured_leverage = bot_config["leverage"]
    requested_leverage = params.get("requestedLeverage")
    if requested_leverage is not None:
        if not _finite(requested_leverage) or requested_leverage <= 0:
            return {"approved": False, "size": 0, "leverage": 0, "reason": "Invalid requested leverage"}
        if requested_leverage > configured_leverage:
            return {"approved": False, "size": 0, "leverage": 0, "reason": f"Requested leverage {requested_leverage}x exceeds bot config {configured_leverage}x"}
    leverage = requested_leverage if requested_leverage is not None else configured_leverage
    size_pct = (bot_config["position_size_pct"] or 2) / 100

    if not _finite(price) or price <= 0:
        return {"approved": False, "size": 0, "leverage": 0, "reason": "Invalid market price"}
    if not _finite(leverage) or leverage <= 0:
        return {"approved": False, "size": 0, "leverage": 0, "reason": "Invalid leverage"}
    if not _finite(size_pct) or size_pct <= 0:
        return {"approved": False, "size": 0, "leverage": 0, "reason": "Invalid position size"}

    capital_base = min(available_balance, initial_balance * 3)
    margin = capital_base * size_pct
    position_value = margin * leverage
    position_value = min(position_value, capital_base * 0.5 * leverage)
    position_value = min(position_value, initial_balance * leverage * 2)
    max_allowed = position_value

    if params.get("requestedNotional") is not None:
        requested_notional = float(params["requestedNotional"])
        if not _finite(requested_notional) or requested_notional <= 0:
            return {"approved": False, "size": 0, "leverage": 0, "reason": "Invalid requested notional"}
        if requested_notional > max_allowed * 1.000001:
            return {"approved": False, "size": 0, "leverage": 0, "reason": f"Requested notional ${requested_notional:.2f} exceeds risk cap ${max_allowed:.2f}"}
        position_value = requested_notional

    if position_value <= 0 or position_value < MIN_POSITION_NOTIONAL_USD:
        return {"approved": False, "size": 0, "leverage": 0, "reason": f"Position notional too small (< ${MIN_POSITION_NOTIONAL_USD})"}

    size = position_value / price
    log.info(f"Risk approved: {side} {symbol} size={size:.2f} notional=${position_value:.0f} lev={leverage}", {"accountId": account_id})
    event_bus.emit("risk:approved", {"symbol": symbol, "side": side, "size": size, "leverage": leverage, "accountId": account_id})
    return {"approved": True, "size": size, "leverage": leverage}


def set_cooldown(account_id: int, symbol: str) -> None:
    _cooldown_map[f"{account_id}:{symbol}"] = now_ms()
    _purge_stale_cooldowns()


def _purge_stale_cooldowns() -> None:
    now = now_ms()
    for key in [k for k, ts in _cooldown_map.items() if now - ts > COOLDOWN_MS]:
        _cooldown_map.pop(key, None)
