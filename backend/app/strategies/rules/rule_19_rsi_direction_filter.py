from .rule_interface import TradingRule, MarketData, RuleResult, side_for


def _evaluate(data: MarketData) -> RuleResult:
    alert = data.trigger_alert
    if not alert:
        return RuleResult(score=0, side="neutral", detail="no alert")

    rsi_h1 = data.rsi.get("60", 0)
    dir = alert.get("direction")

    if rsi_h1 <= 0:
        return RuleResult(score=0, side="neutral", detail="RSI H1 yok")

    score = 0
    detail = ""

    if dir == "DOWN" and rsi_h1 > 80:
        score = 3
        detail = f"RSI H1 {rsi_h1:.1f} + DOWN: guclu reversal [+3]"
    elif dir == "DOWN" and rsi_h1 > 70:
        score = 2
        detail = f"RSI H1 {rsi_h1:.1f} + DOWN: reversal [+2]"
    elif dir == "UP" and rsi_h1 < 20:
        score = -2
        detail = f"RSI H1 {rsi_h1:.1f} + UP: contrarian tuzak [-2]"
    elif dir == "UP" and rsi_h1 < 30:
        score = -1.5
        detail = f"RSI H1 {rsi_h1:.1f} + UP: zayif contrarian [-1.5]"
    else:
        detail = f"RSI H1 {rsi_h1:.1f} + {dir}: notr [0]"

    return RuleResult(score=score, side=side_for(score), detail=detail)


rule_19_rsi_direction_filter = TradingRule(
    key="rule_19_rsi_direction_filter",
    name="RSI Direction Filter (Data-Driven)",
    sources=["hammer", "sniper"],
    evaluate=_evaluate,
)
