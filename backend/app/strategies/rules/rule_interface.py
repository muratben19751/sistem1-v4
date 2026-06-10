from dataclasses import dataclass, field
from typing import Callable, Optional

from ...lib.indicators import Kline


@dataclass
class RuleResult:
    score: float
    side: str  # 'long' | 'short' | 'neutral'
    detail: str


@dataclass
class MarketData:
    symbol: str
    klines: dict[str, list[Kline]] = field(default_factory=dict)
    ticker: dict = field(default_factory=dict)
    funding_rate: float = 0.0
    open_interest: float = 0.0
    open_interest_change: float = 0.0
    rsi: dict[str, float] = field(default_factory=dict)
    stoch_rsi: dict[str, dict] = field(default_factory=dict)
    volume_change: float = 0.0
    funding_rate_history: Optional[list[dict]] = None
    funding_interval_hours: Optional[float] = None
    prior_results: Optional[list[RuleResult]] = None
    trigger_source: Optional[str] = None
    trigger_alert: Optional[dict] = None
    # Sinyalin degerlendirilme zamani (ms). Backtest bunu sinyal anina ayarlar; canlida None
    # -> rules zaman bazli (16/17/25) kurallar simdiki saati kullanir. Look-ahead korumali.
    eval_ms: Optional[int] = None


@dataclass
class TradingRule:
    key: str
    name: str
    evaluate: Callable[[MarketData], RuleResult]
    sources: Optional[list[str]] = None
    recommended_tp: Optional[float] = None
    recommended_sl: Optional[float] = None


def side_for(score: float) -> str:
    return "long" if score > 0 else "short" if score < 0 else "neutral"
