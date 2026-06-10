from .rule_interface import TradingRule, MarketData, RuleResult, side_for


def _evaluate(data: MarketData) -> RuleResult:
    rsi5m = data.rsi.get("5", 50)

    score = 0
    detail = ""

    if rsi5m < 25:
        score = 2
        detail = f"5m strong oversold RSI:{rsi5m:.1f}"
    elif rsi5m >= 25 and rsi5m < 40:
        score = 1
        detail = f"5m oversold bounce RSI:{rsi5m:.1f}"
    elif rsi5m >= 60 and rsi5m < 75:
        score = 1
        detail = f"5m bullish RSI:{rsi5m:.1f}"
    elif rsi5m > 85:
        score = -1
        detail = f"5m extreme overbought RSI:{rsi5m:.1f}"

    return RuleResult(score=score, side=side_for(score), detail=detail)


rule_03_5m_rsi = TradingRule(
    key="rule_03_5m_rsi",
    name="5m RSI Confirmation",
    sources=["sniper"],
    evaluate=_evaluate,
)
