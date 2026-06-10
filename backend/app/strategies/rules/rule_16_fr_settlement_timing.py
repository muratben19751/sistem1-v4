from datetime import datetime, timezone

from .rule_interface import TradingRule, MarketData, RuleResult, side_for


def _eval_dt(data: MarketData) -> datetime:
    # Backtest: sinyal ani; canli: simdi (eval_ms None)
    if data.eval_ms is not None:
        return datetime.fromtimestamp(data.eval_ms / 1000, tz=timezone.utc)
    return datetime.now(timezone.utc)


def _evaluate(data: MarketData) -> RuleResult:
    utc_hour = _eval_dt(data).hour

    score = 0
    detail = ""

    if utc_hour == 8:
        score = -2
        detail = "08:00 UTC settlement → EN KOTU saat (WR 1h: 39%, Ort 4h: -4.03%) [-2]"
    elif utc_hour == 0:
        score = -1
        detail = "00:00 UTC settlement → riskli (WR 4h: 32.1%) [-1]"
    elif utc_hour == 7:
        score = -1
        detail = "07:00 UTC → settlement öncesi belirsizlik [-1]"
    elif utc_hour >= 10 and utc_hour <= 14:
        score = -0.5
        detail = f"{utc_hour}:00 UTC → öğle saatleri, düşük performans [-0.5]"

    if utc_hour == 2:
        score = 2
        detail = "02:00 UTC → EN IYI saat (WR 4h: 64.4%, Ort 4h: +6.38%) [+2]"
    elif utc_hour == 3:
        score = 2
        detail = "03:00 UTC → mükemmel saat (WR 4h: 71.7%) [+2]"
    elif utc_hour == 4:
        score = 1.5
        detail = "04:00 UTC → güçlü saat (WR 4h: 61.7%) [+1.5]"
    elif utc_hour == 23:
        score = 1
        detail = "23:00 UTC → iyi saat (WR 1h: 75.9%) [+1]"
    elif utc_hour == 15:
        score = 1
        detail = "15:00 UTC → yüksek WR 1h (81.9%) [+1]"
    elif utc_hour == 16:
        score = 0.5
        detail = "16:00 UTC settlement → pozitif (Ort 4h: +1.75%) [+0.5]"

    return RuleResult(
        score=score,
        side=side_for(score),
        detail=detail or f"{utc_hour}:00 UTC → nötr bölge [0]",
    )


rule_16_fr_settlement_timing = TradingRule(
    key="rule_16_fr_settlement_timing",
    name="FR Settlement Timing",
    sources=["fr", "scanner", "hammer", "sniper"],
    evaluate=_evaluate,
)
