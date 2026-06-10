from .rule_interface import TradingRule, MarketData, RuleResult
from ...lib.indicators import detect_rsi_divergence, calc_nadaraya_watson, calc_wave_trend


def div_label(d: dict, side: str) -> str:
    dir = "Ayi" if side == "short" else "Boga"
    if d["type"] == "bearish" or d["type"] == "bullish":
        return f"{dir} (Kesinlesmis)"
    return f"{dir} (Olusuyor)"


def nw_label(nw, side: str) -> str:
    if not nw:
        return "Veri yok"
    if side == "short":
        if nw["position"] > 0.7:
            return "Ust bantta temas"
        if nw["position"] > 0.4 and nw["trend"] == "down":
            return "Ust banttan donus"
        if nw["position"] > 0.4:
            return "Ust banda yakin"
        return "Notr"
    if nw["position"] < -0.7:
        return "Alt bantta temas"
    if nw["position"] < -0.4 and nw["trend"] == "up":
        return "Alt banttan donus"
    if nw["position"] < -0.4:
        return "Alt banda yakin"
    return "Notr"


def wt_label(wt, side: str) -> str:
    if not wt:
        return "Veri yok"
    if side == "short":
        if wt["signal"] == "sell":
            return "Satis sinyali"
        if wt["signal"] == "approaching_sell":
            return "Yaklasan satis"
        if wt["overbought"]:
            return "Asiri alim bolgesi"
        return "Notr"
    if wt["signal"] == "buy":
        return "Alis sinyali"
    if wt["signal"] == "approaching_buy":
        return "Yaklasan alis"
    if wt["oversold"]:
        return "Asiri satim bolgesi"
    return "Notr"


def is_same_direction(d: dict, side: str) -> bool:
    if side == "short":
        return d["type"] == "bearish" or d["type"] == "forming_bearish"
    return d["type"] == "bullish" or d["type"] == "forming_bullish"


def is_opposite_direction(d: dict, side: str) -> bool:
    if side == "short":
        return d["type"] == "bullish" or d["type"] == "forming_bullish"
    return d["type"] == "bearish" or d["type"] == "forming_bearish"


def _evaluate(data: MarketData) -> RuleResult:
    klines4h = data.klines.get("240")
    if not klines4h or len(klines4h) < 50:
        return RuleResult(score=0, side="neutral", detail="Yetersiz veri (4H)")

    div4h = detect_rsi_divergence(klines4h)
    if div4h["type"] == "none":
        return RuleResult(score=0, side="neutral", detail="RSI uyumsuzlugu yok")

    side = "short" if (div4h["type"] == "bearish" or div4h["type"] == "forming_bearish") else "long"
    is_confirmed = div4h["type"] == "bearish" or div4h["type"] == "bullish"
    score = 1.5 if is_confirmed else 0.75

    klines1h = data.klines.get("60")
    klines1d = data.klines.get("D")
    div1h = None
    div1d = None

    if klines1h and len(klines1h) >= 50:
        div1h = detect_rsi_divergence(klines1h)
        if is_same_direction(div1h, side):
            score += 0.25
        elif is_opposite_direction(div1h, side):
            score -= 0.25

    if klines1d and len(klines1d) >= 50:
        div1d = detect_rsi_divergence(klines1d)
        if is_same_direction(div1d, side):
            score += 0.25
        elif is_opposite_direction(div1d, side):
            score -= 0.25

    nw = calc_nadaraya_watson(klines4h)
    if nw:
        if side == "short":
            if nw["position"] > 0.7:
                score += 0.5
            elif nw["position"] > 0.4:
                score += 0.25
            elif nw["position"] < -0.3:
                score -= 0.25
        else:
            if nw["position"] < -0.7:
                score += 0.5
            elif nw["position"] < -0.4:
                score += 0.25
            elif nw["position"] > 0.3:
                score -= 0.25

    wt = calc_wave_trend(klines4h)
    if wt:
        if side == "short":
            if wt["signal"] == "sell":
                score += 0.5
            elif wt["signal"] == "approaching_sell" or wt["overbought"]:
                score += 0.25
            elif wt["signal"] == "buy":
                score -= 0.25
        else:
            if wt["signal"] == "buy":
                score += 0.5
            elif wt["signal"] == "approaching_buy" or wt["oversold"]:
                score += 0.25
            elif wt["signal"] == "sell":
                score -= 0.25

    score = max(0.5, score)
    abs_score = score
    final_score = -abs_score if side == "short" else abs_score

    strength = "Zayif"
    if abs_score >= 2.5:
        strength = "Guclu"
    elif abs_score >= 1.5:
        strength = "Orta"

    detail = " | ".join([
        f"Islem Yonu: {'Short' if side == 'short' else 'Long'}",
        f"RSI Uyumsuzlugu: {div_label(div4h, side)}",
        f"1H Teyidi: {('Var' if is_same_direction(div1h, side) else 'Zit' if is_opposite_direction(div1h, side) else 'Yok') if div1h else 'Veri yok'}",
        f"1D Teyidi: {('Var' if is_same_direction(div1d, side) else 'Zit' if is_opposite_direction(div1d, side) else 'Yok') if div1d else 'Veri yok'}",
        f"NW Durumu: {nw_label(nw, side)}",
        f"WT Durumu: {wt_label(wt, side)}",
        f"Sinyal Gucu: {strength}",
    ])

    return RuleResult(score=final_score, side=side, detail=detail)


rule_14_rsi_divergence_composite = TradingRule(
    key="rule_14_rsi_divergence",
    name="RSI Divergence + NW + WT",
    sources=["sniper"],
    evaluate=_evaluate,
)
