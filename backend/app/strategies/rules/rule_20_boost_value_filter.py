from .rule_interface import TradingRule, MarketData, RuleResult


def _evaluate(data: MarketData) -> RuleResult:
    alert = data.trigger_alert
    if not alert:
        return RuleResult(score=0, side="neutral", detail="no alert")

    boost = alert.get("boostValue") or 0
    if boost <= 0:
        return RuleResult(score=0, side="neutral", detail="boost yok")

    score = 0
    detail = ""

    if boost > 30:
        score = 2
        detail = f"Boost {boost:.1f}% extreme [+2]"
    elif boost > 20:
        score = 1.5
        detail = f"Boost {boost:.1f}% yuksek [+1.5]"
    elif boost >= 10:
        score = 1
        detail = f"Boost {boost:.1f}% iyi [+1]"
    elif boost < 2:
        score = -1.5
        detail = f"Boost {boost:.1f}% cok dusuk [-1.5]"
    elif boost < 5:
        score = -1
        detail = f"Boost {boost:.1f}% dusuk [-1]"
    else:
        detail = f"Boost {boost:.1f}% notr [0]"

    side = "long" if alert.get("direction") == "UP" else "short"
    return RuleResult(score=score, side=side if score != 0 else "neutral", detail=detail)


rule_20_boost_value_filter = TradingRule(
    key="rule_20_boost_value_filter",
    name="Boost Value Filter (Data-Driven)",
    sources=["hammer", "sniper"],
    evaluate=_evaluate,
)
