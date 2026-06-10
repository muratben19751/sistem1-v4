from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class OrderParams:
    account_id: int
    symbol: str
    side: str  # 'long' | 'short'
    size: float
    leverage: int
    tp_percent: Optional[float] = None
    sl_percent: Optional[float] = None
    signal_score: Optional[float] = None
    active_rules: Optional[str] = None
    entry_reason: Optional[str] = None
    trigger_source: Optional[str] = None
    trigger_stars: Optional[int] = None
    min_score_used: Optional[float] = None


@dataclass
class OrderResult:
    success: bool
    trade_id: Optional[int] = None
    fill_price: Optional[float] = None
    error: Optional[str] = None


@dataclass
class CloseResult:
    success: bool
    pnl: Optional[float] = None
    pnl_percent: Optional[float] = None
    exit_price: Optional[float] = None
    error: Optional[str] = None


@dataclass
class Position:
    id: int
    account_id: int
    symbol: str
    side: str
    size: float
    entry_price: float
    mark_price: Optional[float]
    leverage: int
    unrealized_pnl: float
    tp_price: Optional[float]
    sl_price: Optional[float]


@dataclass
class Balance:
    balance: float
    equity: float
    unrealized_pnl: float
    available_balance: float


class TradeEngine(ABC):
    name: str = "base"

    @abstractmethod
    async def place_order(self, params: OrderParams) -> OrderResult: ...

    @abstractmethod
    async def close_position(self, account_id: int, symbol: str, side: str,
                             reason: str | None = None, fill_price_override: float | None = None) -> CloseResult: ...

    @abstractmethod
    async def get_positions(self, account_id: int) -> list[Position]: ...

    @abstractmethod
    async def get_balance(self, account_id: int) -> Balance: ...

    @abstractmethod
    async def set_leverage(self, account_id: int, symbol: str, leverage: int) -> None: ...

    @abstractmethod
    async def set_tp_sl(self, account_id: int, symbol: str, side: str,
                        tp: float | None, sl: float | None) -> None: ...

    @abstractmethod
    async def update_mark_prices(self, account_id: int) -> None: ...
