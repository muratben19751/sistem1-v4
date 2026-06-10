"""app/core/time.py — DB zaman bicimleme/ayristirma yardimcilari."""
import math

import pytest

from app.core.time import format_db_time_ms, now_ms, parse_db_time_ms


class TestFormatDbTimeMs:
    def test_epoch(self):
        assert format_db_time_ms(0) == "1970-01-01T00:00:00.000Z"

    def test_known_ms_with_millis(self):
        # 2021-01-01T00:00:00.123Z
        ms = 1609459200123
        assert format_db_time_ms(ms) == "2021-01-01T00:00:00.123Z"

    def test_always_zulu_suffix(self):
        assert format_db_time_ms(1700000000000).endswith("Z")

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_raises(self, bad):
        with pytest.raises(ValueError):
            format_db_time_ms(bad)


class TestParseDbTimeMs:
    def test_none_is_nan(self):
        assert math.isnan(parse_db_time_ms(None))

    def test_empty_is_nan(self):
        assert math.isnan(parse_db_time_ms("   "))

    def test_numeric_passthrough(self):
        assert parse_db_time_ms(1234.5) == 1234.5
        assert parse_db_time_ms(42) == 42.0

    def test_iso_z_format(self):
        assert parse_db_time_ms("2021-01-01T00:00:00.000Z") == pytest.approx(1609459200000.0)

    def test_iso_without_tz_assumed_utc(self):
        assert parse_db_time_ms("2021-01-01T00:00:00") == pytest.approx(1609459200000.0)

    def test_sqlite_space_format(self):
        assert parse_db_time_ms("2021-01-01 00:00:00") == pytest.approx(1609459200000.0)

    def test_garbage_is_nan(self):
        assert math.isnan(parse_db_time_ms("not-a-date"))


class TestRoundTrip:
    @pytest.mark.parametrize("ms", [0, 1609459200000, 1700000000123, 1735689600000])
    def test_format_then_parse(self, ms):
        assert parse_db_time_ms(format_db_time_ms(ms)) == pytest.approx(float(ms))


class TestNowMs:
    def test_finite_and_positive(self):
        v = now_ms()
        assert math.isfinite(v) and v > 1_600_000_000_000
