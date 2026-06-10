from .rule_interface import TradingRule, MarketData, RuleResult, side_for


def _evaluate(data: MarketData) -> RuleResult:
    srsi5m = (data.stoch_rsi.get("5") or {}).get("k", 50)
    srsi15m = (data.stoch_rsi.get("15") or {}).get("k", 50)

    score = 0
    detail = ""

    if srsi5m > 90 and srsi15m > 80:
        score = -2
        detail = f"StochRSI extreme overbought 5m:{srsi5m:.1f} 15m:{srsi15m:.1f}"
    elif srsi5m < 10 and srsi15m < 20:
        score = 2
        detail = f"StochRSI extreme oversold 5m:{srsi5m:.1f} 15m:{srsi15m:.1f}"
    elif srsi5m < 20:
        score = 1
        detail = f"StochRSI oversold 5m:{srsi5m:.1f}"

    return RuleResult(score=score, side=side_for(score), detail=detail)


rule_04_stochrsi_extreme = TradingRule(
    key="rule_04_stochrsi_extreme",
    name="StochRSI Extreme",
    sources=["sniper", "hammer"],
    evaluate=_evaluate,
)
