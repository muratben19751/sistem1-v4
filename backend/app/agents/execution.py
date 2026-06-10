import asyncio

from ..core.logger import create_logger
from ..core.event_bus import event_bus
from ..engines.paper_engine import paper_engine
from ..engines.trade_engine import TradeEngine, OrderParams

log = create_logger("execution")

_engines: dict[int, TradeEngine] = {}
_inflight_exchange_tasks: set[asyncio.Task] = set()


def set_engine(account_id: int, engine: TradeEngine) -> None:
    _engines[account_id] = engine
    log.info(f"Engine set to: {engine.name} for account {account_id}")


def get_engine(account_id: int) -> TradeEngine:
    return _engines.get(account_id, paper_engine)


async def complete_exchange_operation(operation):
    """Keep a submitted exchange operation alive across caller cancellation."""
    task = asyncio.create_task(operation)
    _inflight_exchange_tasks.add(task)

    def cleanup(done: asyncio.Task) -> None:
        _inflight_exchange_tasks.discard(done)
        if not done.cancelled():
            done.exception()

    task.add_done_callback(cleanup)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        if task.cancelled():
            raise
        await asyncio.gather(asyncio.shield(task), return_exceptions=True)
        raise


async def wait_for_inflight_exchange_operations() -> None:
    while True:
        pending = [task for task in _inflight_exchange_tasks if not task.done()]
        if not pending:
            return
        log.warn(f"Waiting for {len(pending)} in-flight exchange operation(s) before shutdown")
        await asyncio.gather(*(asyncio.shield(task) for task in pending), return_exceptions=True)


async def execute_order(params: dict):
    account_id = params["accountId"]
    symbol = params["symbol"]
    side = params["side"]
    size = params["size"]
    leverage = params["leverage"]
    engine = get_engine(account_id)

    log.info(f"Executing: {side} {size:.6f} {symbol} lev={leverage}", {"accountId": account_id})

    result = await complete_exchange_operation(
        engine.place_order(OrderParams(
            account_id=account_id,
            symbol=symbol,
            side=side,
            size=size,
            leverage=leverage,
            tp_percent=params.get("tpPercent"),
            sl_percent=params.get("slPercent"),
            signal_score=params.get("signalScore"),
            active_rules=params.get("activeRules"),
            entry_reason=params.get("entryReason") or "bot_signal",
            trigger_source=params.get("triggerSource"),
            trigger_stars=params.get("triggerStars"),
            min_score_used=params.get("minScoreUsed"),
        ))
    )

    if result.success:
        log.info(f"Order filled: {symbol} @ {result.fill_price}", {"accountId": account_id, "tradeId": result.trade_id})
        event_bus.emit("order:placed", {
            "symbol": symbol, "side": side, "size": size, "price": result.fill_price,
            "tradeId": result.trade_id, "accountId": account_id,
        })
    else:
        log.error(f"Order failed: {symbol} - {result.error}", {"accountId": account_id})

    return result


async def close_position(account_id: int, symbol: str, side: str, reason: str, fill_price_override: float | None = None):
    engine = get_engine(account_id)
    extra = f" overrideFill={fill_price_override}" if fill_price_override else ""
    log.info(f"Closing: {side} {symbol} reason={reason}{extra}", {"accountId": account_id})
    return await complete_exchange_operation(
        engine.close_position(account_id, symbol, side, reason, fill_price_override)
    )
