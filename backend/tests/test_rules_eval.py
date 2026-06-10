"""Kural degerlendirme — her kural sozlesmeye uymali; rule_01 ozel skorlama."""
import pytest

from app.strategies.rules.rule_interface import MarketData, RuleResult, side_for
from app.strategies.rule_registry import get_rule, get_rules


class TestSideFor:
    def test_long_short_neutral(self):
        assert side_for(3) == "long"
        assert side_for(-2) == "short"
        assert side_for(0) == "neutral"


class TestAllRulesContract:
    @pytest.mark.parametrize("rule", get_rules(None), ids=lambda r: r.key)
    def test_baseline_marketdata_returns_valid_result(self, rule):
        # Gercekci minimum girdi (scanner her zaman ticker doldurur) ile hicbir kural
        # patlamadan gecerli RuleResult donmeli.
        md = MarketData(symbol="BTCUSDT", ticker={"price24hPcnt": "0.0", "lastPrice": "100"})
        res = rule.evaluate(md)
        assert isinstance(res, RuleResult)
        assert res.side in ("long", "short", "neutral")
        assert isinstance(res.score, (int, float))
        assert res.side == side_for(res.score)


class TestRule01ExtremeRsi:
    def _md(self, rsi1, rsi5, srsi1, srsi5):
        return MarketData(
            symbol="BTCUSDT",
            rsi={"1": rsi1, "5": rsi5},
            stoch_rsi={"1": {"k": srsi1}, "5": {"k": srsi5}},
        )

    def test_extreme_oversold_long_3(self):
        r = get_rule("rule_01_extreme_rsi").evaluate(self._md(15, 25, 15, 25))
        assert r.score == 3 and r.side == "long"

    def test_oversold_long_2(self):
        r = get_rule("rule_01_extreme_rsi").evaluate(self._md(15, 60, 15, 60))
        assert r.score == 2 and r.side == "long"

    def test_extreme_overbought_short_minus3(self):
        r = get_rule("rule_01_extreme_rsi").evaluate(self._md(85, 75, 85, 75))
        assert r.score == -3 and r.side == "short"

    def test_overbought_short_minus2(self):
        r = get_rule("rule_01_extreme_rsi").evaluate(self._md(85, 50, 85, 50))
        assert r.score == -2 and r.side == "short"

    def test_neutral_zone(self):
        r = get_rule("rule_01_extreme_rsi").evaluate(self._md(50, 50, 50, 50))
        assert r.score == 0 and r.side == "neutral"

    def test_defaults_to_neutral_when_missing(self):
        r = get_rule("rule_01_extreme_rsi").evaluate(MarketData(symbol="BTCUSDT"))
        assert r.score == 0
