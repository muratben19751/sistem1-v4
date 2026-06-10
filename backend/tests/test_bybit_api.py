"""app/services/bybit_api.py — saf yardimcilar + mock'lu request (ag yok)."""
import pytest

from app.services import bybit_api as api


class TestToFinite:
    def test_valid(self):
        assert api.to_finite("1.5") == 1.5
        assert api.to_finite(3) == 3.0

    def test_fallback_on_bad(self):
        assert api.to_finite("x", 7.0) == 7.0
        assert api.to_finite(None, -1) == -1
        assert api.to_finite(float("inf"), 0) == 0
        assert api.to_finite(float("nan"), 0) == 0


class TestNormalizeSymbol:
    def test_strip_upper(self):
        assert api.normalize_symbol("  btcusdt ") == "BTCUSDT"

    def test_none(self):
        assert api.normalize_symbol(None) == ""


class TestKlineTtl:
    def test_known(self):
        assert api.kline_ttl("15") == 60000
        assert api.kline_ttl("D") == 1800000

    def test_default(self):
        assert api.kline_ttl("999") == api.KLINE_CACHE_TTL


class TestMsgClassifiers:
    def test_rate_limit(self):
        assert api._is_rate_limit_msg("Too many visits!") is True
        assert api._is_rate_limit_msg("rate limit exceeded") is True
        assert api._is_rate_limit_msg("ok") is False
        assert api._is_rate_limit_msg(None) is False

    def test_invalid_symbol(self):
        assert api._is_invalid_symbol_msg("Symbol Invalid") is True
        assert api._is_invalid_symbol_msg("params error") is True
        assert api._is_invalid_symbol_msg("fine") is False


class TestInvalidSymbolCache:
    async def test_empty_symbol_false(self):
        assert await api.is_tradable_linear_symbol("") is False

    async def test_marked_invalid_short_circuits(self, monkeypatch):
        async def _boom():
            raise AssertionError("ag cagrilmamali")
        monkeypatch.setattr(api, "get_tradable_linear_symbols", _boom)
        api.mark_invalid_symbol("ZZZUSDT")
        assert await api.is_tradable_linear_symbol("ZZZUSDT") is False


class _Resp:
    def __init__(self, status=200, payload=None, reason="OK"):
        self.status_code = status
        self._payload = payload or {}
        self.reason_phrase = reason

    def json(self):
        return self._payload


class _Client:
    def __init__(self, resp):
        self._resp = resp

    async def get(self, url, params=None):
        return self._resp


@pytest.fixture()
def no_rate_limit(monkeypatch):
    async def _noop():
        return None
    monkeypatch.setattr(api, "_rate_limit", _noop)


def _patch_client(monkeypatch, resp):
    monkeypatch.setattr(api, "_get_client", lambda: _Client(resp))


class TestRequest:
    async def test_success_returns_result(self, monkeypatch, no_rate_limit):
        _patch_client(monkeypatch, _Resp(payload={"retCode": 0, "result": {"x": 1}}))
        out = await api.request("/v5/market/tickers")
        assert out == {"x": 1}

    async def test_non_zero_retcode_raises(self, monkeypatch, no_rate_limit):
        _patch_client(monkeypatch, _Resp(payload={"retCode": 10001, "retMsg": "boom"}))
        with pytest.raises(RuntimeError):
            await api.request("/v5/market/tickers")

    async def test_http_error_raises(self, monkeypatch, no_rate_limit):
        _patch_client(monkeypatch, _Resp(status=500, reason="Server Error"))
        with pytest.raises(RuntimeError):
            await api.request("/v5/market/tickers")
