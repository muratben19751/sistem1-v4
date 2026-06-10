import math

from .rule_interface import TradingRule, MarketData, RuleResult
from ...core.time import now_ms

FR_BASE_THRESHOLD = -0.0005
FR_EXTREME_THRESHOLD = -0.01
FR_BONUS_LOW = -0.001
FR_BONUS_HIGH = -0.002
VOLUME_MIN = 1.0


def _countdown_hours(data: MarketData):
    interval_hours = data.funding_interval_hours
    if interval_hours is None or not math.isfinite(interval_hours) or interval_hours <= 0:
        return None
    # Backtest: sinyal ani; canli: simdi (eval_ms None) -> look-ahead korumali geri sayim
    now = data.eval_ms if data.eval_ms is not None else now_ms()
    history = data.funding_rate_history
    if history and len(history) > 0:
        last_ts = max(h["fundingRateTimestamp"] for h in history)
        if math.isfinite(last_ts) and last_ts > 0:
            next_ms = last_ts + interval_hours * 3_600_000
            return max(0, (next_ms - now) / 3_600_000)
    interval_ms = interval_hours * 3_600_000
    return (math.ceil(now / interval_ms) * interval_ms - now) / 3_600_000


def _evaluate(data: MarketData) -> RuleResult:
    fr = data.funding_rate
    if not math.isfinite(fr) or fr >= FR_BASE_THRESHOLD:
        return RuleResult(score=0, side="neutral", detail=f"FR {fr * 100:.3f}% >= -0.05%, squeeze esigi saglanmadi")

    history = data.funding_rate_history or []
    if len(history) < 2:
        return RuleResult(score=0, side="neutral", detail="FR history yetersiz")
    sorted_h = sorted(history, key=lambda h: h["fundingRateTimestamp"])
    prev = sorted_h[-2]["fundingRate"]
    rising = fr > prev
    if not rising:
        return RuleResult(score=0, side="neutral", detail=f"FR artmiyor ({prev * 100:.3f}% -> {fr * 100:.3f}%)")

    oi_change = data.open_interest_change
    oi_known = math.isfinite(oi_change) and oi_change != 0
    if oi_known and oi_change <= 0:
        return RuleResult(score=0, side="neutral", detail=f"OI artmiyor ({oi_change:.2f}%)")

    vol_change = data.volume_change
    if not math.isfinite(vol_change) or vol_change < VOLUME_MIN:
        return RuleResult(score=0, side="neutral", detail=f"Hacim yetersiz ({vol_change:.2f}x)")

    cd_h = _countdown_hours(data)
    if cd_h is not None and cd_h < 1 and fr < FR_EXTREME_THRESHOLD:
        base = 5
        base_label = "FR<-1.0% & geri sayim <1H"
    elif cd_h is not None and cd_h < 1:
        base = 4
        base_label = "geri sayim <1H"
    elif cd_h is not None and cd_h < 4:
        base = 3
        base_label = "geri sayim 1-4H"
    else:
        base = 2
        base_label = "geri sayim bilinmiyor" if cd_h is None else "geri sayim >4H"

    bonus = 0
    bonus_label = "bonus yok"
    if fr < FR_BONUS_HIGH:
        bonus = 2
        bonus_label = "FR<-0.20% bonus +2"
    elif fr < FR_BONUS_LOW:
        bonus = 1
        bonus_label = "FR<-0.10% bonus +1"

    total = base + bonus
    oi_note = f"OI={oi_change:.2f}%" if oi_known else "OI=bilinmiyor"
    cd_note = f"{cd_h:.2f}h" if cd_h is not None else "N/A"

    return RuleResult(
        score=total,
        side="long",
        detail=f"Squeeze: {base_label} [+{base}] + {bonus_label} = +{total} (FR={fr * 100:.3f}%, {oi_note}, vol={vol_change:.2f}x, countdown={cd_note})",
    )


rule_25_fr_squeeze_setup = TradingRule(
    key="rule_25_fr_squeeze_setup",
    name="FR Squeeze Set Up",
    sources=["fr"],
    recommended_tp=5,
    recommended_sl=3,
    evaluate=_evaluate,
)
