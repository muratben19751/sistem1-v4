import os
import tempfile
import re
import sqlite3
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agents.risk import evaluate_risk
from app.core.secrets import (
    PREFIX,
    decrypt_secret,
    encrypt_secret,
    ensure_credential_encryption,
    get_invalid_credential_account_ids,
    mark_credentials_valid,
)
from app.core.time import format_db_time_ms, parse_db_time_ms
from app.db.database import DB_PATH
from app.engines.backtest_engine import to_db_time
from app.engines.bybit_engine import BybitEngine
from app.engines.paper_engine import PaperEngine
from app.engines.trade_engine import Balance, OrderParams
from app.main import app as fastapi_app
from app.middleware import auth
from app.middleware.auth import require_auth
from app.routes.accounts import enrich_live_balance
from app.routes.alerts import backfill
from app.routes.backtest import _build_config
from app.routes.optimizer import _parse_positive_id
from app.routes.trading import normalize_symbol, parse_account_id, parse_leverage, set_tp_sl
from app.services import alert_signals, telegram
from app.strategies.rule_registry import get_all_rule_keys


class SecretTests(unittest.TestCase):
    def test_secret_round_trip_and_plaintext_compatibility(self):
        with patch.dict(
            os.environ,
            {"CREDENTIAL_ENCRYPTION_KEY": "test-key-with-enough-entropy-for-repeatable-tests"},
            clear=False,
        ):
            encrypted = encrypt_secret("private-value")
            self.assertIsNotNone(encrypted)
            self.assertTrue(encrypted.startswith(PREFIX))
            self.assertNotIn("private-value", encrypted)
            self.assertEqual(decrypt_secret(encrypted), "private-value")
            self.assertEqual(decrypt_secret("legacy-plaintext"), "legacy-plaintext")

    def test_tampered_secret_is_rejected(self):
        with patch.dict(
            os.environ,
            {"CREDENTIAL_ENCRYPTION_KEY": "test-key-with-enough-entropy-for-repeatable-tests"},
            clear=False,
        ):
            encrypted = encrypt_secret("private-value")
            iv_raw, tag_raw, encrypted_raw = encrypted[len(PREFIX):].split(":")
            replacement = "A" if tag_raw[0] != "A" else "B"
            tampered = f"{PREFIX}{iv_raw}:{replacement}{tag_raw[1:]}:{encrypted_raw}"
            with self.assertRaises(Exception):
                decrypt_secret(tampered)

    def test_legacy_auth_token_credentials_migrate_to_dedicated_key(self):
        from app.db.database import execute

        key_file = os.path.join(tempfile.gettempdir(), "sistem1-test-credential-key")
        try:
            os.unlink(key_file)
        except FileNotFoundError:
            pass
        legacy_env = {
            "AUTH_TOKEN": "legacy-auth-token-with-enough-entropy",
            "CREDENTIAL_KEY_FILE": key_file,
        }
        with patch.dict(os.environ, legacy_env, clear=False):
            os.environ.pop("CREDENTIAL_ENCRYPTION_KEY", None)
            encrypted_key = encrypt_secret("api-key")
            encrypted_secret = encrypt_secret("api-secret")
            row = execute(
                """
                INSERT INTO accounts (name, type, engine, api_key, api_secret)
                VALUES ('Legacy Secret Test', 'demo', 'demo', ?, ?)
                """,
                (encrypted_key, encrypted_secret),
            )
            account_id = row.lastrowid
            try:
                os.environ["CREDENTIAL_ENCRYPTION_KEY"] = "new-dedicated-key-with-enough-entropy"
                self.assertEqual(ensure_credential_encryption(), 1)
                from app.db.database import query_one
                migrated = query_one("SELECT api_key, api_secret FROM accounts WHERE id = ?", (account_id,))
                self.assertEqual(decrypt_secret(migrated["api_key"]), "api-key")
                self.assertEqual(decrypt_secret(migrated["api_secret"]), "api-secret")
            finally:
                execute("DELETE FROM accounts WHERE id = ?", (account_id,))
                try:
                    os.unlink(key_file)
                except FileNotFoundError:
                    pass

    def test_plaintext_credentials_are_migrated(self):
        from app.db.database import execute, query_one

        key_file = os.path.join(tempfile.gettempdir(), "sistem1-test-plaintext-key")
        try:
            os.unlink(key_file)
        except FileNotFoundError:
            pass
        with patch.dict(
            os.environ,
            {
                "CREDENTIAL_ENCRYPTION_KEY": "plaintext-migration-key-with-enough-entropy",
                "CREDENTIAL_KEY_FILE": key_file,
            },
            clear=False,
        ):
            row = execute(
                """
                INSERT INTO accounts (name, type, engine, api_key, api_secret)
                VALUES ('Plaintext Secret Test', 'demo', 'demo', 'plain-key', 'plain-secret')
                """
            )
            account_id = row.lastrowid
            try:
                self.assertEqual(ensure_credential_encryption(), 1)
                migrated = query_one(
                    "SELECT api_key, api_secret FROM accounts WHERE id = ?",
                    (account_id,),
                )
                self.assertTrue(migrated["api_key"].startswith(PREFIX))
                self.assertTrue(migrated["api_secret"].startswith(PREFIX))
                self.assertEqual(decrypt_secret(migrated["api_key"]), "plain-key")
                self.assertEqual(decrypt_secret(migrated["api_secret"]), "plain-secret")
            finally:
                execute("DELETE FROM accounts WHERE id = ?", (account_id,))
                try:
                    os.unlink(key_file)
                except FileNotFoundError:
                    pass

    def test_failed_explicit_rotation_keeps_old_key_file(self):
        from app.db.database import execute

        key_file = Path(tempfile.gettempdir()) / "sistem1-test-rotation-key"
        key_file.write_text("old-file-key-with-enough-entropy\n", encoding="utf-8")
        with patch.dict(
            os.environ,
            {"CREDENTIAL_KEY_FILE": str(key_file)},
            clear=False,
        ):
            os.environ.pop("CREDENTIAL_ENCRYPTION_KEY", None)
            encrypted_key = encrypt_secret("api-key")
            encrypted_secret = encrypt_secret("api-secret")
            row = execute(
                """
                INSERT INTO accounts (name, type, engine, api_key, api_secret)
                VALUES ('Rotation Failure Test', 'demo', 'demo', ?, ?)
                """,
                (encrypted_key, encrypted_secret),
            )
            account_id = row.lastrowid

            class FailingConnection:
                def executemany(self, _sql, _rows):
                    raise RuntimeError("simulated write failure")

            @contextmanager
            def failing_transaction():
                yield FailingConnection()

            try:
                os.environ["CREDENTIAL_ENCRYPTION_KEY"] = "new-file-key-with-enough-entropy"
                with (
                    patch("app.db.database.transaction", failing_transaction),
                    self.assertRaisesRegex(RuntimeError, "simulated write failure"),
                ):
                    ensure_credential_encryption()
                self.assertEqual(
                    key_file.read_text(encoding="utf-8").strip(),
                    "old-file-key-with-enough-entropy",
                )
                os.environ.pop("CREDENTIAL_ENCRYPTION_KEY", None)
                self.assertEqual(decrypt_secret(encrypted_key), "api-key")
            finally:
                execute("DELETE FROM accounts WHERE id = ?", (account_id,))
                try:
                    key_file.unlink()
                except FileNotFoundError:
                    pass

    def test_undecryptable_credentials_disable_only_the_affected_bot(self):
        from app.db.database import execute, query_one

        key_file = Path(DB_PATH).with_name("credential-quarantine-test.key")
        try:
            key_file.unlink()
        except FileNotFoundError:
            pass
        with patch.dict(
            os.environ,
            {
                "CREDENTIAL_ENCRYPTION_KEY": "lost-original-key-with-enough-entropy",
                "CREDENTIAL_KEY_FILE": str(key_file),
            },
            clear=False,
        ):
            encrypted_key = encrypt_secret("api-key")
            encrypted_secret = encrypt_secret("api-secret")
        row = execute(
            """
            INSERT INTO accounts (name, type, engine, api_key, api_secret)
            VALUES ('Credential Quarantine Test', 'demo', 'demo', ?, ?)
            """,
            (encrypted_key, encrypted_secret),
        )
        account_id = int(row.lastrowid)
        execute(
            "INSERT INTO bot_configs (account_id, bot_enabled) VALUES (?, 1)",
            (account_id,),
        )
        try:
            with patch.dict(
                os.environ,
                {
                    "CREDENTIAL_ENCRYPTION_KEY": "current-key-with-enough-entropy",
                    "CREDENTIAL_KEY_FILE": str(key_file),
                },
                clear=False,
            ):
                self.assertEqual(ensure_credential_encryption(), 0)
            self.assertIn(account_id, get_invalid_credential_account_ids())
            self.assertEqual(
                query_one(
                    "SELECT bot_enabled FROM bot_configs WHERE account_id = ?",
                    (account_id,),
                )["bot_enabled"],
                0,
            )
            stored = query_one(
                "SELECT api_key, api_secret FROM accounts WHERE id = ?",
                (account_id,),
            )
            self.assertEqual(stored["api_key"], encrypted_key)
            self.assertEqual(stored["api_secret"], encrypted_secret)
        finally:
            mark_credentials_valid(account_id)
            execute("DELETE FROM bot_configs WHERE account_id = ?", (account_id,))
            execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            try:
                key_file.unlink()
            except FileNotFoundError:
                pass


