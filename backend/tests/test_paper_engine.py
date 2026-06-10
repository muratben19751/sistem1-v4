"""app/engines/paper_engine.py — emir dogrulama + tam ac/kapa dongusu (fiyat mock'lu)."""
import pytest

from app.engines import paper_engine as pe_mod
from app.engines.paper_engine import PaperEngine
from app.engines.trade_engine import OrderParams

engine = PaperEngine()


@pytest.fixture()
def fixed_price(monkeypatch):
    async def _fake_price(symbol):
        return 100.0
    monkeypatch.setattr(pe_mod, "get_last_price", _fake_price)
    return 100.0


def _op(account_id, symbol="TESTUSDT", side="long", size=1.0, leverage=2, **kw):
    return OrderParams(account_id=account_id, symbol=symbol, side=side, size=size, leverage=leverage, **kw)


class TestPlaceOrderValidation:
    async def test_invalid_account(self, seeded_account):
        assert (await engine.place_order(_op(0))).error == "Invalid account"
        assert (await engine.place_order(_op(-1))).error == "Invalid account"

    async def test_invalid_symbol(self, seeded_account):
        r = await engine.place_order(_op(seeded_account, symbol="BTC"))
        assert r.success is False and r.error == "Invalid symbol"

    async def test_invalid_side(self, seeded_account):
        r = await engine.place_order(_op(seeded_account, side="buy"))
        assert r.error == "Invalid side"

    async def test_invalid_leverage(self, seeded_account):
        assert (await engine.place_order(_op(seeded_account, leverage=0))).error == "Invalid leverage"
        assert (await engine.place_order(_op(seeded_account, leverage=200))).error == "Invalid leverage"

    async def test_invalid_size(self, seeded_account):
        assert (await engine.place_order(_op(seeded_account, size=0))).error == "Invalid size"
        assert (await engine.place_order(_op(seeded_account, size=-5))).error == "Invalid size"
        assert (await engine.place_order(_op(seeded_account, size=float("nan")))).error == "Invalid size"


class TestOpenCloseCycle:
    async def test_full_long_cycle(self, seeded_account, fixed_price):
        sym = "CYCLEUSDT"
        bal0 = (await engine.get_balance(seeded_account)).balance

        res = await engine.place_order(_op(seeded_account, symbol=sym, side="long", size=1, leverage=2, tp_percent=5, sl_percent=3))
        assert res.success is True
        assert res.fill_price == pytest.approx(100.0 * (1 + 0.05 / 100))  # long slippage yukari

        positions = await engine.get_positions(seeded_account)
        assert any(p.symbol == sym for p in positions)

        bal1 = (await engine.get_balance(seeded_account)).balance
        assert bal1 < bal0  # margin+fee dusuldu

        close = await engine.close_position(seeded_account, sym, "long", fill_price_override=100.0)
        assert close.success is True
        assert isinstance(close.pnl, float)

        positions2 = await engine.get_positions(seeded_account)
        assert not any(p.symbol == sym for p in positions2)

    async def test_duplicate_position_rejected(self, seeded_account, fixed_price):
        sym = "DUPUSDT"
        r1 = await engine.place_order(_op(seeded_account, symbol=sym))
        assert r1.success is True
        r2 = await engine.place_order(_op(seeded_account, symbol=sym))
        assert r2.success is False and "already exists" in r2.error
        await engine.close_position(seeded_account, sym, "long", fill_price_override=100.0)

    async def test_insufficient_balance(self, seeded_account, fixed_price):
        r = await engine.place_order(_op(seeded_account, symbol="HUGEUSDT", size=1e9, leverage=1))
        assert r.success is False and r.error == "Insufficient balance"

    async def test_close_nonexistent(self, seeded_account, fixed_price):
        r = await engine.close_position(seeded_account, "NOPEUSDT", "long", fill_price_override=100.0)
        assert r.success is False and r.error == "Position not found"


class TestBalance:
    async def test_unknown_account_zero(self):
        b = await engine.get_balance(999999)
        assert b.balance == 0 and b.equity == 0
