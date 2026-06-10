from .rule_interface import TradingRule, MarketData, RuleResult
from ...lib.indicators import Kline


def _calc_utbot(candles: list[Kline], atr_period: int = 10, key_value: float = 1):
    n = len(candles)
    if n < atr_period + 2:
        return {"trend": 0, "lastBuy": -1, "lastSell": -1}

    tr = [0.0]
    for i in range(1, n):
        tr.append(max(
            candles[i].high - candles[i].low,
            abs(candles[i].high - candles[i - 1].close),
            abs(candles[i].low - candles[i - 1].close),
        ))

    atr: list = [None] * n
    s = 0.0
    for i in range(1, atr_period + 1):
        s += tr[i]
    atr[atr_period] = s / atr_period
    for i in range(atr_period + 1, n):
        atr[i] = (atr[i - 1] * (atr_period - 1) + tr[i]) / atr_period

    prev_trail = 0.0
    prev_close = candles[atr_period].close
    last_buy = -1
    last_sell = -1
    final_trail = 0.0

    for i in range(atr_period, n):
        n_loss = atr[i] * key_value
        close = candles[i].close

        if close > prev_trail and prev_close > prev_trail:
            trail = max(prev_trail, close - n_loss)
        elif close < prev_trail and prev_close < prev_trail:
            trail = min(prev_trail, close + n_loss)
        elif close > prev_trail:
            trail = close - n_loss
        else:
            trail = close + n_loss

        if prev_close <= prev_trail and close > trail:
            last_buy = i
        if prev_close >= prev_trail and close < trail:
            last_sell = i

        final_trail = trail
        prev_trail = trail
        prev_close = close

    last_close = candles[n - 1].close
    trend = 1 if last_close > final_trail else -1 if last_close < final_trail else 0

    return {"trend": trend, "lastBuy": last_buy, "lastSell": last_sell}


def _evaluate(data: MarketData) -> RuleResult:
    klines = data.klines.get("5")
    if not klines or len(klines) < 15:
        return RuleResult(score=0, side="neutral", detail="Not enough 5m data")

    res = _calc_utbot(klines, 10, 1)
    trend = res["trend"]
    last_buy = res["lastBuy"]
    last_sell = res["lastSell"]
    n = len(klines)
    last = n - 1

    score = 0
    detail = ""

    if last_buy == last:
        score = 2
        detail = "UT Bot BUY signal on current candle"
    elif last_buy >= last - 2 and last_buy > 0:
        score = 1
        detail = f"UT Bot BUY signal {last - last_buy} candles ago"
    elif last_sell == last:
        score = -2
        detail = "UT Bot SELL signal on current candle"
    elif last_sell >= last - 2 and last_sell > 0:
        score = -1
        detail = f"UT Bot SELL signal {last - last_sell} candles ago"
    elif trend == 1:
        score = 0.5
        detail = "UT Bot uptrend (price above trail stop)"
    elif trend == -1:
        score = -0.5
        detail = "UT Bot downtrend (price below trail stop)"

    return RuleResult(score=score, side="long" if score > 0 else "short" if score < 0 else "neutral", detail=detail)


rule_21_utbot_5m = TradingRule(
    key="rule_21_utbot_5m",
    name="UT Bot Alert (5m)",
    evaluate=_evaluate,
)
