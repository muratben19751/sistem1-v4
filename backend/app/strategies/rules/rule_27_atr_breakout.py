import math

from .rule_interface import TradingRule, MarketData, RuleResult
from ...lib.indicators import calc_atr


def _to_precision(value: float, precision: int) -> str:
    if value == 0:
        return "0" if precision == 1 else "0." + "0" * (precision - 1)
    neg = value < 0
    av = abs(value)
    e = math.floor(math.log10(av))
    factor = 10 ** (precision - 1 - e)
    # JS Number.toPrecision paritesi: half-away-from-zero (av pozitif -> half-up)
    rounded = math.floor(av * factor + 0.5) / factor
    if rounded != 0:
        e = math.floor(math.log10(rounded))
    if e < -6 or e >= precision:
        mant = rounded / (10 ** e)
        s = f"{mant:.{precision - 1}f}"
        sign = "+" if e >= 0 else "-"
        out = f"{s}e{sign}{abs(e)}"
    else:
        decimals = precision - 1 - e
        out = f"{rounded:.{decimals}f}"
    return ("-" if neg else "") + out


def _evaluate(data: MarketData) -> RuleResult:
    klines = data.klines.get("15")
    lookback = 20
    if not klines or len(klines) < lookback + 16:
        return RuleResult(score=0, side="neutral", detail="Not enough 15m data")
    atr = calc_atr(klines, 14)
    if not atr or atr <= 0:
        return RuleResult(score=0, side="neutral", detail="ATR yok")

    last = klines[-1]
    window = klines[-(lookback + 1):-1]
    prior_high = max(k.high for k in window)
    prior_low = min(k.low for k in window)
    tag = f"ATR={_to_precision(atr, 3)}"

    if last.close > prior_high + atr:
        return RuleResult(score=2, side="long", detail=f"Guclu yukari kirilim >1ATR ({tag})")
    if last.close > prior_high:
        return RuleResult(score=1, side="long", detail=f"Yukari kirilim ({tag})")
    if last.close < prior_low - atr:
        return RuleResult(score=-2, side="short", detail=f"Guclu asagi kirilim >1ATR ({tag})")
    if last.close < prior_low:
        return RuleResult(score=-1, side="short", detail=f"Asagi kirilim ({tag})")
    return RuleResult(score=0, side="neutral", detail=f"Kanal icinde ({tag})")


rule_27_atr_breakout = TradingRule(
    key="rule_27_atr_breakout",
    name="ATR Volatility Breakout (15m)",
    sources=["scanner", "sniper", "hammer"],
    evaluate=_evaluate,
)