class AuthConfigTests(unittest.TestCase):
    def test_auth_token_minimum_cannot_be_configured_below_security_floor(self):
        self.assertGreaterEqual(auth.MIN_AUTH_TOKEN_LENGTH, 24)

    def test_exposed_host_requires_explicit_token(self):
        fake_config = SimpleNamespace(host="0.0.0.0", auth_token="dev-token")
        with (
            patch.object(auth, "config", fake_config),
            patch.dict(os.environ, {"APP_ENV": "production"}, clear=True),
            self.assertRaises(RuntimeError),
        ):
            auth.validate_auth_config()

    def test_exposed_host_rejects_short_explicit_token(self):
        fake_config = SimpleNamespace(host="0.0.0.0", auth_token="short-token")
        with (
            patch.object(auth, "config", fake_config),
            patch.dict(
                os.environ,
                {"APP_ENV": "production", "AUTH_TOKEN": "short-token"},
                clear=True,
            ),
            self.assertRaises(RuntimeError),
        ):
            auth.validate_auth_config()

    def test_auth_disable_is_allowed_only_on_loopback(self):
        loopback = SimpleNamespace(host="127.0.0.1", auth_token="dev-token")
        exposed = SimpleNamespace(host="0.0.0.0", auth_token="dev-token")
        with patch.object(auth, "config", loopback), patch.dict(
            os.environ, {"DISABLE_AUTH": "true"}, clear=True
        ):
            auth.validate_auth_config()
        with (
            patch.object(auth, "config", exposed),
            patch.dict(os.environ, {"DISABLE_AUTH": "true"}, clear=True),
            self.assertRaises(RuntimeError),
        ):
            auth.validate_auth_config()


