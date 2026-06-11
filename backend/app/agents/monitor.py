import asyncio
import os

from ..core.logger import create_logger
from ..core.event_bus import event_bus
from ..core.time import now_ms
from ..db.database import query_one, query_all, execute
from ..services.bybit_api import get_last_price
from ..services.bybit_ws import on_bybit_ticker_update
from ..engines.registry import live_engine_for
from .execution import close_position, complete_exchange_operation
from .risk import set_cooldown

log = create_logger("monitor")

_monitors: dict[int, dict] = {}
# Hesap basina TEK paylasilan check_positions kilidi: manuel cagri + monitor tik'i
# ayni guard'i gorur (split-brain'i onler -> ayni TP/SL iki kez kapanmaz).
_check_guards: dict[int, dict] = {}
_global_running = {"flag": False}
_global_task: asyncio.Task | None = None
_last_global_skip_warn = {"ts": 0.0}
_stopping_tasks: set[asyncio.Task] = set()


def _coalesce(value, fallback):
    return value if value is not None else fallback


def _cancel_owned_task(task: asyncio.Task | None) -> None:
    if task is None or task.done():
        return
    _stopping_tasks.add(task)
    task.add_done_callback(_stopping_tasks.discard)
    task.cancel()


async def wait_for_monitor_tasks() -> None:
    while True:
        pending = [task for task in _stopping_tasks if not task.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


def _warn_monitor_skip(account_id: int, state: dict) -> None:
    now = now_ms()
    if now - state["lastSkipWarn"] < 60000:
        return
    state["lastSkipWarn"] = now
    log.warn("Position monitor still running; skipped overlapping tick", {"accountId": account_id})


async def check_positions(account_id: int) -> None:
    guard = _check_guards.setdefault(account_id, {"running": False, "lastSkipWarn": 0})
    if guard["running"]:
        _warn_monitor_skip(account_id, guard)
        return
    guard["running"] = True
    try:
        account = await asyncio.to_thread(query_one, "SELECT engine FROM accounts WHERE id = ?", (account_id,))
        live_engine = live_engine_for(account["engine"]) if account else None
        if live_engine:
            await live_engine.update_mark_prices(account_id)
        positions = await asyncio.to_thread(query_all, "SELECT * FROM open_positions WHERE account_id = ?", (account_id,))

        for pos in positions:
            try:
                price = await get_last_price(pos["symbol"])
                if pos["side"] == "long":
                    unrealized_pnl = (price - pos["entry_price"]) * pos["size"]
                else:
                    unrealized_pnl = (pos["entry_price"] - price) * pos["size"]

                prev_high = _coalesce(pos["intra_high"], pos["entry_price"])
                prev_low = _coalesce(pos["intra_low"], pos["entry_price"])
                new_high = max(prev_high, price)
                new_low = min(prev_low, price)

                await asyncio.to_thread(
                    execute,
                    "UPDATE open_positions SET mark_price = ?, unrealized_pnl = ?, intra_high = ?, intra_low = ? WHERE id = ?",
                    (price, unrealized_pnl, new_high, new_low, pos["id"]),
                )
                event_bus.emit("position:updated", {
                    "symbol": pos["symbol"], "side": pos["side"], "unrealizedPnl": unrealized_pnl,
                    "markPrice": price, "accountId": account_id, "positionId": pos["id"],
                })

                if pos["tp_price"]:
                    tp_hit = new_high >= pos["tp_price"] if pos["side"] == "long" else new_low <= pos["tp_price"]
                    if tp_hit:
                        log.info(f"TP hit: {pos['symbol']} target={pos['tp_price']}", {"accountId": account_id})
                        res = await close_position(account_id, pos["symbol"], pos["side"], "tp_hit", pos["tp_price"])
                        if getattr(res, "success", True):
                            set_cooldown(account_id, pos["symbol"])
                        continue

                if pos["sl_price"]:
                    if pos["trailing_stop"]:
                        sl_hit = price <= pos["sl_price"] if pos["side"] == "long" else price >= pos["sl_price"]
                    else:
                        sl_hit = new_low <= pos["sl_price"] if pos["side"] == "long" else new_high >= pos["sl_price"]
                    if sl_hit:
                        log.info(f"SL hit: {pos['symbol']} target={pos['sl_price']}", {"accountId": account_id})
                        res = await close_position(account_id, pos["symbol"], pos["side"], "sl_hit", pos["sl_price"])
                        if getattr(res, "success", True):
                            set_cooldown(account_id, pos["symbol"])
                        continue

                if pos["trailing_stop"]:
                    await _update_trailing_stop(pos, price, account_id, live_engine)
            except Exception as err:  # noqa: BLE001
                log.error(f"Monitor failed for {pos['symbol']}: {err}")
    finally:
        guard["running"] = False


async def _update_trailing_stop(pos, price: float, account_id: int, live_engine=None) -> None:
    bot_config = await asyncio.to_thread(query_one, "SELECT * FROM bot_configs WHERE account_id = ?", (account_id,))
    if not bot_config:
        return
    trailing_pcnt = bot_config["trailing_percent"] / 100
    if pos["side"] == "long":
        highest = max(_coalesce(pos["trailing_highest"], pos["entry_price"]), price)
        new_sl = highest * (1 - trailing_pcnt)
        if new_sl > (pos["sl_price"] or 0):
            if live_engine:
                await complete_exchange_operation(
                    live_engine.set_tp_sl(account_id, pos["symbol"], pos["side"], pos["tp_price"], new_sl)
                )
                await asyncio.to_thread(execute, "UPDATE open_positions SET trailing_highest = ? WHERE id = ?", (highest, pos["id"]))
            else:
                await asyncio.to_thread(execute, "UPDATE open_positions SET trailing_highest = ?, sl_price = ? WHERE id = ?", (highest, new_sl, pos["id"]))
            log.info(f"Trailing SL updated: {pos['symbol']} new SL={new_sl:.4f}", {"accountId": account_id})
    else:
        lowest = min(_coalesce(pos["trailing_lowest"], pos["entry_price"]), price)
        new_sl = lowest * (1 + trailing_pcnt)
        if new_sl < (pos["sl_price"] if pos["sl_price"] else float("inf")):
            if live_engine:
                await complete_exchange_operation(
                    live_engine.set_tp_sl(account_id, pos["symbol"], pos["side"], pos["tp_price"], new_sl)
                )
                await asyncio.to_thread(execute, "UPDATE open_positions SET trailing_lowest = ? WHERE id = ?", (lowest, pos["id"]))
            else:
                await asyncio.to_thread(execute, "UPDATE open_positions SET trailing_lowest = ?, sl_price = ? WHERE id = ?", (lowest, new_sl, pos["id"]))
            log.info(f"Trailing SL updated: {pos['symbol']} new SL={new_sl:.4f}", {"accountId": account_id})


async def _monitor_loop(account_id: int, interval_ms: int) -> None:
    while account_id in _monitors:
        try:
            await check_positions(account_id)
        except Exception as err:  # noqa: BLE001
            log.error(f"Monitor tick failed for account {account_id}: {err}")
        await asyncio.sleep(interval_ms / 1000)


def start_monitor(account_id: int, interval_ms: int = 5000) -> None:
    if account_id in _monitors:
        return
    log.info(f"Monitor started for account {account_id} ({interval_ms}ms)")
    state = {"running": False, "lastSkipWarn": 0, "task": None}
    _monitors[account_id] = state
    state["task"] = asyncio.create_task(_monitor_loop(account_id, interval_ms))


def stop_monitor(account_id: int) -> None:
    state = _monitors.pop(account_id, None)
    if state:
        task = state.get("task")
        _cancel_owned_task(task)
        log.info(f"Monitor stopped for account {account_id}")


def is_monitor_running(account_id: int) -> bool:
    return account_id in _monitors


async def _global_tick() -> None:
    positions = await asyncio.to_thread(query_all, "SELECT * FROM open_positions")
    if not positions:
        return
    account_engines = {r["id"]: r["engine"] for r in await asyncio.to_thread(query_all, "SELECT id, engine FROM accounts")}
    symbol_map: dict[str, list] = {}
    for pos in positions:
        pos_engine = account_engines.get(pos["account_id"])
        if pos_engine in ("bybit", "demo"):
            continue
        symbol_map.setdefault(pos["symbol"], []).append(pos)

    for symbol, pos_list in symbol_map.items():
        try:
            price = await get_last_price(symbol)
            for pos in pos_list:
                if pos["account_id"] in _monitors:
                    continue
                unrealized_pnl = (price - pos["entry_price"]) * pos["size"] if pos["side"] == "long" else (pos["entry_price"] - price) * pos["size"]
                new_high = max(_coalesce(pos["intra_high"], pos["entry_price"]), price)
                new_low = min(_coalesce(pos["intra_low"], pos["entry_price"]), price)
                await asyncio.to_thread(
                    execute,
                    "UPDATE open_positions SET mark_price = ?, unrealized_pnl = ?, intra_high = ?, intra_low = ? WHERE id = ?",
                    (price, unrealized_pnl, new_high, new_low, pos["id"]),
                )
                event_bus.emit("position:updated", {
                    "symbol": pos["symbol"], "side": pos["side"], "unrealizedPnl": unrealized_pnl,
                    "markPrice": price, "accountId": pos["account_id"], "positionId": pos["id"],
                })
                if pos["tp_price"]:
                    tp_hit = new_high >= pos["tp_price"] if pos["side"] == "long" else new_low <= pos["tp_price"]
                    if tp_hit:
                        log.info(f"[global] TP hit: {pos['symbol']} target={pos['tp_price']}", {"accountId": pos["account_id"]})
                        res = await close_position(pos["account_id"], pos["symbol"], pos["side"], "tp_hit", pos["tp_price"])
                        if getattr(res, "success", True):
                            set_cooldown(pos["account_id"], pos["symbol"])
                        continue
                if pos["sl_price"]:
                    if pos["trailing_stop"]:
                        sl_hit = price <= pos["sl_price"] if pos["side"] == "long" else price >= pos["sl_price"]
                    else:
                        sl_hit = new_low <= pos["sl_price"] if pos["side"] == "long" else new_high >= pos["sl_price"]
                    if sl_hit:
                        log.info(f"[global] SL hit: {pos['symbol']} target={pos['sl_price']}", {"accountId": pos["account_id"]})
                        res = await close_position(pos["account_id"], pos["symbol"], pos["side"], "sl_hit", pos["sl_price"])
                        if getattr(res, "success", True):
                            set_cooldown(pos["account_id"], pos["symbol"])
                        continue
                if pos["trailing_stop"]:
                    await _update_trailing_stop(pos, price, pos["account_id"])
        except Exception as err:  # noqa: BLE001
            log.warn(f"[global] price update failed for {symbol}: {err}")


RECONCILE_INTERVAL_MS = max(15000, int(os.environ.get("LIVE_RECONCILE_INTERVAL_MS") or 30000))
_last_reconcile = {"ts": 0.0}


async def reconcile_live_positions() -> None:
    """Use each live engine's guarded reconciliation even when its bot is stopped."""
    accounts = query_all("SELECT id, engine FROM accounts WHERE engine IN ('bybit', 'demo')")
    for acc in accounts:
        engine = live_engine_for(acc["engine"])
        if engine is None:
            continue
        try:
            await engine.update_mark_prices(acc["id"])
        except Exception as err:  # noqa: BLE001
            log.warn(f"[reconcile] account {acc['id']} update failed: {err}")


async def _global_loop(interval_ms: int) -> None:
    while _global_running["flag"]:
        if _global_running.get("ticking"):
            now = now_ms()
            if now - _last_global_skip_warn["ts"] > 60000:
                _last_global_skip_warn["ts"] = now
                log.warn("[global] previous price updater tick still running; skipped overlapping tick")
        else:
            _global_running["ticking"] = True
            try:
                await _global_tick()
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                log.error(f"[global] price updater tick failed; next tick will retry: {err}")
            finally:
                _global_running["ticking"] = False
        now = now_ms()
        if now - _last_reconcile["ts"] > RECONCILE_INTERVAL_MS:
            _last_reconcile["ts"] = now
            try:
                await reconcile_live_positions()
            except Exception as err:  # noqa: BLE001
                log.warn(f"[reconcile] failed: {err}")
        await asyncio.sleep(interval_ms / 1000)


def start_global_price_updater(interval_ms: int = 5000) -> None:
    global _global_task
    if _global_task is not None and not _global_task.done():
        return
    _global_task = None
    _global_running["flag"] = True
    _global_task = asyncio.create_task(_global_loop(interval_ms))
    log.info(f"Global price updater started ({interval_ms}ms)")


def stop_global_price_updater() -> None:
    global _global_task
    if _global_task is None:
        return
    _global_running["flag"] = False
    _cancel_owned_task(_global_task)
    _global_task = None
    log.info("Global price updater stopped")


def start_realtime_position_stream() -> None:
    # WS tabanli; stub on_bybit_ticker_update no-op oldugundan pasif (sonraki faz).
    on_bybit_ticker_update(lambda symbol, price: None)
    log.info("Realtime position price stream started (WS deferred)")


async def take_equity_snapshot(account_id: int) -> None:
    wallet = await asyncio.to_thread(query_one, "SELECT * FROM paper_wallets WHERE account_id = ?", (account_id,))
    positions = await asyncio.to_thread(query_all, "SELECT * FROM open_positions WHERE account_id = ?", (account_id,))
    unrealized_pnl = 0.0
    reserved_margin = 0.0
    for pos in positions:
        leverage = pos["leverage"] if pos["leverage"] > 0 else 1
        reserved_margin += (pos["entry_price"] * pos["size"]) / leverage
        unrealized_pnl += pos["unrealized_pnl"] or 0

    if wallet:
        balance = wallet["balance"]
        equity = balance + reserved_margin + unrealized_pnl
        initial_balance = wallet["initial_balance"]
    else:
        # Canli (bybit/demo) hesap: paper_wallet yok -> borsadan equity cek ki
        # drawdown devre kesici (risk.py) icin peak/equity gercekten kayda gecsin.
        account = await asyncio.to_thread(query_one, "SELECT engine, initial_balance FROM accounts WHERE id = ?", (account_id,))
        live_engine = live_engine_for(account["engine"]) if account else None
        if not live_engine:
            return
        try:
            bal = await live_engine.get_balance(account_id)
        except Exception as err:  # noqa: BLE001
            log.warn(f"[equity] live balance fetch failed for account {account_id}: {err}")
            return
        equity = bal.equity if bal.equity is not None else bal.balance
        balance = bal.balance
        if equity is None:
            return
        initial_balance = account["initial_balance"] or 0

    peak_row = await asyncio.to_thread(query_one, "SELECT MAX(equity) as peak FROM equity_snapshots WHERE account_id = ?", (account_id,))
    peak = max(initial_balance, (peak_row["peak"] if peak_row and peak_row["peak"] else 0), equity)
    drawdown = ((peak - equity) / peak) * 100 if peak > 0 else 0
    await asyncio.to_thread(
        execute,
        "INSERT INTO equity_snapshots (account_id, equity, balance, unrealized_pnl, drawdown) VALUES (?, ?, ?, ?, ?)",
        (account_id, equity, balance, unrealized_pnl, max(0, drawdown)),
    )
