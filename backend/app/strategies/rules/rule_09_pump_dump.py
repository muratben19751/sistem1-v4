from .rule_interface import TradingRule, MarketData, RuleResult, side_for


def _evaluate(data: MarketData) -> RuleResult:
    # .get(...) or 0: v3'te eksik alan NaN -> tum karsilastirmalar false (notr). Python'da
    # dogrudan erisim KeyError firlatip kurali sessizce atlatirdi.
    price_pcnt = float(data.ticker.get("price24hPcnt") or 0) * 100
    rsi5m = data.rsi.get("5", 50)

    score = 0
    detail = ""

    if price_pcnt > 15 and rsi5m > 80:
        score = -3
        detail = f"Pump detected +{price_pcnt:.1f}% RSI:{rsi5m:.1f}"
    elif price_pcnt > 15 and rsi5m > 70:
        score = -2
        detail = f"Strong pump +{price_pcnt:.1f}% RSI:{rsi5m:.1f}"
    elif price_pcnt < -15 and rsi5m < 20:
        score = 3
        detail = f"Dump detected {price_pcnt:.1f}% RSI:{rsi5m:.1f}"
    elif price_pcnt < -15 and rsi5m < 30:
        score = 2
        detail = f"Strong dump {price_pcnt:.1f}% RSI:{rsi5m:.1f}"

    return RuleResult(score=score, side=side_for(score), detail=detail)


rule_09_pump_dump = TradingRule(
    key="rule_09_pump_dump",
    name="Pump/Dump Detection",
    sources=["scanner"],
    evaluate=_evaluate,
)
