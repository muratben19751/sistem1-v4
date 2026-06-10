"""app/engines/backtest_engine.run_backtest — uctan uca (seed'li kline cache, AG YOK).

ensure_kline_range / ensure_funding_range no-op'lanir; tum kline'lar onceden seed edilir,
boylece motor tamamen deterministik ve ag'siz calisir.
"""
import json

import pytest

from app.db.database import execute, executemany
from app.engines import backtest_engine as be

SYMBOL = "BTCUSDT"
SRC = "hammer"
MS_DAY = 86_400_000
END_MS = 1_700_000_000_000
START_MS = END_MS - 2 * MS_DAY


def _seed_klines(interval, step_ms, from_ms, to_ms):
    rows = []
    t = from_ms
    i = 0
    while t <= to_ms:
        # ~100 etrafinda hafif salinim (tp/sl %5'e carpmaz -> window_end cikisi)
        close = 100.0 + (i % 7) * 0.1
        rows.append((SYMBOL, interval, t, close, close * 1.002, close * 0.998, close, 100.0))
        t += step_ms
        i += 1
    executemany(
        "INSERT OR IGNORE INTO kline_cache (symbol, interval, open_time, o, h, l, c, v) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


def _seed_alert(ms, direction="UP"):
    from app.core.time import format_db_time_ms
    execute(
        "INSERT INTO alerts (symbol, direction, source_type, signal_type, raw_message, rsi_data, srsi_data, created_at) "
        "VALUES (?, ?, ?, 'T', 'msg', ?, ?, ?)",
        (SYMBOL, direction, SRC, json.dumps({"1m": 50}), json.dumps({}), format_db_time_ms(ms)),
    )


@pytest.fixture()
def seeded_market(monkeypatch):
    async def _noop_klines(*a, **k):
        return None
    async def _noop_funding(*a, **k):
        return None
    monkeypatch.setattr(be, "ensure_kline_range", _noop_klines)
    monkeypatch.setattr(be, "ensure_funding_range", _noop_funding)

    # 1m ve 5m bar'lari: buffer(once) + pencere + forward(sonra)
    _seed_klines("1", 60_000, START_MS - 220 * 60_000, END_MS)
    _seed_klines("5", 300_000, START_MS - 220 * 300_000, END_MS + MS_DAY)

    # pencere icinde 3 alarm
    _seed_alert(START_MS + 6 * 3_600_000)
    _seed_alert(START_MS + 12 * 3_600_000)
    _seed_alert(START_MS + 18 * 3_600_000)

    yield
    execute("DELETE FROM kline_cache WHERE symbol = ?", (SYMBOL,))
    execute("DELETE FROM kline_cache_meta WHERE symbol = ?", (SYMBOL,))
    execute("DELETE FROM alerts WHERE source_type = ? AND symbol = ?", (SRC, SYMBOL))


def _cfg():
    return {
        "enabledRules": ["rule_01_extreme_rsi"],
        "longMinScore": 0, "shortMinScore": 0,   # skor 0 -> her sinyal long olur
        "tpPercent": 5, "slPercent": 5, "leverage": 1,
        "positionSizePct": 3, "maxPositions": 3, "signalSource": SRC,
    }


def _params():
    return {
        "strategyConfig": _cfg(),
        "initialBalance": 10000,
        "startMs": START_MS, "endMs": END_MS,
        "execTf": "5", "maxLookaheadDays": 1,
        "minInterval": "1", "maxSignals": 50000, "maxSymbols": 60,
    }


class TestRunBacktest:
    async def test_returns_valid_structure(self, seeded_market):
        res = await be.run_backtest(_params())
        assert set(res) >= {"metrics", "equityCurve", "trades", "coverage"}
        m = res["metrics"]
        assert set(m) >= {"trades", "totalPnl", "winRate", "profitFactor", "maxDrawdown", "calmar"}

    async def test_evaluates_seeded_alerts(self, seeded_market):
        res = await be.run_backtest(_params())
        # 3 alarm degerlendirildi
        assert res["coverage"]["evaluated"] == 3
        assert res["coverage"]["symbols"] == 1

    async def test_produces_trades(self, seeded_market):
        res = await be.run_backtest(_params())
        assert res["metrics"]["trades"] >= 1
        for t in res["trades"]:
            assert set(t) >= {"symbol", "side", "entryPrice", "exitPrice", "pnl", "exitReason"}
            assert t["symbol"] == SYMBOL
            assert t["side"] == "long"

    async def test_empty_when_no_matching_source(self, seeded_market):
        p = _params()
        p["strategyConfig"]["signalSource"] = "fr"  # seed'de fr alarm yok
        res = await be.run_backtest(p)
        assert res["metrics"]["trades"] == 0
        assert res["coverage"]["evaluated"] == 0

    async def test_maxpositions_one_caps_concurrent(self, seeded_market):
        p = _params()
        p["strategyConfig"]["maxPositions"] = 1
        res = await be.run_backtest(p)
        # tek eszamanli pozisyon: yine de sirayla birden fazla islem olabilir
        assert res["metrics"]["trades"] >= 1