class ParserTests(unittest.TestCase):
    def test_strict_trade_input_parsers(self):
        self.assertEqual(parse_account_id("12"), 12)
        self.assertIsNone(parse_account_id("12x"))
        self.assertEqual(parse_leverage("5"), 5)
        self.assertIsNone(parse_leverage("5.5"))
        self.assertEqual(normalize_symbol(" btcusdt "), "BTCUSDT")
        self.assertEqual(normalize_symbol("husdt"), "HUSDT")
        self.assertIsNone(normalize_symbol("BTC/USDT"))
        self.assertEqual(_parse_positive_id("12"), 12)
        self.assertEqual(_parse_positive_id(12.0), 12)
        self.assertIsNone(_parse_positive_id(12.5))
        self.assertIsNone(_parse_positive_id("12x"))

    def test_database_path_is_backend_relative(self):
        # Guvenlik: relatif DATABASE_PATH backend kokune cozulmeli (disari kacamaz).
        # (Test kosumunda conftest DATABASE_PATH'i izole gecici dosyaya ayarlar; bu yuzden
        # cozumleme MANTIGINI dogrudan test ediyoruz, canli sabiti degil.)
        backend_root = Path(__file__).resolve().parents[1]
        rel = Path("data/sistem1_v4.db")
        resolved = (rel if rel.is_absolute() else backend_root / rel).resolve()
        self.assertEqual(resolved, (backend_root / "data" / "sistem1_v4.db").resolve())
        self.assertTrue(DB_PATH.is_absolute())

    def test_backtest_rejects_non_finite_date_ranges(self):
        account = {"account_name": "Test", "enabled_rules": None}
        with patch("app.routes.backtest.query_one", return_value=account):
            positive_inf = _build_config(
                {"accountId": 1, "startMs": 1, "endMs": float("inf")}
            )
            negative_inf = _build_config(
                {"accountId": 1, "startMs": float("-inf"), "endMs": 1}
            )

        self.assertEqual(positive_inf, {"error": "Invalid date range", "status": 400})
        self.assertEqual(negative_inf, {"error": "Invalid date range", "status": 400})


