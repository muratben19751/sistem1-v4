"""tools/lean_oracle saf yardimcilari (run_backtest/LEAN kosmadan)."""
import sys
from pathlib import Path

import pytest

# tools/ paketini import yoluna ekle
_TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from lean_oracle import compare, export  # noqa: E402


class TestWindowParse:
    def test_days(self):
        assert export.parse_window_days("90d") == 90
        assert export.parse_window_days("30 d") == 30

    def test_invalid(self):
        with pytest.raises(ValueError):
            export.parse_window_days("3w")


class TestSymbolsParse:
    def test_topn(self):
        assert export.parse_symbols_arg("TOP10") == 10
        assert export.parse_symbols_arg("top5") == 5

    def test_all(self):
        assert export.parse_symbols_arg("ALL") == 500

    def test_invalid(self):
        with pytest.raises(ValueError):
            export.parse_symbols_arg("BTCUSDT")


class TestDeslip:
    def test_long_short_inverse(self):
        from app.core.config import config
        slip = config.paper.slippage / 100
        ref = 100.0
        assert export._deslip(ref * (1 + slip), "long") == pytest.approx(ref)
        assert export._deslip(ref * (1 - slip), "short") == pytest.approx(ref)


class TestParseStat:
    def test_numbers_and_units(self):
        assert compare.parse_stat("12.34%") == 12.34
        assert compare.parse_stat("$1,234.56") == 1234.56
        assert compare.parse_stat("1.23") == 1.23
        assert compare.parse_stat(5) == 5.0

    def test_none_like(self):
        assert compare.parse_stat(None) is None
        assert compare.parse_stat("N/A") is None
        assert compare.parse_stat("") is None


class TestRelPct:
    def test_basic(self):
        assert compare.rel_pct(100, 100) == 0.0
        assert compare.rel_pct(100, 110) == pytest.approx(9.0909, abs=1e-3)

    def test_zero_zero(self):
        assert compare.rel_pct(0, 0) == 0.0


class TestBuildRows:
    MY = {
        "trades": 100, "totalPnlPct": 50.0, "totalPnl": 5000.0, "winRate": 55.0,
        "maxDrawdown": 10.0, "sharpe": 4.0, "profitFactor": 2.0, "calmar": 5.0,
        "avgWin": 80.0, "avgLoss": 40.0,
    }

    def test_mechanical_pass_when_equal(self):
        lean = {"Total Trades": "100", "Win Rate": "55%"}
        rows = {r["metric"]: r for r in compare.build_rows(self.MY, lean, 10000)}
        assert rows["Total Trades"]["verdict"] == "PASS"
        assert rows["Win Rate %"]["verdict"] == "PASS"

    def test_mechanical_investigate_when_far(self):
        lean = {"Total Trades": "50"}  # mine 100 -> ~%66 sapma
        rows = {r["metric"]: r for r in compare.build_rows(self.MY, lean, 10000)}
        assert rows["Total Trades"]["verdict"] == "INVESTIGATE"

    def test_modeling_metrics_are_note(self):
        # Net Profit / Max Drawdown modelleme farki -> sapsa bile NOTE (olasi bug degil)
        lean = {"Net Profit": "10.0%", "Drawdown": "30%"}
        rows = {r["metric"]: r for r in compare.build_rows(self.MY, lean, 10000)}
        assert rows["Net Profit %"]["kind"] == "modeling"
        assert rows["Net Profit %"]["verdict"] == "NOTE"
        assert rows["Max Drawdown %"]["verdict"] == "NOTE"

    def test_definitional_always_note(self):
        lean = {"Sharpe Ratio": "2.0", "Profit-Loss Ratio": "2.0"}
        rows = {r["metric"]: r for r in compare.build_rows(self.MY, lean, 10000)}
        assert rows["Sharpe"]["kind"] == "definitional"
        assert rows["Sharpe"]["verdict"] == "NOTE"

    def test_missing_lean_value_na(self):
        rows = {r["metric"]: r for r in compare.build_rows(self.MY, {}, 10000)}
        assert rows["Total Trades"]["verdict"] == "N/A"


def _rows(win_rel, trade_rel=0.0):
    return [
        {"metric": "Win Rate %", "relPct": win_rel},
        {"metric": "Total Trades", "relPct": trade_rel},
    ]


class TestOverallVerdict:
    def test_pass_when_winrate_close(self):
        assert compare.overall_verdict(_rows(1.0))["verdict"] == "pass"

    def test_warn_when_winrate_mid(self):
        assert compare.overall_verdict(_rows(3.0))["verdict"] == "warn"

    def test_fail_when_winrate_far(self):
        assert compare.overall_verdict(_rows(8.0))["verdict"] == "fail"

    def test_none_when_no_winrate(self):
        assert compare.overall_verdict([{"metric": "Net Profit %", "relPct": 1.0}])["verdict"] == "none"

    def test_downgrade_to_warn_when_trades_far(self):
        # win-rate tutuyor ama islem sayisi cok sapmis -> warn'a iner
        out = compare.overall_verdict(_rows(1.0, trade_rel=20.0))
        assert out["verdict"] == "warn"
        assert out["winRateRel"] == 1.0 and out["tradeRel"] == 20.0


class TestParityIndex:
    def test_writes_index_entry(self, tmp_path):
        export_dir = tmp_path / "ATR_Breakout_30d"
        export_dir.mkdir()
        meta = {"strategy": "ATR_Breakout", "window": "30d"}
        compare._update_parity_index(export_dir, meta, _rows(1.0, 5.0), "lean")
        import json as _json
        idx = _json.loads((tmp_path / "parity_index.json").read_text())
        assert idx["ATR_Breakout"]["verdict"] == "pass"
        assert idx["ATR_Breakout"]["source"] == "lean"
        assert idx["ATR_Breakout"]["runId"] == "ATR_Breakout_30d"
        assert "checkedAt" in idx["ATR_Breakout"]

    def test_upsert_keeps_other_strategies(self, tmp_path):
        d1 = tmp_path / "A_run"; d1.mkdir()
        d2 = tmp_path / "B_run"; d2.mkdir()
        compare._update_parity_index(d1, {"strategy": "A", "window": "30d"}, _rows(1.0), "lean")
        compare._update_parity_index(d2, {"strategy": "B", "window": "30d"}, _rows(8.0), "lean")
        import json as _json
        idx = _json.loads((tmp_path / "parity_index.json").read_text())
        assert set(idx) == {"A", "B"}
        assert idx["A"]["verdict"] == "pass" and idx["B"]["verdict"] == "fail"


class TestRenderMarkdown:
    def test_contains_table_and_verdicts(self):
        my = TestBuildRows.MY
        lean = {"Total Trades": "100", "Net Profit": "50%", "Win Rate": "55%", "Drawdown": "10%",
                "Sharpe Ratio": "2.0", "Profit-Loss Ratio": "2.0"}
        rows = compare.build_rows(my, lean, 10000)
        md = compare.render_markdown({"strategy": "X", "window": "90d", "leanSource": "stub",
                                      "initialBalance": 10000}, rows)
        assert "Parite Raporu" in md
        assert "| Total Trades |" in md
        assert "STUB" in md
