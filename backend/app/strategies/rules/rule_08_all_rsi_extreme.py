from .rule_interface import TradingRule, MarketData, RuleResult, side_for


def _evaluate(data: MarketData) -> RuleResult:
    timeframes = ["1", "5", "15", "60"]
    overbought = 0
    oversold = 0
    total = 0

    for tf in timeframes:
        rsi = data.rsi.get(tf)
        if rsi is None:
            continue
        total += 1
        if rsi > 70:
            overbought += 1
        if rsi < 30:
            oversold += 1

    score = 0
    detail = ""

    if overbought >= 3 and total >= 3:
        score = -2
        detail = f"All RSI overbought ({overbought}/{total} TFs >70)"
    elif oversold >= 3 and total >= 3:
        score = 2
        detail = f"All RSI oversold ({oversold}/{total} TFs <30)"
    elif overbought >= 2:
        score = -1
        detail = f"Multiple RSI overbought ({overbought}/{total})"
    elif oversold >= 2:
        score = 1
        detail = f"Multiple RSI oversold ({oversold}/{total})"

    return RuleResult(score=score, side=side_for(score), detail=detail)


rule_08_all_rsi_extreme = TradingRule(
    key="rule_08_all_rsi_extreme",
    name="All RSI Extreme",
    sources=["sniper"],
    evaluate=_evaluate,
)
