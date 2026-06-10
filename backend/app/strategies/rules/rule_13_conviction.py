from .rule_interface import TradingRule, MarketData, RuleResult, side_for


def _evaluate(data: MarketData) -> RuleResult:
    results = data.prior_results or []
    long_count = 0
    short_count = 0

    for r in results:
        if r.score > 0:
            long_count += 1
        elif r.score < 0:
            short_count += 1

    score = 0
    detail = ""

    if long_count >= 6:
        score = 2
        detail = f"Strong conviction: {long_count} rules agree long"
    elif long_count >= 4:
        score = 1
        detail = f"Conviction bonus: {long_count} rules agree long"
    elif short_count >= 6:
        score = -2
        detail = f"Strong conviction: {short_count} rules agree short"
    elif short_count >= 4:
        score = -1
        detail = f"Conviction bonus: {short_count} rules agree short"

    return RuleResult(score=score, side=side_for(score), detail=detail)


rule_13_conviction = TradingRule(
    key="rule_13_conviction",
    name="Conviction Bonus",
    evaluate=_evaluate,
)
