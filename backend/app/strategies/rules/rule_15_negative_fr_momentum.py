import math

from .rule_interface import TradingRule, MarketData, RuleResult, side_for


def _evaluate(data: MarketData) -> RuleResult:
    fr = data.funding_rate
    fr_pct = fr * 100

    score = 0
    details: list[str] = []

    history = data.funding_rate_history
    is_improving = False
    is_worsening = False
    is_dropping_from_high = False
    is_rising_from_zero = False
    fr_values: list[float] = []

    if history and len(history) >= 2:
        sorted_h = sorted(history, key=lambda h: float(h["fundingRateTimestamp"]))
        recent = sorted_h[-3:]
        fr_values = [float(h["fundingRate"]) * 100 for h in recent]

        strictly_increasing = all(i == 0 or v > fr_values[i - 1] for i, v in enumerate(fr_values))
        strictly_decreasing = all(i == 0 or v < fr_values[i - 1] for i, v in enumerate(fr_values))

        if fr_pct < 0:
            is_improving = strictly_increasing
            is_worsening = strictly_decreasing
        elif fr_pct > 0:
            is_dropping_from_high = strictly_decreasing
            is_rising_from_zero = strictly_increasing

        if fr_pct < 0:
            if fr_pct <= -0.75:
                if is_improving:
                    score += 2
                    details.append(f"Ekstrem Neg FR Squeeze! İyileşiyor ({fr_pct:.3f}%) [+2]")
                else:
                    details.append(f"Ekstrem Neg FR ({fr_pct:.3f}%) → Dipte short aranmaz [0]")
            elif is_improving and fr_pct > -0.25:
                score += 1.5
                details.append(f"Neg FR iyileşme trendi ({' → '.join(f'{v:.3f}%' for v in fr_values)}) [+1.5]")
            elif is_improving and fr_pct <= -0.25:
                score += 0.5
                details.append(f"Neg FR iyileşiyor ama derin ({fr_pct:.3f}%) [+0.5]")
            elif is_worsening:
                details.append("Neg FR kötüleşiyor → Düşen bıçak, beklemede kal [0]")

            if fr_pct >= -0.10 and fr_pct < 0:
                price_change = float(data.ticker.get("price24hPcnt") or 0)
                if price_change > 0.10:
                    score += 2
                    details.append(f"Kaliteli Neg FR + Gerçek Pump ({(price_change * 100):.1f}%) [+2]")
                elif price_change > 0.05:
                    score += 1
                    details.append(f"Kaliteli Neg FR + Yükseliş ({(price_change * 100):.1f}%) [+1]")
        elif fr_pct > 0:
            if fr_pct >= 0.75:
                if is_dropping_from_high:
                    score -= 2
                    details.append(f"Ekstrem Poz FR Squeeze! Soğuyor ({fr_pct:.3f}%) [-2]")
                else:
                    details.append(f"Ekstrem Poz FR ({fr_pct:.3f}%) → Tepede long aranmaz [0]")
            elif is_dropping_from_high and fr_pct < 0.25:
                score -= 1.5
                details.append(f"Poz FR soğuma trendi ({' → '.join(f'{v:.3f}%' for v in fr_values)}) [-1.5]")
            elif is_dropping_from_high and fr_pct >= 0.25:
                score -= 0.5
                details.append(f"Poz FR soğuyor ama yüksek ({fr_pct:.3f}%) [-0.5]")
            elif is_rising_from_zero:
                details.append("Poz FR artıyor → Trend devamı, beklemede kal [0]")

            if fr_pct > 0 and fr_pct <= 0.10:
                price_change = float(data.ticker.get("price24hPcnt") or 0)
                if price_change < -0.10:
                    score -= 2
                    details.append(f"Kaliteli Poz FR + Gerçek Dump ({(price_change * 100):.1f}%) [-2]")
                elif price_change < -0.05:
                    score -= 1
                    details.append(f"Kaliteli Poz FR + Düşüş ({(price_change * 100):.1f}%) [-1]")
    else:
        details.append("Yeterli FR geçmişi yok")

    interval_h = data.funding_interval_hours if data.funding_interval_hours is not None else 8
    if interval_h <= 1:
        if fr_pct > -0.25 and fr_pct < 0 and is_improving:
            score += 1
            details.append(f"Hızlı cycle: {interval_h}H + Neg FR [+1]")
        elif fr_pct < 0.25 and fr_pct > 0 and is_dropping_from_high:
            score -= 1
            details.append(f"Hızlı cycle: {interval_h}H + Poz FR [-1]")
    elif interval_h <= 2:
        if fr_pct > -0.10 and fr_pct < 0 and is_improving:
            score += 0.5
            details.append(f"Kısa cycle: {interval_h}H + Neg FR [+0.5]")
        elif fr_pct < 0.10 and fr_pct > 0 and is_dropping_from_high:
            score -= 0.5
            details.append(f"Kısa cycle: {interval_h}H + Poz FR [-0.5]")

    score = math.floor(score * 100 + 0.5) / 100

    detail_body = " | ".join(details) if details else "nötr"
    return RuleResult(
        score=score,
        side=side_for(score),
        detail=f"FR: {fr_pct:.4f}% | {detail_body}",
    )


rule_15_negative_fr_momentum = TradingRule(
    key="rule_15_neg_fr_momentum",
    name="FR Momentum (Symmetric)",
    sources=["fr"],
    evaluate=_evaluate,
)
