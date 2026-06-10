from .rule_interface import TradingRule, MarketData, RuleResult
from ...lib.indicators import calc_adx


def _evaluate(data: MarketData) -> RuleResult:
    klines = data.klines.get("60")
    if not klines or len(klines) < 30:
        return RuleResult(score=0, side="neutral", detail="Not enough 1H data")
    adx = calc_adx(klines, 14)
    if not adx:
        return RuleResult(score=0, side="neutral", detail="ADX hesaplanamadi")

    direction = "long" if adx["plusDI"] >= adx["minusDI"] else "short"
    sign = 1 if direction == "long" else -1
    tag = f"ADX={adx['adx']:.1f} +DI={adx['plusDI']:.1f} -DI={adx['minusDI']:.1f}"

    if adx["adx"] >= 40:
        return RuleResult(score=sign * 2, side=direction, detail=f"Cok guclu trend ({tag})")
    if adx["adx"] >= 25:
        return RuleResult(score=sign * 1.5, side=direction, detail=f"Guclu trend ({tag})")
    if adx["adx"] >= 20:
        return RuleResult(score=sign * 0.5, side=direction, detail=f"Gelisen trend ({tag})")
    return RuleResult(score=0, side="neutral", detail=f"Zayif/yatay ({tag})")


rule_26_adx_trend = TradingRule(
    key="rule_26_adx_trend",
    name="ADX Trend Strength (1H)",
    sources=["scanner", "sniper", "hammer", "fr"],
    evaluate=_evaluate,
)
