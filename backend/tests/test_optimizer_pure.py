"""app/agents/backtest_optimizer.py — saf yardimcilar (walk-forward, kalite, fitness)."""
from types import SimpleNamespace

import pytest

from app.agents import backtest_optimizer as opt
from app.agents.backtest_optimizer import (
    CALMAR_CAP,
    CALMAR_W,
    DD_FLOOR,
    MIN_FOLD_TRADES,
    PF_GATE_PENALTY,
    SHARPE_W,
    TRADE_CONF_K,
    WF_EMBARGO_DAYS,
    WF_FOLDS,
    _clamp,
    _mean,
    _std,
    aggregate_folds,
    build_folds,
    compute_fitness,
    fold_quality,
)


class TestClamp:
    def test_within(self):
        assert _clamp(5, 0, 10) == 5

    def test_below_and_above(self):
        assert _clamp(-3, 0, 10) == 0
        assert _clamp(99, 0, 10) == 10


class TestMeanStd:
    def test_mean(self):
        assert _mean([2, 4, 6]) == 4.0
        assert _mean([]) == 0.0

    def test_std(self):
        assert _std([2, 4]) == pytest.approx(1.0)
        assert _std([5]) == 0.0  # tek eleman
        assert _std([]) == 0.0


class TestBuildFolds:
    def test_count_matches_wf_folds(self):
        folds = build_folds(0, 365 * 86_400_000)
        assert len(folds) == WF_FOLDS

    def test_covers_full_span(self):
        start, end = 1_000_000, 1_000_000 + 300 * 86_400_000
        folds = build_folds(start, end)
        assert folds[0][0] == start
        assert folds[-1][1] == end

    def test_embargo_gap_between_folds(self):
        if WF_FOLDS <= 1:
            pytest.skip("tek fold modu")
        start, end = 0, 300 * 86_400_000
        folds = build_folds(start, end)
        embargo_ms = int(WF_EMBARGO_DAYS * 86_400_000)
        for i in range(len(folds) - 1):
            gap = folds[i + 1][0] - folds[i][1]
            assert gap == embargo_ms

    def test_folds_non_overlapping_and_ordered(self):
        folds = build_folds(0, 300 * 86_400_000)
        for i in range(len(folds) - 1):
            assert folds[i][1] <= folds[i + 1][0]
            assert folds[i][0] < folds[i][1]


class TestFoldQuality:
    def test_too_few_trades_invalid(self):
        q, ok = fold_quality({"trades": MIN_FOLD_TRADES - 1, "totalPnlPct": 50})
        assert ok is False and q == 0.0

    def test_valid_quality_value(self):
        m = {"trades": 100, "totalPnlPct": 10, "maxDrawdown": 5, "sharpe": 1.0, "profitFactor": 2.0}
        q, ok = fold_quality(m)
        assert ok is True
        calmar = max(-CALMAR_CAP, min(CALMAR_CAP, 10 / max(5, DD_FLOOR)))
        base = CALMAR_W * calmar + SHARPE_W * 1.0  # pf>=1, ceza yok
        conf = 100 / (100 + TRADE_CONF_K)
        assert q == pytest.approx(base * conf)

    def test_profit_factor_penalty(self):
        good = {"trades": 100, "totalPnlPct": 10, "maxDrawdown": 5, "sharpe": 1.0, "profitFactor": 2.0}
        bad = {**good, "profitFactor": 0.5}
        qg, _ = fold_quality(good)
        qb, _ = fold_quality(bad)
        conf = 100 / (100 + TRADE_CONF_K)
        assert qg - qb == pytest.approx(PF_GATE_PENALTY * conf)

    def test_calmar_capped(self):
        m = {"trades": 100, "totalPnlPct": 10_000, "maxDrawdown": 1, "sharpe": 0, "profitFactor": 2.0}
        q, ok = fold_quality(m)
        conf = 100 / (100 + TRADE_CONF_K)
        assert q == pytest.approx(CALMAR_W * CALMAR_CAP * conf)


def _fold(trades, pnl, pnlpct, dd=5.0, sharpe=1.0, pf=2.0):
    wins = trades * 6 // 10
    return {
        "trades": trades, "wins": wins, "losses": trades - wins,
        "totalPnl": pnl, "totalPnlPct": pnlpct, "maxDrawdown": dd,
        "sharpe": sharpe, "profitFactor": pf,
    }


class TestAggregateFolds:
    G = SimpleNamespace(leverage=3)

    def test_combined_metrics_are_fold_sums(self):
        folds = [_fold(10, 100.0, 5.0, dd=4.0), _fold(20, 200.0, 8.0, dd=9.0)]
        combined, wf, fitness = aggregate_folds(folds, self.G)
        assert combined["trades"] == 30          # SUM
        assert combined["totalPnl"] == 300.0     # SUM
        assert combined["maxDrawdown"] == 9.0     # MAX
        assert wf["folds"] == 2

    def test_winrate_from_summed_wins(self):
        folds = [_fold(10, 100.0, 5.0), _fold(20, 200.0, 8.0)]
        combined, _, _ = aggregate_folds(folds, self.G)
        total_wins = combined["wins"]
        assert combined["winRate"] == pytest.approx(total_wins / 30 * 100, abs=0.01)

    def test_all_invalid_folds_reject_fitness(self):
        folds = [_fold(1, 10.0, 1.0), _fold(2, 20.0, 1.0)]  # trades < MIN_FOLD_TRADES
        combined, wf, fitness = aggregate_folds(folds, self.G)
        assert fitness == -1.0
        assert wf["validFolds"] == 0

    def test_valid_folds_positive_fitness(self):
        folds = [_fold(100, 500.0, 10.0), _fold(100, 480.0, 9.0)]
        _, wf, fitness = aggregate_folds(folds, self.G)
        assert wf["validFolds"] == 2
        assert fitness > 0

    def test_compute_fitness_single_metric(self):
        # geriye donuk: tek metrik sozlugu -> fitness sayisi
        f = compute_fitness(_fold(100, 500.0, 10.0), self.G)
        assert isinstance(f, float)
