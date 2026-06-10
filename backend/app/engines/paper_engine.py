import asyncio
import math
import re

from ..core.config import config
from ..core.logger import create_logger
from ..core.event_bus import event_bus
from ..core.time import parse_db_time_ms, now_ms
from ..db.database import query_one, query_all, transaction
from ..services.bybit_api import get_last_price
from .trade_engine import (
    TradeEngine, OrderParams, OrderResult, CloseResult, Position, Balance,
)

log = create_logger("paper-engine")

_locks: dict[str, asyncio.Lock] = {}


def _lock_for(account_id: int, symbol: str) -> asyncio.Lock:
    key = f"{account_id}:{symbol.upper()}"
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


class PaperEngine(TradeEngine):
    name = "paper"

    async def place_order(self, params: OrderParams) -> OrderResult:
        if not isinstance(params.account_id, int) or isinstance(params.account_id, bool) or params.account_id <= 0:
            return OrderResult(success=False, error="Invalid account")
        if not isinstance(params.symbol, str) or not re.fullmatch(r"[A-Z0-9]{1,30}USDT", params.symbol.strip().upper()):
            return OrderResult(success=False, error="Invalid symbol")
        if params.side not in ("long", "short"):
            return OrderResult(success=False, error="Invalid side")
        if not isinstance(params.leverage, int) or isinstance(params.leverage, bool) or not 1 <= params.leverage <= 125:
            return OrderResult(success=False, error="Invalid leverage")
        try:
            size = float(params.size)
        except (TypeError, ValueError):
            return OrderResult(success=False, error="Invalid size")
        if not math.isfinite(size) or size <= 0:
            return OrderResult(success=False, error="Invalid size")

        symbol = params.symbol.strip().upper()
        params.size = size
        async with _lock_for(params.account_id, symbol):
            account_id = params.account_id
            wallet = query_one("SELECT * FROM paper_wallets WHERE account_id = ?", (account_id,))
            if not wallet:
                return OrderResult(success=False, error="Wallet not found")

            existing = query_one(
                "SELECT side FROM open_positions WHERE account_id = ? AND symbol = ? LIMIT 1",
                (account_id, symbol),
            )
            if existing:
                return OrderResult(success=False, error=f"Position already exists for {symbol} ({existing['side']})")

            try:
                raw_price = await get_last_price(symbol)
                slippage_dir = 1 if params.side == "long" else -1
                fill_price = raw_price * (1 + slippage_dir * config.paper.slippage / 100)
            except Exception as err:  # noqa: BLE001
                return OrderResult(success=False, error=f"Price fetch failed: {err}")

            margin = (params.size * fill_price) / params.leverage
            fee = params.size * fill_price * (config.paper.taker_fee / 100)
            if wallet["balance"] < margin + fee:
                return OrderResult(success=False, error="Insufficient balance")

            lev = params.leverage if params.leverage > 0 else 1
            tp_price = None
            sl_price = None
            if params.tp_percent:
                price_pct = params.tp_percent / lev / 100
                tp_price = fill_price * (1 + price_pct) if params.side == "long" else fill_price * (1 - price_pct)
            if params.sl_percent:
                price_pct = params.sl_percent / lev / 100
                sl_price = fill_price * (1 - price_pct) if params.side == "long" else fill_price * (1 + price_pct)

            bot_config = query_one("SELECT trailing_stop FROM bot_configs WHERE account_id = ?", (account_id,))
            trailing_stop = 1 if (bot_config and bot_config["trailing_stop"]) else 0
            trailing_highest = fill_price if (trailing_stop and params.side == "long") else None
            trailing_lowest = fill_price if (trailing_stop and params.side == "short") else None

            with transaction() as conn:
                conn.execute(
                    "UPDATE paper_wallets SET balance = balance - ?, updated_at = datetime('now') WHERE account_id = ?",
                    (margin + fee, account_id),
                )
                cur = conn.execute(
                    """
                    INSERT INTO trades (account_id, symbol, side, size, entry_price, leverage, fee, status, signal_score, active_rules, entry_reason, trigger_source, trigger_stars, min_score_used)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?)
                    """,
                    (account_id, symbol, params.side, params.size, fill_price, params.leverage, fee,
                     params.signal_score, params.active_rules, params.entry_reason,
                     params.trigger_source, params.trigger_stars, params.min_score_used),
                )
                trade_id = cur.lastrowid
                conn.execute(
                    """
                    INSERT INTO open_positions (
                      account_id, symbol, side, size, entry_price, mark_price, leverage,
                      tp_price, sl_price, trailing_stop, trailing_highest, trailing_lowest
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (account_id, symbol, params.side, params.size, fill_price, fill_price, params.leverage,
                     tp_price, sl_price, trailing_stop, trailing_highest, trailing_lowest),
                )

            log.info(f"Order filled: {params.side} {params.size} {symbol} @ {fill_price}", {"accountId": account_id})
            event_bus.emit("order:filled", {"symbol": symbol, "side": params.side, "size": params.size, "fillPrice": fill_price, "accountId": account_id})
            event_bus.emit("position:opened", {"symbol": symbol, "side": params.side, "size": params.size, "entryPrice": fill_price, "accountId": account_id})
            return OrderResult(success=True, trade_id=trade_id, fill_price=fill_price)

    async def close_position(self, account_id: int, symbol: str, side: str,
                             reason: str | None = None, fill_price_override: float | None = None) -> CloseResult:
        symbol = symbol.upper()
        async with _lock_for(account_id, symbol):
            position = query_one(
                "SELECT * FROM open_positions WHERE account_id = ? AND symbol = ? AND side = ?",
                (account_id, symbol, side),
            )
            if not position:
                return CloseResult(success=False, error="Position not found")

            if fill_price_override and math.isfinite(fill_price_override) and fill_price_override > 0:
                slippage_dir = -1 if side == "long" else 1
                exit_price = fill_price_override * (1 + slippage_dir * config.paper.slippage / 100)
            else:
                try:
                    live_price = await asyncio.wait_for(get_last_price(symbol), timeout=3.0)
                except Exception:  # noqa: BLE001
                    live_price = None
                if isinstance(live_price, (int, float)) and math.isfinite(live_price) and live_price > 0:
                    raw_price = live_price
                elif position["mark_price"] and position["mark_price"] > 0:
                    raw_price = position["mark_price"]
                else:
                    raw_price = position["entry_price"]
                if not math.isfinite(raw_price) or raw_price <= 0:
                    return CloseResult(success=False, error="No usable price for close (live fetch slow, no mark price)")
                slippage_dir = -1 if side == "long" else 1
                exit_price = raw_price * (1 + slippage_dir * config.paper.slippage / 100)

            close_fee = position["size"] * exit_price * (config.paper.taker_fee / 100)
            if side == "long":
                pnl = (exit_price - position["entry_price"]) * position["size"]
            else:
                pnl = (position["entry_price"] - exit_price) * position["size"]

            entry_fee_row = query_one(
                "SELECT fee FROM trades WHERE account_id = ? AND symbol = ? AND side = ? AND status = 'open' ORDER BY opened_at DESC, id DESC LIMIT 1",
                (account_id, symbol, side),
            )
            total_fee = (entry_fee_row["fee"] if entry_fee_row else 0) + close_fee
            wallet_pnl = pnl - close_fee
            net_pnl = pnl - total_fee
            margin = (position["entry_price"] * position["size"]) / position["leverage"]
            pnl_percent = (net_pnl / margin) * 100 if margin > 0 else 0.0

            opened_at = parse_db_time_ms(position["opened_at"])
            duration_seconds = int((now_ms() - opened_at) / 1000) if math.isfinite(opened_at) else None

            with transaction() as conn:
                conn.execute("DELETE FROM open_positions WHERE id = ?", (position["id"],))
                conn.execute(
                    "UPDATE paper_wallets SET balance = balance + ?, total_pnl = total_pnl + ?, total_trades = total_trades + 1, winning_trades = winning_trades + ?, losing_trades = losing_trades + ?, updated_at = datetime('now') WHERE account_id = ?",
                    (margin + wallet_pnl, net_pnl, 1 if net_pnl > 0 else 0, 1 if net_pnl <= 0 else 0, account_id),
                )
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

    async def get_positions(self, account_id: int) -> list[Position]:
        rows = query_all("SELECT * FROM open_positions WHERE account_id = ?", (account_id,))
        return [
            Position(
                id=r["id"], account_id=r["account_id"], symbol=r["symbol"], side=r["side"], size=r["size"],
                entry_price=r["entry_price"], mark_price=r["mark_price"], leverage=r["leverage"],
                unrealized_pnl=r["unrealized_pnl"], tp_price=r["tp_price"], sl_price=r["sl_price"],
            )
            for r in rows
        ]

    async def get_balance(self, account_id: int) -> Balance:
        wallet = query_one("SELECT * FROM paper_wallets WHERE account_id = ?", (account_id,))
        if not wallet:
            return Balance(balance=0, equity=0, unrealized_pnl=0, available_balance=0)
        positions = query_all("SELECT * FROM open_positions WHERE account_id = ?", (account_id,))
        unrealized_pnl = 0.0
        reserved_margin = 0.0
        for pos in positions:
            leverage = pos["leverage"] if pos["leverage"] > 0 else 1
            reserved_margin += (pos["entry_price"] * pos["size"]) / leverage
            if pos["mark_price"]:
                if pos["side"] == "long":
                    unrealized_pnl += (pos["mark_price"] - pos["entry_price"]) * pos["size"]
                else:
                    unrealized_pnl += (pos["entry_price"] - pos["mark_price"]) * pos["size"]
        equity = wallet["balance"] + reserved_margin + unrealized_pnl
        return Balance(balance=wallet["balance"], equity=equity, unrealized_pnl=unrealized_pnl, available_balance=wallet["balance"])

    async def set_leverage(self, account_id: int, symbol: str, leverage: int) -> None:
        pass

    async def set_tp_sl(self, account_id: int, symbol: str, side: str, tp, sl) -> None:
        from ..db.database import execute
        execute(
            "UPDATE open_positions SET tp_price = ?, sl_price = ? WHERE account_id = ? AND symbol = ? AND side = ?",
            (tp, sl, account_id, symbol, side),
        )

    async def update_mark_prices(self, account_id: int) -> None:
        positions = query_all("SELECT * FROM open_positions WHERE account_id = ?", (account_id,))
        from ..db.database import execute
        for pos in positions:
            try:
                price = await get_last_price(pos["symbol"])
                if pos["side"] == "long":
                    unrealized_pnl = (price - pos["entry_price"]) * pos["size"]
                else:
                    unrealized_pnl = (pos["entry_price"] - price) * pos["size"]
                execute("UPDATE open_positions SET mark_price = ?, unrealized_pnl = ? WHERE id = ?", (price, unrealized_pnl, pos["id"]))
                event_bus.emit("position:updated", {
                    "symbol": pos["symbol"], "side": pos["side"], "unrealizedPnl": unrealized_pnl,
                    "markPrice": price, "accountId": account_id, "positionId": pos["id"],
                })
            except Exception as err:  # noqa: BLE001
                log.error(f"Failed to update mark price for {pos['symbol']}: {err}")


paper_engine = PaperEngine()
