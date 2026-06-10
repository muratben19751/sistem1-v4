from .rule_interface import TradingRule, MarketData, RuleResult, side_for


def _evaluate(data: MarketData) -> RuleResult:
    oi_change = data.open_interest_change
    klines1h = data.klines.get("60")

    if not klines1h or len(klines1h) < 2:
        return RuleResult(score=0, side="neutral", detail="OI: 1h price data unavailable")

    last = klines1h[-1]
    prev = klines1h[-2]
    price_up = last.close >= prev.close
    dir = "up" if price_up else "down"

    score = 0
    detail = ""

    if oi_change > 5:
        score = 1 if price_up else -1
        detail = f"OI +{oi_change:.1f}% & price {dir}"
    elif oi_change > 3:
        score = 0.5 if price_up else -0.5
        detail = f"OI +{oi_change:.1f}% & price {dir}"
    elif oi_change < -5:
        score = -0.5 if price_up else 0.5
        detail = f"OI {oi_change:.1f}% & price {dir}"
    else:
        detail = f"OI {'+' if oi_change >= 0 else ''}{oi_change:.1f}% notr (esik disi) & price {dir}"

    return RuleResult(score=score, side=side_for(score), detail=detail)


rule_11_open_interest = TradingRule(
    key="rule_11_open_interest",
    name="Open Interest",
    sources=["scanner", "fr"],
    evaluate=_evaluate,
)
