from datetime import datetime, timezone

from .rule_interface import TradingRule, MarketData, RuleResult


def _evaluate(data: MarketData) -> RuleResult:
    # Backtest: sinyal ani; canli: simdi (eval_ms None)
    if data.eval_ms is not None:
        now = datetime.fromtimestamp(data.eval_ms / 1000, tz=timezone.utc)
    else:
        now = datetime.now(timezone.utc)
    utc_day = (now.weekday() + 1) % 7
    utc_hour = now.hour

    is_weekend = utc_day == 0 or utc_day == 6
    is_friday_late = utc_day == 5 and utc_hour >= 18

    if not is_weekend and not is_friday_late:
        return RuleResult(score=0, side="neutral", detail="Hafta ici - cezasiz [0]")

    magnitude = 1 if is_weekend else 0.5
    label = "Hafta sonu" if is_weekend else "Cuma aksami"

    signal_side = "neutral"
    if data.trigger_alert and data.trigger_alert.get("direction") == "UP":
        signal_side = "long"
    elif data.trigger_alert and data.trigger_alert.get("direction") == "DOWN":
        signal_side = "short"
    else:
        prior_sum = sum(r.score for r in (data.prior_results or []))
        if prior_sum > 0.5:
            signal_side = "long"
        elif prior_sum < -0.5:
            signal_side = "short"

    if signal_side == "long":
        return RuleResult(
            score=-magnitude,
            side="short",
            detail=f"{label} - dusuk likidite, LONG cezalandirildi (backtest WR 44.7%, avg -4.51%) [-{magnitude}]",
        )
    if signal_side == "short":
        return RuleResult(
            score=magnitude,
            side="long",
            detail=f"{label} - dusuk likidite, SHORT cezalandirildi (backtest WR 44.7%, avg -4.51%) [+{magnitude}]",
        )
    return RuleResult(score=0, side="neutral", detail=f"{label} - yon belirsiz, cezasiz [0]")


rule_17_weekend_bonus = TradingRule(
    key="rule_17_weekend_bonus",
    name="Weekend Penalty",
    sources=["fr", "scanner", "hammer", "sniper"],
    evaluate=_evaluate,
)
