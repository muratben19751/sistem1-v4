from .rule_interface import TradingRule, MarketData, RuleResult
from ...lib.indicators import ema


def _detect_cross(ema_fast: list[float], ema_slow: list[float]):
    n = min(len(ema_fast), len(ema_slow))
    if n < 2:
        return {"lastCross": None, "barsAgo": -1, "aligned": "flat"}
    last_cross = None
    bars_ago = -1
    for i in range(n - 1, 0, -1):
        prev_diff = ema_fast[i - 1] - ema_slow[i - 1]
        cur_diff = ema_fast[i] - ema_slow[i]
        if prev_diff <= 0 and cur_diff > 0:
            last_cross = "golden"
            bars_ago = n - 1 - i
            break
        if prev_diff >= 0 and cur_diff < 0:
            last_cross = "death"
            bars_ago = n - 1 - i
            break
    last = ema_fast[n - 1] - ema_slow[n - 1]
    aligned = "up" if last > 0 else "down" if last < 0 else "flat"
    return {"lastCross": last_cross, "barsAgo": bars_ago, "aligned": aligned}


def _evaluate(data: MarketData) -> RuleResult:
    klines = data.klines.get("15")
    if not klines or len(klines) < 12:
        return RuleResult(score=0, side="neutral", detail="Not enough 15m data")
    closes = [k.close for k in klines]
    fast = ema(closes, 5)
    slow = ema(closes, 9)
    fast_trimmed = fast[len(fast) - len(slow):]
    res = _detect_cross(fast_trimmed, slow)
    last_cross = res["lastCross"]
    bars_ago = res["barsAgo"]
    aligned = res["aligned"]

    if last_cross == "golden" and bars_ago == 0:
        return RuleResult(score=2, side="long", detail="EMA5 crossed above EMA9 on current 15m candle")
    if last_cross == "death" and bars_ago == 0:
        return RuleResult(score=-2, side="short", detail="EMA5 crossed below EMA9 on current 15m candle")
    if last_cross == "golden" and bars_ago > 0 and bars_ago <= 3:
        return RuleResult(score=1, side="long", detail=f"EMA5/9 golden cross {bars_ago} bars ago (15m)")
    if last_cross == "death" and bars_ago > 0 and bars_ago <= 3:
        return RuleResult(score=-1, side="short", detail=f"EMA5/9 death cross {bars_ago} bars ago (15m)")
    if aligned == "up":
        return RuleResult(score=0.5, side="long", detail="EMA5 above EMA9 (15m uptrend)")
    if aligned == "down":
        return RuleResult(score=-0.5, side="short", detail="EMA5 below EMA9 (15m downtrend)")
    return RuleResult(score=0, side="neutral", detail="EMA5/9 flat (15m)")


rule_24_ema_cross_15m = TradingRule(
    key="rule_24_ema_cross_15m",
    name="EMA 5/9 Crossover (15m, TP2/SL1)",
    sources=["scanner", "sniper"],
    recommended_tp=2,
    recommended_sl=1,
    evaluate=_evaluate,
)
