"""app/lib/indicators.py — saf sayisal fonksiyonlar (v3 ile parite hedefli)."""
import math

import pytest

from app.lib.indicators import (
    Kline,
    calc_adx,
    calc_atr,
    calc_nadaraya_watson,
    calc_rsi,
    calc_rsi_series,
    calc_stoch_rsi,
    calc_volume_change,
    calc_wave_trend,
    detect_rsi_divergence,
    ema,
    sma,
)


def _kl(closes, highs=None, lows=None, vols=None):
    n = len(closes)
    highs = highs or [c * 1.01 for c in closes]
    lows = lows or [c * 0.99 for c in closes]
    vols = vols or [100.0] * n
    return [Kline(time=i * 60, open=closes[i], high=highs[i], low=lows[i], close=closes[i], volume=vols[i]) for i in range(n)]


# ---------------- RSI ----------------
class TestRsi:
    def test_insufficient_data_returns_neutral_50(self):
        assert calc_rsi([1, 2, 3], 14) == 50.0
        assert calc_rsi([], 14) == 50.0

    def test_monotonic_increasing_is_100(self):
        assert calc_rsi(list(range(1, 30)), 14) == 100.0

    def test_monotonic_decreasing_is_0(self):
        # surekli dusus -> avg_gain 0 -> rs 0 -> RSI 0
        assert calc_rsi(list(range(30, 1, -1)), 14) == 0.0

    def test_flat_series_no_movement(self):
        # hic hareket yok: avg_gain=avg_loss=0 -> avg_loss==0 -> 100.0 (kod davranisi)
        assert calc_rsi([100.0] * 30, 14) == 100.0

    def test_value_in_range(self):
        closes = [100, 101, 100, 102, 101, 103, 102, 104, 103, 105, 104, 106, 105, 107, 106, 108]
        v = calc_rsi([float(c) for c in closes], 14)
        assert 0.0 <= v <= 100.0

    def test_period_boundary(self):
        # tam period+1 eleman yeterli
        assert calc_rsi([float(i) for i in range(15)], 14) == 100.0
        assert calc_rsi([float(i) for i in range(14)], 14) == 50.0


class TestRsiSeries:
    def test_empty_when_insufficient(self):
        assert calc_rsi_series([1, 2, 3], 14) == []

    def test_length_matches_excess(self):
        closes = [float(i) for i in range(40)]
        s = calc_rsi_series(closes, 14)
        assert len(s) == len(closes) - 14
        assert all(0.0 <= x <= 100.0 for x in s)

    def test_last_equals_calc_rsi(self):
        closes = [100 + math.sin(i / 3) * 5 for i in range(60)]
        assert calc_rsi_series(closes, 14)[-1] == pytest.approx(calc_rsi(closes, 14))


# ---------------- SMA / EMA ----------------
class TestSma:
    def test_short_returns_empty(self):
        assert sma([1, 2], 5) == []

    def test_known_values(self):
        assert sma([1, 2, 3, 4, 5], 5) == [3.0]
        assert sma([2, 4, 6, 8], 2) == [3.0, 5.0, 7.0]

    def test_length(self):
        assert len(sma([float(i) for i in range(10)], 3)) == 8


class TestEma:
    def test_short_returns_empty(self):
        assert ema([1, 2], 5) == []

    def test_first_is_sma_seed(self):
        out = ema([1, 2, 3, 4, 5, 6], 3)
        assert out[0] == pytest.approx(2.0)  # ilk deger period seed = sma(1,2,3)

    def test_flat_series_stays_flat(self):
        assert all(x == pytest.approx(5.0) for x in ema([5.0] * 10, 3))

    def test_length(self):
        assert len(ema([float(i) for i in range(10)], 4)) == 7


# ---------------- StochRSI ----------------
class TestStochRsi:
    def test_insufficient_returns_neutral(self):
        assert calc_stoch_rsi([1, 2, 3], 14, 14) == {"k": 50.0, "d": 50.0}

    def test_structure_and_range(self):
        closes = [100 + math.sin(i / 4) * 10 for i in range(80)]
        out = calc_stoch_rsi(closes)
        assert set(out) == {"k", "d"}
        assert 0.0 <= out["k"] <= 100.0
        assert 0.0 <= out["d"] <= 100.0


