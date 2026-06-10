from .rule_interface import TradingRule, MarketData, RuleResult, side_for


def _evaluate(data: MarketData) -> RuleResult:
    fr = data.funding_rate
    fr_pct = fr * 100

    score = 0
    detail = ""

    if fr_pct < -0.75:
        score = -3
        detail = f"EXTREME neg FR {fr_pct:.4f}% → yapısal düşüş, DIP ALMA [-3]"
    elif fr_pct < -0.25:
        score = -1
        detail = f"Yuksek neg FR {fr_pct:.4f}% → trend devam riski [-1]"
    elif fr_pct < -0.05:
        score = 0
        detail = f"Orta neg FR {fr_pct:.4f}% → nötr [0]"
    elif fr_pct < -0.005:
        score = 2
        detail = f"Dusuk neg FR {fr_pct:.4f}% → kaliteli long bolgesi [+2]"
    elif fr_pct <= 0.005:
        score = 1
        detail = f"Minimal FR {fr_pct:.4f}% → stabil, iyi WR [+1]"

    if fr_pct > 0.1:
        score = -2
        detail = f"Extreme pozitif FR {fr_pct:.4f}% → asiri kalabalik long [-2]"
    elif fr_pct > 0.05:
        score = -1
        detail = f"Yuksek pozitif FR {fr_pct:.4f}% → kalabalik long [-1]"
    elif fr_pct > 0.005:
        score = 0
        detail = f"Normal pozitif FR {fr_pct:.4f}% → nötr [0]"

    return RuleResult(score=score, side=side_for(score), detail=detail)


rule_10_funding_rate = TradingRule(
    key="rule_10_funding_rate",
    name="Funding Rate (Data-Driven)",
    sources=["fr"],
    evaluate=_evaluate,
)
