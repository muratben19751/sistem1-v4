from .rule_interface import TradingRule, MarketData, RuleResult
from ...lib.indicators import calc_atr


def _evaluate(data: MarketData) -> RuleResult:
    klines4h = data.klines.get("240")

    if not klines4h or len(klines4h) < 2:
        return RuleResult(score=0, side="neutral", detail="Insufficient 4H data")

    current = klines4h[-1]
    price_change_4h = ((current.close - current.open) / current.open) * 100 if current.open > 0 else 0
    abs_price_change = abs(price_change_4h)
    bullish = price_change_4h > 0

    atr = calc_atr(klines4h, 14)

    if atr and atr > 0:
        price_move = abs(current.close - current.open)
        atr_ratio = price_move / atr

        if atr_ratio < 1.5:
            return RuleResult(score=0, side="neutral", detail=f"Normal move: ATR ratio {atr_ratio:.2f}x")

        score = 0
        flag = ""

        if bullish:
            if atr_ratio >= 6.0:
                score = -3
                flag = "EXTREME_CHASE_WARNING"
            elif atr_ratio >= 4.0:
                score = -2
                flag = "DANGER_ZONE"
            elif atr_ratio >= 2.5:
                score = -1.5
                flag = "FOMO_ZONE"
            else:
                score = -1
        else:
            if atr_ratio >= 6.0:
                score = -2
                flag = "FALLING_KNIFE_WARNING"
            elif atr_ratio >= 4.0:
                score = -1.5
                flag = "DANGER_ZONE"
            elif atr_ratio >= 2.5:
                score = -1
                flag = "FOMO_ZONE"
            else:
                score = -0.5

        dir = "short" if bullish else "long"
        detail = f"{dir} penalty: ATR ratio {atr_ratio:.2f}x, 4H {'+' if price_change_4h >= 0 else ''}{price_change_4h:.2f}%{(' [' + flag + ']') if flag else ''}"
        return RuleResult(score=score, side=dir, detail=detail)

    score = 0
    flag = ""

    if bullish:
        if abs_price_change >= 25:
            score = -3
            flag = "EXTREME_CHASE_WARNING"
        elif abs_price_change >= 18:
            score = -2
            flag = "DANGER_ZONE"
        elif abs_price_change >= 12:
            score = -1.5
            flag = "FOMO_ZONE"
        elif abs_price_change >= 8:
            score = -1
    else:
        if abs_price_change >= 25:
            score = -2
            flag = "FALLING_KNIFE_WARNING"
        elif abs_price_change >= 18:
            score = -1.5
            flag = "DANGER_ZONE"
        elif abs_price_change >= 12:
            score = -1
            flag = "FOMO_ZONE"
        elif abs_price_change >= 8:
            score = -0.5

    if score == 0:
        return RuleResult(score=0, side="neutral", detail=f"Normal move: 4H {'+' if price_change_4h >= 0 else ''}{price_change_4h:.2f}% (no ATR)")

    dir = "short" if bullish else "long"
    detail = f"{dir} penalty: 4H {'+' if price_change_4h >= 0 else ''}{price_change_4h:.2f}% fallback{(' [' + flag + ']') if flag else ''}"
    return RuleResult(score=score, side=dir, detail=detail)


rule_12_anti_chase = TradingRule(
    key="rule_12_anti_chase",
    name="Anti-Chase Penalty",
    sources=["scanner"],
    evaluate=_evaluate,
)
