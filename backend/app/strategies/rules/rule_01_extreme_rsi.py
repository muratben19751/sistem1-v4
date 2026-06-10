from .rule_interface import TradingRule, MarketData, RuleResult, side_for


def _evaluate(data: MarketData) -> RuleResult:
    rsi1m = data.rsi.get("1", 50)
    rsi5m = data.rsi.get("5", 50)
    srsi1m = (data.stoch_rsi.get("1") or {}).get("k", 50)
    srsi5m = (data.stoch_rsi.get("5") or {}).get("k", 50)

    score = 0
    detail = ""

    if rsi1m > 80 and srsi1m > 80 and rsi5m > 70 and srsi5m > 70:
        score = -3
        detail = f"Extreme overbought 1m RSI:{rsi1m:.1f} SRSI:{srsi1m:.1f} 5m RSI:{rsi5m:.1f}"
    elif rsi1m > 80 and srsi1m > 80:
        score = -2
        detail = f"Overbought 1m RSI:{rsi1m:.1f} SRSI:{srsi1m:.1f}"
    elif rsi1m < 20 and srsi1m < 20 and rsi5m < 30 and srsi5m < 30:
        score = 3
        detail = f"Extreme oversold 1m RSI:{rsi1m:.1f} SRSI:{srsi1m:.1f} 5m RSI:{rsi5m:.1f}"
    elif rsi1m < 20 and srsi1m < 20:
        score = 2
        detail = f"Oversold 1m RSI:{rsi1m:.1f} SRSI:{srsi1m:.1f}"

    return RuleResult(score=score, side=side_for(score), detail=detail)


rule_01_extreme_rsi = TradingRule(
    key="rule_01_extreme_rsi",
    name="1m/5m Extreme RSI+StochRSI",
    sources=["sniper", "hammer"],
    evaluate=_evaluate,
)
