"""app/agents/risk.py — pozisyon risk degerlendirmesi (paper yolu, ag yok)."""
import pytest

from app.agents.risk import evaluate_risk


def _params(account_id, **kw):
    base = {"accountId": account_id, "symbol": "RISKUSDT", "side": "long", "score": 5, "price": 100.0}
    base.update(kw)
    return base


class TestEvaluateRisk:
    async def test_account_not_found(self):
        out = await evaluate_risk(_params(999999))
        assert out["approved"] is False
        assert out["reason"] == "Account not found"

    async def test_long_score_below_min_rejected(self, seeded_account):
        # seed long_min_score = 4
        out = await evaluate_risk(_params(seeded_account, side="long", score=1))
        assert out["approved"] is False
        assert "min long" in out["reason"]

    async def test_short_score_above_min_rejected(self, seeded_account):
        # seed short_min_score = -4; score 0 > -4 -> red
        out = await evaluate_risk(_params(seeded_account, side="short", score=0))
        assert out["approved"] is False
        assert "min short" in out["reason"]

    async def test_skip_score_check_bypasses_gate(self, seeded_account):
        out = await evaluate_risk(_params(seeded_account, side="long", score=0, skipScoreCheck=True, symbol="SKIPUSDT"))
        assert out["approved"] is True

    async def test_invalid_price_rejected(self, seeded_account):
        out = await evaluate_risk(_params(seeded_account, price=0, symbol="BADPXUSDT"))
        assert out["approved"] is False
        assert "price" in out["reason"].lower()

    async def test_happy_path_approved(self, seeded_account):
        out = await evaluate_risk(_params(seeded_account, side="long", score=5, symbol="OKUSDT"))
        assert out["approved"] is True
        assert out["size"] > 0
        assert out["leverage"] > 0

    async def test_requested_leverage_exceeds_config_rejected(self, seeded_account):
        out = await evaluate_risk(_params(seeded_account, requestedLeverage=125, symbol="LEVUSDT"))
        assert out["approved"] is False
        assert "leverage" in out["reason"].lower()