# ---------------- ATR ----------------
class TestAtr:
    def test_none_when_short(self):
        assert calc_atr(_kl([1, 2, 3]), 14) is None

    def test_constant_range(self):
        # her bar high-low = 2, gap yok -> ATR = 2
        kl = [Kline(time=i, open=10, high=11, low=9, close=10, volume=1) for i in range(20)]
        assert calc_atr(kl, 14) == pytest.approx(2.0)

    def test_positive(self):
        kl = _kl([100 + i for i in range(20)])
        assert calc_atr(kl, 14) > 0


# ---------------- ADX ----------------
class TestAdx:
    def test_none_when_short(self):
        assert calc_adx(_kl([1, 2, 3]), 14) is None

    def test_structure(self):
        kl = _kl([100 + math.sin(i / 5) * 8 for i in range(60)])
        out = calc_adx(kl, 14)
        assert out is not None
        assert set(out) == {"adx", "plusDI", "minusDI"}
        assert out["adx"] >= 0
        assert out["plusDI"] >= 0 and out["minusDI"] >= 0

    def test_strong_uptrend_plus_di_dominates(self):
        kl = _kl([100 + i * 2 for i in range(60)])
        out = calc_adx(kl, 14)
        assert out["plusDI"] >= out["minusDI"]


# ---------------- Volume change ----------------
class TestVolumeChange:
    def test_zero_when_short(self):
        assert calc_volume_change(_kl([1, 2, 3]), 20) == 0.0

    def test_spike_positive(self):
        vols = [100.0] * 20 + [300.0]
        kl = _kl([100.0] * 21, vols=vols)
        assert calc_volume_change(kl, 20) == pytest.approx(200.0)

    def test_zero_avg_returns_zero(self):
        vols = [0.0] * 20 + [50.0]
        kl = _kl([100.0] * 21, vols=vols)
        assert calc_volume_change(kl, 20) == 0.0


# ---------------- Divergence ----------------
class TestDivergence:
    def test_none_when_short(self):
        out = detect_rsi_divergence(_kl([1, 2, 3]), 14, 5)
        assert out == {"type": "none", "strength": 0.0}

    def test_returns_valid_type(self):
        kl = _kl([100 + math.sin(i / 6) * 12 for i in range(80)])
        out = detect_rsi_divergence(kl)
        assert out["type"] in ("none", "bullish", "bearish", "forming_bullish", "forming_bearish")
        assert 0.0 <= out["strength"] <= 1.0


# ---------------- Nadaraya-Watson ----------------
class TestNadarayaWatson:
    def test_none_when_short(self):
        assert calc_nadaraya_watson(_kl([1.0] * 29)) is None

    def test_structure(self):
        kl = _kl([100 + math.sin(i / 5) * 6 for i in range(60)])
        out = calc_nadaraya_watson(kl)
        assert set(out) == {"regression", "upper", "lower", "position", "trend"}
        assert out["lower"] <= out["regression"] <= out["upper"]
        assert -1.0 <= out["position"] <= 1.0
        assert out["trend"] in ("up", "down", "flat")

    def test_flat_series_regression_near_value(self):
        out = calc_nadaraya_watson(_kl([50.0] * 40))
        assert out["regression"] == pytest.approx(50.0, abs=1e-6)
        # std=0 -> slope_threshold=0; trend minik float isaretine baglidir (parite davranisi)
        assert out["trend"] in ("up", "down", "flat")
        assert out["position"] == 0.0  # half_band ~0 -> pos 0

    def test_uptrend_detected(self):
        out = calc_nadaraya_watson(_kl([100 + i for i in range(40)]))
        assert out["trend"] == "up"


# ---------------- WaveTrend ----------------
class TestWaveTrend:
    def test_none_when_short(self):
        assert calc_wave_trend(_kl([1.0] * 10)) is None

    def test_structure(self):
        kl = _kl([100 + math.sin(i / 4) * 10 for i in range(120)])
        out = calc_wave_trend(kl)
        assert out is not None
        assert set(out) == {"wt1", "wt2", "signal", "overbought", "oversold"}
        assert out["signal"] in ("buy", "sell", "neutral", "approaching_buy", "approaching_sell")
        assert isinstance(out["overbought"], bool)
