"""app/engines/backtest_engine.py — saf metrik/zaman/pencere yardimcilari."""
import math

import pytest

from app.engines.backtest_engine import (
    compute_metrics,
    empty_result,
    parse_json,
    to_db_time,
    to_ms,
    within_time_window,
)


def _trade(pnl, margin=100.0):
    return {"pnl": pnl, "margin": margin}


class TestToMsToDbTime:
    def test_round_trip(self):
        ms = 1609459200000
        assert to_ms(to_db_time(ms)) == ms

    def test_to_ms_invalid_is_nan(self):
        assert math.isnan(to_ms("garbage"))

    def test_to_db_time_format(self):
        assert to_db_time(0) == "1970-01-01T00:00:00.000Z"


class TestParseJson:
    def test_valid(self):
        assert parse_json('{"a": 1}') == {"a": 1}

    def test_empty_and_invalid(self):
        assert parse_json("") == {}
        assert parse_json(None) == {}
        assert parse_json("{bad") == {}


class TestComputeMetrics:
    def test_empty(self):
        m = compute_metrics([], 10000, 0)
        assert m["trades"] == 0
        assert m["winRate"] == 0
        assert m["profitFactor"] == 0
        assert m["totalPnl"] == 0

    def test_all_wins(self):
        trades = [_trade(10), _trade(20), _trade(30)]
        m = compute_metrics(trades, 10000, 0)
        assert m["trades"] == 3
        assert m["wins"] == 3
        assert m["losses"] == 0
        assert m["winRate"] == 100
        assert m["totalPnl"] == 60
        assert m["profitFactor"] == 99  # gross_loss=0, gross_profit>0

    def test_all_losses(self):
        trades = [_trade(-10), _trade(-20)]
        m = compute_metrics(trades, 10000, 0)
        assert m["wins"] == 0
        assert m["losses"] == 2
        assert m["winRate"] == 0
        assert m["totalPnl"] == -30
        assert m["profitFactor"] == 0

    def test_mixed_profit_factor(self):
        trades = [_trade(30), _trade(-10), _trade(-5)]
        m = compute_metrics(trades, 10000, 0)
        # gross_profit=30, gross_loss=15 -> pf=2.0
        assert m["profitFactor"] == 2.0
        assert m["wins"] == 1 and m["losses"] == 2

    def test_zero_pnl_counts_as_loss(self):
        # pnl<=0 loss kabul edilir
        m = compute_metrics([_trade(0.0)], 10000, 0)
        assert m["losses"] == 1 and m["wins"] == 0

    def test_calmar_with_drawdown(self):
        # totalPnlPct = 100/10000*... totalPnl=100 -> pct=1.0 ; dd=2 -> calmar=0.5
        m = compute_metrics([_trade(100)], 10000, 2)
        assert m["totalPnlPct"] == 1.0
        assert m["calmar"] == 0.5

    def test_calmar_no_drawdown_positive(self):
        m = compute_metrics([_trade(100)], 10000, 0)
        assert m["calmar"] == 99

    def test_sharpe_zero_when_no_variance(self):
        m = compute_metrics([_trade(10), _trade(10)], 10000, 0)
        assert m["sharpe"] == 0  # std=0


class TestEmptyResult:
    def test_shape(self):
        r = empty_result(10000, 1609459200000)
        assert r["metrics"]["trades"] == 0
        assert r["trades"] == []
        assert len(r["equityCurve"]) == 1
        assert r["equityCurve"][0]["value"] == 10000
        assert r["coverage"]["entered"] == 0


class TestWithinTimeWindow:
    # 2021-01-01 00:00:00 UTC = Cuma (weekday 4). getUTCDay: (4+1)%7 = 5
    FRI_MS = 1609459200000

    def test_no_filters_always_true(self):
        assert within_time_window(self.FRI_MS, {}) is True

    def test_hour_in_range(self):
        assert within_time_window(self.FRI_MS, {"hourStart": 0, "hourEnd": 6}) is True

    def test_hour_out_of_range(self):
        assert within_time_window(self.FRI_MS, {"hourStart": 6, "hourEnd": 12}) is False

    def test_hour_wraparound(self):
        # saat 0, pencere 22->4 (sarmalama) -> icinde
        assert within_time_window(self.FRI_MS, {"hourStart": 22, "hourEnd": 4}) is True

    def test_allowed_days_match(self):
        # getUTCDay = 5 (Cuma)
        assert within_time_window(self.FRI_MS, {"allowedDays": [5]}) is True

    def test_allowed_days_no_match(self):
        assert within_time_window(self.FRI_MS, {"allowedDays": [0, 1]}) is False
