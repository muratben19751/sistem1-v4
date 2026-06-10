from .rule_interface import TradingRule, MarketData, RuleResult, side_for


def _evaluate(data: MarketData) -> RuleResult:
    rsi5m = data.rsi.get("5", 50)
    rsi_h1 = data.rsi.get("60", 50)

    score = 0
    detail = ""

    if rsi5m > 70 and rsi_h1 < 40:
        score = -1.5
        detail = f"Bearish divergence 5m RSI:{rsi5m:.1f} vs H1 RSI:{rsi_h1:.1f}"
    elif rsi5m < 30 and rsi_h1 > 60:
        score = 1.5
        detail = f"Bullish divergence 5m RSI:{rsi5m:.1f} vs H1 RSI:{rsi_h1:.1f}"
    elif rsi5m > 65 and rsi_h1 < 45:
        score = -1
        detail = f"Mild bearish divergence 5m RSI:{rsi5m:.1f} vs H1 RSI:{rsi_h1:.1f}"
    elif rsi5m < 35 and rsi_h1 > 55:
        score = 1
        detail = f"Mild bullish divergence 5m RSI:{rsi5m:.1f} vs H1 RSI:{rsi_h1:.1f}"

    return RuleResult(score=score, side=side_for(score), detail=detail)


rule_06_tf_divergence = TradingRule(
    key="rule_06_tf_divergence",
    name="Timeframe Divergence",
    sources=["sniper", "hammer"],
    evaluate=_evaluate,
)
