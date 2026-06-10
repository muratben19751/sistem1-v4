"""FastAPI route'lari — kimlik dogrulama kapisi + DB-guvenli uctan uca (ASGI, ag yok)."""
import json
import os

TOKEN = os.environ["AUTH_TOKEN"]


class TestHealth:
    async def test_health_no_auth(self, anon_client):
        r = await anon_client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestTradeMetrics:
    async def test_returns_24h_aggregate(self, client, db):
        account = db.execute(
            "INSERT INTO accounts (name, type, engine) VALUES ('Metrics Test', 'paper', 'paper')"
        )
        account_id = account.lastrowid
        try:
            db.execute(
                """
                INSERT INTO trades (
                  account_id, symbol, side, size, entry_price, exit_price, leverage,
                  pnl, fee, status, opened_at, closed_at
                ) VALUES (?, 'HUSDT', 'long', 10, 1, 1.2, 2, 1.5, 0.2, 'closed',
                          datetime('now', '-2 hours'), datetime('now', '-1 hour'))
                """,
                (account_id,),
            )
            db.commit()
            r = await client.get(f"/api/trades/metrics?hours=24&accountId={account_id}")
            assert r.status_code == 200
            body = r.json()
            assert body["closedTrades"] == 1
            assert body["realizedPnl"] == 1.5
            assert body["fees"] == 0.2
        finally:
            db.execute("DELETE FROM trades WHERE account_id = ?", (account_id,))
            db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            db.commit()


class TestAuthGate:
    async def test_protected_route_requires_auth(self, anon_client):
        r = await anon_client.get("/api/accounts")
        assert r.status_code == 401

    async def test_protected_route_with_bearer(self, client):
        r = await client.get("/api/accounts")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_unknown_api_path_returns_json_404(self, client):
        r = await client.get("/api/does-not-exist")
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("application/json")


class TestLoginFlow:
    async def test_login_wrong_token(self, anon_client):
        r = await anon_client.post("/api/auth/login", json={"token": "definitely-wrong-token-xx"})
        assert r.status_code == 401

    async def test_login_right_token_sets_cookie(self, anon_client):
        r = await anon_client.post("/api/auth/login", json={"token": TOKEN})
        assert r.status_code == 200
        assert r.json().get("success") is True
        assert "sistem1_auth" in r.cookies

    async def test_login_missing_token(self, anon_client):
        r = await anon_client.post("/api/auth/login", json={})
        assert r.status_code == 401


class TestAuthStatus:
    async def test_status_authenticated_with_bearer(self, client):
        r = await client.get("/api/auth/status")
        assert r.status_code == 200
        assert r.json()["authenticated"] is True

    async def test_status_anon_false(self, anon_client):
        r = await anon_client.get("/api/auth/status")
        assert r.status_code == 200
        assert r.json()["authenticated"] is False

    async def test_logout(self, client):
        r = await client.post("/api/auth/logout")
        assert r.status_code == 200
        assert r.json().get("success") is True


class TestAccountsContent:
    async def test_lists_seeded_accounts(self, client):
        r = await client.get("/api/accounts")
        assert r.status_code == 200
        data = r.json()
        names = {a["name"] for a in data}
        assert {"Conservative", "Aggressive", "Scalper"} <= names

    async def test_delete_account_removes_exchange_order_fk_rows(self, client, db):
        account = db.execute(
            "INSERT INTO accounts (name, type, engine) VALUES ('Delete FK Test', 'paper', 'paper')"
        )
        account_id = int(account.lastrowid)
        db.execute("INSERT INTO bot_configs (account_id) VALUES (?)", (account_id,))
        db.execute(
            """
            INSERT INTO exchange_orders (
              account_id, symbol, side, action, order_link_id, status
            ) VALUES (?, 'BTCUSDT', 'long', 'open', ?, 'failed')
            """,
            (account_id, f"delete-fk-{account_id}"),
        )
        db.commit()

        response = await client.delete(f"/api/accounts/{account_id}")

        assert response.status_code == 200
        assert db.execute("SELECT 1 FROM accounts WHERE id = ?", (account_id,)).fetchone() is None
        assert db.execute(
            "SELECT 1 FROM exchange_orders WHERE account_id = ?",
            (account_id,),
        ).fetchone() is None


class TestOptimizerDeploy:
    async def test_new_deployment_enables_default_drawdown_guard(self, client, db, monkeypatch):
        from app.routes import optimizer

        config = {
            "enabledRules": ["rule_01"],
            "longMinScore": 4,
            "shortMinScore": -4,
            "leverage": 2,
            "maxPositions": 3,
            "tpPercent": 5,
            "slPercent": 3,
            "signalSource": "all",
            "positionSizePct": 2,
        }
        row = db.execute(
            "INSERT INTO optimizer_results (strategy_name, config_json) VALUES (?, ?)",
            ("Deploy Drawdown Test", json.dumps(config)),
        )
        result_id = int(row.lastrowid)
        db.commit()
        monkeypatch.setattr(optimizer, "start_bot", lambda _account_id: {"success": True})

        account_id = None
        try:
            response = await client.post("/api/optimizer/deploy", json={"resultId": result_id})
            assert response.status_code == 200
            account_id = int(response.json()["accountId"])
            cfg = db.execute(
                "SELECT max_drawdown, max_drawdown_enabled FROM bot_configs WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            assert (cfg["max_drawdown"], cfg["max_drawdown_enabled"]) == (50, 1)
        finally:
            if account_id is not None:
                db.execute("DELETE FROM paper_wallets WHERE account_id = ?", (account_id,))
                db.execute("DELETE FROM bot_configs WHERE account_id = ?", (account_id,))
                db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            db.execute("DELETE FROM optimizer_results WHERE id = ?", (result_id,))
            db.commit()


class TestLeanOracleRunValidation:
    async def test_rejects_window_not_supported_by_exporter(self, client):
        response = await client.post(
            "/api/lean-oracle/run",
            json={"strategy": "ATR_Breakout", "window": "12m", "symbols": "TOP10"},
        )
        assert response.status_code == 400
        assert response.json()["error"] == "gecersiz window (orn. 90d)"

    async def test_rejects_symbols_not_supported_by_exporter(self, client):
        response = await client.post(
            "/api/lean-oracle/run",
            json={"strategy": "ATR_Breakout", "window": "90d", "symbols": "BTCUSDT,ETHUSDT"},
        )
        assert response.status_code == 400
        assert response.json()["error"] == "gecersiz symbols (TOP10 veya ALL)"
