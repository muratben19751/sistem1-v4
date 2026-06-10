from .rule_interface import TradingRule, MarketData, RuleResult, side_for


def _evaluate(data: MarketData) -> RuleResult:
    rsi_h1 = data.rsi.get("60", 50)

    score = 0
    detail = ""

    if rsi_h1 < 30:
        score = 1.5
        detail = f"H1 oversold RSI:{rsi_h1:.1f}"
    elif rsi_h1 >= 35 and rsi_h1 < 40:
        score = 1
        detail = f"H1 reversal zone RSI:{rsi_h1:.1f}"
    elif rsi_h1 >= 60 and rsi_h1 <= 65:
        score = 1
        detail = f"H1 uptrend RSI:{rsi_h1:.1f}"
    elif rsi_h1 > 65 and rsi_h1 <= 70:
        score = -1
        detail = f"H1 overbought zone RSI:{rsi_h1:.1f}"
    elif rsi_h1 > 70:
        score = -1.5
        detail = f"H1 overbought RSI:{rsi_h1:.1f}"

    return RuleResult(score=score, side=side_for(score), detail=detail)


rule_02_h1_trend = TradingRule(
    key="rule_02_h1_trend",
    name="H1 RSI Trend",
    sources=["scanner", "sniper"],
    evaluate=_evaluate,
)
