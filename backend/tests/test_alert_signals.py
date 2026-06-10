"""app/services/alert_signals.py — kaynak eslemesi + son alarm sorgusu (DB)."""
import json

import pytest

from app.core.time import format_db_time_ms, now_ms
from app.db.database import execute
from app.services.alert_signals import (
    get_recent_alerts,
    get_source_types,
    is_alert_only,
    needs_scanner,
)


class TestSourceTypes:
    def test_known_singles(self):
        assert get_source_types("hammer") == ["hammer"]
        assert get_source_types("fr") == ["fr"]
        assert get_source_types("sniper") == ["4s_sniper", "sniper"]

    def test_combos(self):
        assert get_source_types("hammer+sniper+fr") == ["hammer", "4s_sniper", "sniper", "fr"]

    def test_all(self):
        assert set(get_source_types("all")) == {"hammer", "4s_sniper", "sniper", "fr", "m1_a", "v3_a"}

    def test_unknown_empty(self):
        assert get_source_types("nope") == []


class TestScannerHelpers:
    def test_needs_scanner(self):
        assert needs_scanner("scanner+hammer") is True
        assert needs_scanner("all") is True
        assert needs_scanner("hammer") is False

    def test_is_alert_only(self):
        assert is_alert_only("hammer+sniper+fr") is True
        assert is_alert_only("all") is False


class TestGetRecentAlerts:
    SRC = "test_alertsig_src"

    @pytest.fixture(autouse=True)
    def _cleanup(self):
        yield
        execute("DELETE FROM alerts WHERE source_type = ?", (self.SRC,))

    def _insert(self, symbol, direction, ms_ago=0, rsi=None):
        ts = format_db_time_ms(now_ms() - ms_ago)
        execute(
            "INSERT INTO alerts (symbol, direction, source_type, signal_type, raw_message, rsi_data, created_at) "
            "VALUES (?, ?, ?, 'T', 'msg', ?, ?)",
            (symbol, direction, self.SRC, json.dumps(rsi) if rsi else None, ts),
        )

    def test_returns_fresh_alert(self):
        self._insert("BTCUSDT", "UP", rsi={"1m": 25})
        out = get_recent_alerts([self.SRC], 60)
        assert len(out) == 1
        assert out[0]["symbol"] == "BTCUSDT"
        assert out[0]["rsiData"] == {"1m": 25}

    def test_dedup_same_symbol_direction_source(self):
        self._insert("ETHUSDT", "UP")
        self._insert("ETHUSDT", "UP")
        out = get_recent_alerts([self.SRC], 60)
        assert len([a for a in out if a["symbol"] == "ETHUSDT"]) == 1

    def test_distinct_directions_kept(self):
        self._insert("XRPUSDT", "UP")
        self._insert("XRPUSDT", "DOWN")
        out = get_recent_alerts([self.SRC], 60)
        dirs = {a["direction"] for a in out if a["symbol"] == "XRPUSDT"}
        assert dirs == {"UP", "DOWN"}

    def test_freshness_cutoff_excludes_old(self):
        self._insert("OLDUSDT", "UP", ms_ago=120 * 60_000)  # 120 dk once
        out = get_recent_alerts([self.SRC], 60)  # 60 dk pencere
        assert not any(a["symbol"] == "OLDUSDT" for a in out)
