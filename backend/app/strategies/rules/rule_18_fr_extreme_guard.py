from .rule_interface import TradingRule, MarketData, RuleResult, side_for


def _evaluate(data: MarketData) -> RuleResult:
    fr = data.funding_rate
    fr_pct = fr * 100
    prior_results = data.prior_results or []
    total_prior_score = sum(r.score for r in prior_results)

    score = 0
    details: list[str] = []

    if fr_pct < -1.5:
        score = -3
        details.append(f"FR {fr_pct:.3f}% delisting riski [-3]")
    elif fr_pct < -0.75:
        score = -2
        details.append(f"FR {fr_pct:.3f}% extreme neg [-2]")
    elif fr_pct < -0.25:
        score = -0.5
        details.append(f"FR {fr_pct:.3f}% yuksek neg [-0.5]")
    elif fr_pct >= -0.05 and fr_pct < -0.005:
        score = 2
        details.append(f"FR {fr_pct:.3f}% kaliteli long [+2]")
    elif fr_pct >= -0.005 and fr_pct <= 0.005:
        score = 1
        details.append(f"FR {fr_pct:.3f}% stabil [+1]")
    elif fr_pct > 0.1:
        score = -2
        details.append(f"FR {fr_pct:.3f}% extreme poz, short [-2]")
    elif fr_pct > 0.05:
        score = -1
        details.append(f"FR {fr_pct:.3f}% yuksek poz [-1]")

    if total_prior_score >= 3 and score > 0:
        score += 1.5
        details.append(f"{total_prior_score:.1f}p uyum confluence [+1.5]")
    elif total_prior_score <= -3 and score < 0:
        score -= 1
        details.append(f"{total_prior_score:.1f}p uyum short confluence [-1]")

    if data.trigger_alert:
        alert_dir = data.trigger_alert.get("direction")
        if alert_dir == "UP" and fr_pct < -0.75:
            score -= 1
            details.append("UP sinyal + extreme neg FR tuzak [-1]")
        elif alert_dir == "DOWN" and fr_pct > 0.05:
            score -= 1
            details.append("DOWN sinyal + yuksek poz FR tuzak [-1]")

    return RuleResult(
        score=score,
        side=side_for(score),
        detail=" | ".join(details) or f"FR {fr_pct:.3f}% notr [0]",
    )


rule_18_fr_extreme_guard = TradingRule(
    key="rule_18_fr_extreme_guard",
    name="FR Extreme Guard",
    evaluate=_evaluate,
)
