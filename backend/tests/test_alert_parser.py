"""app/services/alert_parser.py — telegram alarm metni ayristirma."""
import math

from app.services.alert_parser import (
    derive_fr_direction,
    detect_source_type,
    extract_explicit_direction,
    get_alert_parse_failure_reason,
    parse_alert,
    parse_timeframe_values,
)

SNIPER_MSG = (
    "#BTCUSDT LONG\n"
    "Strategy: NW Sniper\n"
    "Boost Value: 2.5%\n"
    "Current Price: 50000\n"
    "RSI: 1m: 25 5m: 30\n"
    "SRSI: 1m: 15 5m: 20\n"
)

FR_MSG = (
    "#ETHUSDT\n"
    "Funding Rate: -0.05\n"
    "Time Remaining: 02:30:00\n"
)


class TestDetectSourceType:
    def test_explicit_sources(self):
        assert detect_source_type("x", "fr") == "fr"
        assert detect_source_type("x", "hammer") == "hammer"
        assert detect_source_type("x", "m1_a") == "m1_a"
        assert detect_source_type("x", "m1a") == "m1_a"
        assert detect_source_type("x", "v3_a") == "v3_a"
        assert detect_source_type("x", "sniper") == "4s_sniper"
        assert detect_source_type("x", "nw") == "4s_sniper"

    def test_local_suffix_stripped(self):
        assert detect_source_type("x", "fr_local") == "fr"

    def test_strategy_marker_implies_sniper(self):
        assert detect_source_type("Strategy: foo", None) == "4s_sniper"

    def test_unknown(self):
        assert detect_source_type("just text", None) == "unknown"


class TestDirection:
    def test_words(self):
        assert extract_explicit_direction("going LONG now") == "UP"
        assert extract_explicit_direction("SHORT setup") == "DOWN"
        assert extract_explicit_direction("BUY") == "UP"
        assert extract_explicit_direction("SELL") == "DOWN"

    def test_none_when_absent(self):
        assert extract_explicit_direction("no direction here") is None

    def test_emoji_priority(self):
        assert extract_explicit_direction("\U0001F534 SELL") == "DOWN"
        assert extract_explicit_direction("\U0001F7E2 BUY") == "UP"


class TestFrDirection:
    def test_negative_is_up(self):
        assert derive_fr_direction(-0.05) == "UP"

    def test_positive_is_down(self):
        assert derive_fr_direction(0.05) == "DOWN"

    def test_neutral_band_none(self):
        assert derive_fr_direction(0.0) is None
        assert derive_fr_direction(0.001) is None

    def test_invalid_none(self):
        assert derive_fr_direction(None) is None
        assert derive_fr_direction(float("nan")) is None


class TestParseTimeframeValues:
    def test_basic(self):
        assert parse_timeframe_values("1m: 25 5m: 30") == {"1m": 25, "5m": 30}

    def test_decimals_with_colon(self):
        out = parse_timeframe_values("1h: 1.5 4h: 2")
        assert out["1h"] == 1.5
        assert out["4h"] == 2

    def test_equals_and_minus_stripped_by_cleaner(self):
        # _CLEAN_JUNK_REGEX '=' ve '-' karakterlerini siler -> ayirici/sign kaybolur
        assert parse_timeframe_values("1h = -1.5") == {}

    def test_empty(self):
        assert parse_timeframe_values("no values") == {}


class TestParseAlert:
    def test_sniper_message(self):
        out = parse_alert(SNIPER_MSG, "sniper")
        assert out is not None
        assert out["symbol"] == "BTCUSDT"
        assert out["direction"] == "UP"
        assert out["sourceType"] == "4s_sniper"
        assert out["signalType"] == "NW Sniper"
        assert out["rsi"] == {"1m": 25, "5m": 30}
        assert out["srsi"] == {"1m": 15, "5m": 20}
        assert out["price"] == 50000
        assert out["boostValue"] == 2.5
        assert isinstance(out["stars"], int)

    def test_fr_message(self):
        out = parse_alert(FR_MSG, "fr")
        assert out is not None
        assert out["symbol"] == "ETHUSDT"
        assert out["sourceType"] == "fr"
        assert out["direction"] == "UP"  # negatif FR -> UP
        assert out["fundingRate"] == -0.05
        assert out["timeRemaining"] == "02:30:00"
        assert out["signalType"] == "FR_UPDATE"

    def test_no_symbol_returns_none(self):
        assert parse_alert("hello world LONG", "sniper") is None

    def test_no_direction_returns_none(self):
        assert parse_alert("#BTCUSDT just chatter", "sniper") is None

    def test_symbol_uppercased(self):
        out = parse_alert("#btcusdt LONG", "sniper")
        assert out["symbol"] == "BTCUSDT"


class TestFailureReason:
    def test_empty(self):
        assert get_alert_parse_failure_reason("") == "empty_message"
        assert get_alert_parse_failure_reason("   ") == "empty_message"

    def test_symbol_not_found(self):
        assert get_alert_parse_failure_reason("hello world") == "symbol_not_found"

    def test_direction_not_found(self):
        assert get_alert_parse_failure_reason("#BTCUSDT chatter", "sniper") == "direction_not_found"

    def test_unknown_format_when_parseable(self):
        assert get_alert_parse_failure_reason("#BTCUSDT LONG extra", "sniper") == "unknown_format"
