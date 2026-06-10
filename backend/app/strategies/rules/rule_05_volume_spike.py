from .rule_interface import TradingRule, MarketData, RuleResult, side_for


def _evaluate(data: MarketData) -> RuleResult:
    klines4h = data.klines.get("240")
    klines_d = data.klines.get("D")

    if not klines4h or len(klines4h) < 2 or not klines_d or len(klines_d) < 20:
        return RuleResult(score=0, side="neutral", detail="Insufficient kline data")

    current = klines4h[-1]
    current_volume = current.volume

    daily_slice = klines_d[-20:]
    avg_daily_volume = sum(k.volume for k in daily_slice) / len(daily_slice)
    avg_volume_4h = avg_daily_volume / 6

    if avg_volume_4h == 0:
        return RuleResult(score=0, side="neutral", detail="Zero average volume")

    volume_ratio = current_volume / avg_volume_4h
    price_change = ((current.close - current.open) / current.open) * 100 if current.open > 0 else 0
    bullish = price_change >= 0

    score = 0
    detail = ""

    pc_sign = "+" if price_change >= 0 else ""

    if volume_ratio >= 6.0:
        score = 0.5 if bullish else -0.5
        detail = f"Manipulation warning: ratio {volume_ratio:.1f}x, price {pc_sign}{price_change:.2f}%"
    elif volume_ratio >= 3.5:
        score = 1.5 if bullish else -1.5
        detail = f"Extreme volume: ratio {volume_ratio:.1f}x, price {pc_sign}{price_change:.2f}%"
    elif volume_ratio >= 2.0:
        score = 1.0 if bullish else -1.0
        detail = f"Strong volume: ratio {volume_ratio:.1f}x, price {pc_sign}{price_change:.2f}%"
    elif volume_ratio >= 1.3:
        score = 0.5 if bullish else -0.5
        detail = f"Volume increase: ratio {volume_ratio:.1f}x, price {pc_sign}{price_change:.2f}%"

    klines1h = data.klines.get("60")
    if score != 0 and klines1h and len(klines1h) >= 2:
        current1h = klines1h[-1]
        avg_volume_1h = avg_daily_volume / 24
        ratio1h = current1h.volume / avg_volume_1h if avg_volume_1h > 0 else 0
        price_change1h = ((current1h.close - current1h.open) / current1h.open) * 100 if current1h.open > 0 else 0
        bullish1h = price_change1h >= 0
        if ratio1h >= 1.3 and bullish1h == bullish:
            score += 0.5 if bullish else -0.5
            detail += f" | 1H+4H confirm ({'+' if bullish else '-'}0.5): 1H ratio {ratio1h:.1f}x"

    return RuleResult(score=score, side=side_for(score), detail=detail)


rule_05_volume_spike = TradingRule(
    key="rule_05_volume",
    name="Volume Spike",
    sources=["scanner"],
    evaluate=_evaluate,
)