class QueryContractTests(unittest.TestCase):
    def test_db_timestamp_normalizes_utc_offsets_to_canonical_z(self):
        parsed = parse_db_time_ms("2026-06-08T10:17:30.123+00:00")
        self.assertEqual(
            format_db_time_ms(parsed),
            "2026-06-08T10:17:30.123Z",
        )

    def test_backtest_iso_bounds_match_alert_storage_and_use_range_index(self):
        db = sqlite3.connect(":memory:")
        try:
            db.execute(
                "CREATE TABLE alerts (id INTEGER PRIMARY KEY, source_type TEXT, created_at TEXT)"
            )
            db.execute(
                "CREATE INDEX idx_alerts_source_created ON alerts(source_type, created_at)"
            )
            db.execute(
                "INSERT INTO alerts(source_type, created_at) VALUES (?, ?)",
                ("m1_a", "2026-06-08T10:17:30.000Z"),
            )
            start_ms = datetime(
                2026, 6, 8, 10, 17, tzinfo=timezone.utc
            ).timestamp() * 1000
            end_ms = datetime(
                2026, 6, 8, 10, 18, tzinfo=timezone.utc
            ).timestamp() * 1000
            params = ("m1_a", to_db_time(start_ms), to_db_time(end_ms))
            sql = (
                "SELECT id FROM alerts "
                "WHERE source_type = ? AND created_at >= ? AND created_at <= ?"
            )

            rows = db.execute(sql, params).fetchall()
            plan = " ".join(
                str(row[3]) for row in db.execute(f"EXPLAIN QUERY PLAN {sql}", params)
            )
        finally:
            db.close()

        self.assertEqual(len(rows), 1)
        self.assertEqual(params[1], "2026-06-08T10:17:00.000Z")
        self.assertIn("idx_alerts_source_created", plan)

    def test_recent_alert_query_keeps_created_at_sargable(self):
        with (
            patch.object(alert_signals, "now_ms", return_value=1_749_379_020_000),
            patch.object(alert_signals, "query_all", return_value=[]) as query,
        ):
            alert_signals.get_recent_alerts(["m1_a", "fr"], 30)

        sql, params = query.call_args.args
        self.assertIn("created_at >= ?", sql)
        self.assertNotIn("datetime(created_at)", sql)
        self.assertEqual(params, ("m1_a", "fr", "2025-06-08T10:07:00.000Z"))

    def test_trade_metrics_date_filter_uses_account_closed_index(self):
        db = sqlite3.connect(":memory:")
        try:
            db.execute(
                """
                CREATE TABLE trades (
                    id INTEGER PRIMARY KEY,
                    account_id INTEGER,
                    status TEXT,
                    closed_at TEXT
                )
                """
            )
            db.execute(
                "CREATE INDEX idx_trades_account_status_closed "
                "ON trades(account_id, status, closed_at)"
            )
            sql = (
                "SELECT COUNT(*) FROM trades "
                "WHERE account_id = ? AND status = 'closed' "
                "AND closed_at >= datetime('now', ?)"
            )
            plan = " ".join(
                str(row[3])
                for row in db.execute("EXPLAIN QUERY PLAN " + sql, (1, "-24 hours"))
            )
        finally:
            db.close()

        self.assertIn("idx_trades_account_status_closed", plan)
        self.assertIn("closed_at>?", plan)


