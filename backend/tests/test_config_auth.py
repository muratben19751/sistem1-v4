"""app/core/config.py + app/middleware/auth.py — yapilandirma ve kimlik dogrulama mantigi."""
import os

from app.core.config import config
from app.middleware import auth

TOKEN = os.environ["AUTH_TOKEN"]


class TestConfigDefaults:
    def test_port_and_paper(self):
        assert config.port == 3500
        assert config.paper.initial_balance == 10000
        assert config.paper.taker_fee == 0.055

    def test_auth_token_min_length_floor(self):
        assert config.auth_token_min_length >= 24


class TestAuthTokenValidation:
    def test_valid_token(self):
        assert auth.is_auth_token_valid(TOKEN) is True

    def test_wrong_token(self):
        assert auth.is_auth_token_valid("wrong-token-value-here-1234") is False

    def test_none_and_empty(self):
        assert auth.is_auth_token_valid(None) is False
        assert auth.is_auth_token_valid("") is False

    def test_min_length_floor(self):
        assert auth.MIN_AUTH_TOKEN_LENGTH >= 24


class TestAuthDisable:
    def test_disabled_when_flag_set_non_prod(self, monkeypatch):
        monkeypatch.setenv("DISABLE_AUTH", "true")
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("NODE_ENV", raising=False)
        assert auth.is_auth_disabled() is True
        # devre disiyken her token (None dahil) gecerli sayilir
        assert auth.is_auth_token_valid(None) is True

    def test_not_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("DISABLE_AUTH", raising=False)
        assert auth.is_auth_disabled() is False

    def test_disable_rejected_in_production(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        assert auth.is_auth_disabled() is False  # prod'da asla devre disi


class TestCookieKwargs:
    class _Req:
        def __init__(self, scheme="http", proto=None):
            from types import SimpleNamespace
            self.url = SimpleNamespace(scheme=scheme)
            self.headers = {"x-forwarded-proto": proto} if proto else {}

    def test_http_not_secure(self):
        kw = auth.cookie_kwargs(self._Req("http"))
        assert kw["secure"] is False
        assert kw["httponly"] is True
        assert kw["samesite"] == "lax"

    def test_https_secure(self):
        assert auth.cookie_kwargs(self._Req("https"))["secure"] is True

    def test_forwarded_proto_secure(self):
        assert auth.cookie_kwargs(self._Req("http", "https"))["secure"] is True
