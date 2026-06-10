from .rule_interface import TradingRule, MarketData, RuleResult, side_for


def _evaluate(data: MarketData) -> RuleResult:
    timeframes = ["5", "15", "60", "240"]
    bullish = 0
    bearish = 0

    for tf in timeframes:
        rsi = data.rsi.get(tf)
        if rsi is None:
            continue
        if rsi > 55:
            bullish += 1
        elif rsi < 45:
            bearish += 1

    score = 0
    detail = ""

    if bullish >= 4:
        score = 2
        detail = f"All TFs bullish aligned ({bullish}/4)"
    elif bullish >= 3:
        score = 1
        detail = f"Strong bullish alignment ({bullish}/4)"
    elif bearish >= 4:
        score = -2
        detail = f"All TFs bearish aligned ({bearish}/4)"
    elif bearish >= 3:
        score = -1
        detail = f"Strong bearish alignment ({bearish}/4)"

    return RuleResult(score=score, side=side_for(score), detail=detail)


rule_07_multi_tf = TradingRule(
    key="rule_07_multi_tf",
    name="Multi-TF Alignment",
    sources=["scanner", "sniper", "hammer"],
    evaluate=_evaluate,
)
