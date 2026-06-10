import math

from .rule_interface import TradingRule, MarketData, RuleResult
from ...lib.indicators import calc_rsi_series, sma

SMA_PERIOD = 200
RSI_PERIOD = 2
OVERSOLD = 20
OVERBOUGHT = 70
FALL_DAYS = 3


def _evaluate(data: MarketData) -> RuleResult:
    klines = data.klines.get("D")
    if not klines or len(klines) < SMA_PERIOD:
        return RuleResult(score=0, side="neutral", detail=f"Daily klines yetersiz ({len(klines) if klines else 0}/{SMA_PERIOD})")

    closes = [k.close for k in klines]
    last_close = closes[-1]

    sma_series = sma(closes, SMA_PERIOD)
    sma200 = sma_series[-1] if sma_series else float("nan")
    if not math.isfinite(sma200):
        return RuleResult(score=0, side="neutral", detail="SMA200 hesaplanamadi")

    rsi_series = calc_rsi_series(closes, RSI_PERIOD)
    if len(rsi_series) < FALL_DAYS + 1:
        return RuleResult(score=0, side="neutral", detail="RSI(2) serisi yetersiz")

    r = rsi_series[-FALL_DAYS - 1:]
    rsi_now = r[-1]

    above_sma = last_close > sma200
    oversold = rsi_now < OVERSOLD
    falling = True
    for i in range(1, len(r)):
        if r[i] >= r[i - 1]:
            falling = False
            break

    if above_sma and oversold and falling:
        return RuleResult(
            score=3,
            side="long",
            detail=f"RSI Drop: close>{SMA_PERIOD}MA, RSI(2)={rsi_now:.1f}<{OVERSOLD}, {FALL_DAYS} gun dustu → mean-rev LONG [+3]",
        )

    if rsi_now > OVERBOUGHT:
        return RuleResult(
            score=-1,
            side="short",
            detail=f"RSI(2)={rsi_now:.1f}>{OVERBOUGHT}: asiri alim, mean-rev cikis bolgesi [-1]",
        )

    reasons = []
    if not above_sma:
        reasons.append(f"close<{SMA_PERIOD}MA")
    if not oversold:
        reasons.append(f"RSI(2)={rsi_now:.1f}>={OVERSOLD}")
    if not falling:
        reasons.append(f"{FALL_DAYS} gun ust uste dusus yok")
    return RuleResult(score=0, side="neutral", detail=f"Kosul saglanmadi: {', '.join(reasons)}")


rule_22_rsi_drop_daily = TradingRule(
    key="rule_22_rsi_drop_daily",
    name="RSI Drop Strategy (Daily MR)",
    evaluate=_evaluate,
)
