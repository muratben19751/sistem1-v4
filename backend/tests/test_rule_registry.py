"""app/strategies/rule_registry.py — kural kayit defteri."""
from app.strategies.rule_registry import (
    get_all_rule_keys,
    get_all_rule_names,
    get_rule,
    get_rules,
)

EXPECTED_COUNT = 27


class TestRegistry:
    def test_expected_rule_count(self):
        assert len(get_all_rule_keys()) == EXPECTED_COUNT

    def test_keys_unique(self):
        keys = get_all_rule_keys()
        assert len(keys) == len(set(keys))

    def test_keys_follow_naming(self):
        for k in get_all_rule_keys():
            assert k.startswith("rule_")

    def test_get_rules_none_returns_all(self):
        assert len(get_rules(None)) == EXPECTED_COUNT

    def test_get_rules_empty_returns_empty(self):
        assert get_rules([]) == []

    def test_get_rules_filters(self):
        subset = ["rule_01_extreme_rsi", "rule_13_conviction"]
        got = get_rules(subset)
        assert {r.key for r in got} == set(subset)

    def test_get_rules_ignores_unknown(self):
        got = get_rules(["rule_01_extreme_rsi", "does_not_exist"])
        assert [r.key for r in got] == ["rule_01_extreme_rsi"]

    def test_get_rule_known(self):
        r = get_rule("rule_13_conviction")
        assert r is not None and r.key == "rule_13_conviction"

    def test_get_rule_unknown_none(self):
        assert get_rule("nope") is None

    def test_all_rules_have_callable_evaluate(self):
        for r in get_rules(None):
            assert callable(r.evaluate)
            assert isinstance(r.name, str) and r.name

    def test_get_all_rule_names_structure(self):
        names = get_all_rule_names()
        assert len(names) == EXPECTED_COUNT
        for n in names:
            assert set(n) >= {"key", "name", "sources"}
