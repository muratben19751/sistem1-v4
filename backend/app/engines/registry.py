from .bybit_engine import bybit_engine, demo_engine
from .bybit_engine import live_engine_for as _live_engine_for
from .paper_engine import paper_engine
from .trade_engine import TradeEngine


def get_engine(name: str | None) -> TradeEngine:
    if name == "bybit":
        return bybit_engine
    if name == "demo":
        return demo_engine
    return paper_engine


def live_engine_for(name: str | None) -> TradeEngine | None:
    return _live_engine_for(name)