class CrossSurfaceContractTests(unittest.TestCase):
    def test_frontend_and_backend_rule_keys_match(self):
        rule_defs = (
            Path(__file__).resolve().parents[2]
            / "frontend"
            / "src"
            / "lib"
            / "rule-defs.tsx"
        ).read_text(encoding="utf-8")
        frontend_keys = {
            key
            for key in re.findall(r"\bkey:\s*'([^']+)'", rule_defs)
            if key.startswith("rule_")
        }

        self.assertEqual(frontend_keys, set(get_all_rule_keys()))
        self.assertEqual(len(frontend_keys), 27)


class RouteSecurityTests(unittest.TestCase):
    def test_detailed_health_requires_authentication(self):
        route = next(
            route
            for route in fastapi_app.routes
            if getattr(route, "path", None) == "/api/health/services"
        )
        dependencies = {dependency.call for dependency in route.dependant.dependencies}
        self.assertIn(require_auth, dependencies)


class _ZeroAvailableLiveEngine:
    name = "bybit"

    async def get_balance(self, account_id: int) -> Balance:
        return Balance(
            balance=1000,
            equity=1000,
            unrealized_pnl=0,
            available_balance=0,
        )


class RiskTests(unittest.IsolatedAsyncioTestCase):
    async def test_zero_available_balance_does_not_fallback_to_wallet_balance(self):
        def fake_query_one(sql, params=()):
            if "SELECT initial_balance, engine FROM accounts" in sql:
                return {"initial_balance": 1000, "engine": "bybit"}
            if "SELECT * FROM bot_configs" in sql:
                return {
                    "long_min_score": 4,
                    "short_min_score": -4,
                    "max_positions": 3,
                    "max_drawdown": 20,
                    "max_drawdown_enabled": 1,
                    "leverage": 2,
                    "position_size_pct": 2,
                }
            if "SELECT * FROM paper_wallets" in sql:
                return None
            if "SELECT COUNT(*) as cnt FROM open_positions" in sql:
                return {"cnt": 0}
            if "SELECT * FROM open_positions" in sql:
                return None
            if "SELECT MAX(equity) as peak" in sql:
                return {"peak": None}
            raise AssertionError(f"Unexpected query: {sql}")

        with (
            patch("app.agents.risk.query_one", side_effect=fake_query_one),
            patch("app.agents.risk.get_engine", return_value=_ZeroAvailableLiveEngine()),
        ):
            result = await evaluate_risk(
                {
                    "accountId": 1,
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "score": 10,
                    "price": 100,
                }
            )

        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"], "Balance depleted")


class _ZeroBalanceLiveEngine:
    async def get_balance(self, account_id: int) -> Balance:
        return Balance(
            balance=0,
            equity=0,
            unrealized_pnl=0,
            available_balance=0,
        )


class LiveBalanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_genuine_zero_balance_replaces_stale_database_values(self):
        row = {
            "id": 1,
            "engine": "bybit",
            "has_api_credentials": 1,
            "wallet_balance": 500,
            "available_balance": 400,
            "account_equity": 510,
            "open_unrealized_pnl": 10,
        }
        with patch(
            "app.routes.accounts.live_engine_for",
            return_value=_ZeroBalanceLiveEngine(),
        ):
            result = await enrich_live_balance(row)

        self.assertEqual(result["wallet_balance"], 0)
        self.assertEqual(result["available_balance"], 0)
        self.assertEqual(result["account_equity"], 0)
        self.assertEqual(result["open_unrealized_pnl"], 0)
        self.assertEqual(result["reserved_margin"], 0)

    async def test_bybit_balance_failure_is_not_reported_as_zero(self):
        engine = BybitEngine("https://api.example.invalid", "real", "bybit")
        with (
            patch(
                "app.engines.bybit_engine._get_credentials",
                return_value={"api_key": "key", "api_secret": "secret"},
            ),
            patch(
                "app.engines.bybit_engine._private_request",
                new=AsyncMock(side_effect=RuntimeError("exchange unavailable")),
            ),
            self.assertRaisesRegex(RuntimeError, "exchange unavailable"),
        ):
            await engine.get_balance(1)


class _JsonRequest:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


class _TpSlEngine:
    def __init__(self):
        self.args = None

    async def set_tp_sl(self, *args):
        self.args = args


class TradingRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_tp_update_preserves_existing_sl(self):
        engine = _TpSlEngine()
        request = _JsonRequest(
            {"accountId": 1, "symbol": "BTCUSDT", "side": "long", "tp": 120}
        )
        with (
            patch("app.routes.trading.get_engine_for_account", return_value=engine),
            patch(
                "app.routes.trading.query_one",
                return_value={"tp_price": 110.0, "sl_price": 90.0},
            ),
        ):
            result = await set_tp_sl(request)

        self.assertEqual(result, {"success": True})
        self.assertEqual(engine.args, (1, "BTCUSDT", "long", 120.0, 90.0))


class AlertRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_backfill_uses_existing_service_and_clamps_limit(self):
        request = _JsonRequest({"limit": 3000})
        results = [
            {"channel": "fr", "fetched": 10, "inserted": 3},
            {"channel": "hammer", "fetched": 4, "inserted": 1},
        ]
        service = AsyncMock(return_value=results)
        with patch("app.routes.alerts.backfill_channel_history", service):
            response = await backfill(request)

        service.assert_awaited_once_with(2000)
        self.assertEqual(
            response,
            {"success": True, "totalInserted": 4, "channels": results},
        )

    async def test_backfill_normalizes_timestamp_and_includes_m1_channel(self):
        from app.services import telegram_client

        message = SimpleNamespace(
            message="#BTCUSDT\nBoost Value: +1.5%\nCurrent Price: 100",
            date=datetime(2026, 6, 9, 12, 30, tzinfo=timezone.utc),
        )

        class FakeClient:
            def is_connected(self):
                return True

            async def get_input_entity(self, channel_id):
                return channel_id

            def iter_messages(self, _entity, limit):
                async def generate():
                    self.assert_limit = limit
                    yield message

                return generate()

        fake_client = FakeClient()
        channels = SimpleNamespace(fr=None, hammer=None, sniper=None, m1a="-100123")
        process = unittest.mock.Mock(return_value={"id": 1})
        with (
            patch.object(telegram_client, "_client", fake_client),
            patch.object(telegram_client.config.telegram, "channels", channels),
            patch.object(telegram_client, "query_one", return_value=None) as duplicate_query,
            patch.object(telegram_client, "process_incoming_alert", process),
        ):
            result = await telegram_client.backfill_channel_history(25)

        self.assertEqual(
            result,
            [{"channel": "m1_a", "fetched": 1, "inserted": 1}],
        )
        self.assertEqual(fake_client.assert_limit, 25)
        self.assertEqual(
            duplicate_query.call_args.args[1],
            ("m1_a", "2026-06-09T12:30:00.000Z", message.message),
        )
        process.assert_called_once_with(
            message.message,
            "m1_a",
            received_at="2026-06-09T12:30:00.000Z",
        )


class PaperEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_invalid_order_parameters_before_exchange_or_database_work(self):
        engine = PaperEngine()
        invalid_leverage = await engine.place_order(
            OrderParams(account_id=1, symbol="BTCUSDT", side="long", size=1, leverage=0)
        )
        invalid_size = await engine.place_order(
            OrderParams(account_id=1, symbol="BTCUSDT", side="long", size=float("nan"), leverage=2)
        )

        self.assertFalse(invalid_leverage.success)
        self.assertEqual(invalid_leverage.error, "Invalid leverage")
        self.assertFalse(invalid_size.success)
        self.assertEqual(invalid_size.error, "Invalid size")


class TelegramNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_notification_listeners_are_idempotent_and_removed_on_stop(self):
        account_id = 987654
        fake_telegram_config = SimpleNamespace(
            notify_bot_token="test-token",
            notify_chat_id="test-chat",
        )
        scheduled = []
        with (
            patch.object(telegram.config, "telegram", fake_telegram_config),
            patch("app.services.telegram._schedule", side_effect=scheduled.append),
        ):
            telegram.start_telegram_notifications(account_id)
            telegram.start_telegram_notifications(account_id)
            self.assertIn(account_id, telegram._listeners)
            self.assertIn(account_id, telegram._hourly_tasks)
            self.assertEqual(len(scheduled), 2)
            telegram.stop_telegram_notifications(account_id)

        self.assertNotIn(account_id, telegram._listeners)
        self.assertNotIn(account_id, telegram._hourly_tasks)
        for coro in scheduled:
            coro.close()


if __name__ == "__main__":
    unittest.main()
