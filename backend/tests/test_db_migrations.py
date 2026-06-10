"""app/db/migrations.py + seed.py — sema ve seed (izole gecici DB uzerinde)."""
import sqlite3

from app.db.migrations import MIGRATIONS, _exec_migration_sql, run_migrations

EXPECTED_TABLES = [
    "accounts", "bot_configs", "paper_wallets", "trades", "open_positions",
    "optimizer_results", "optimizer_insights", "optimizer_todos",
    "kline_cache", "kline_cache_meta", "backtest_runs", "funding_cache",
    "alerts", "equity_snapshots",
]


def _tables(db):
    rows = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


class TestSchema:
    def test_expected_tables_exist(self, db):
        tables = _tables(db)
        missing = [t for t in EXPECTED_TABLES if t not in tables]
        assert not missing, f"Eksik tablolar: {missing}"

    def test_optimizer_results_columns(self, db):
        cols = {r[1] for r in db.execute("PRAGMA table_info(optimizer_results)")}
        assert {"strategy_name", "config_json", "total_pnl", "calmar", "backtest_days",
                "deployed_account_id", "deployed_at"} <= cols

    def test_migrations_idempotent(self, db):
        # tekrar calistirmak hata vermemeli, tablo sayisini bozmamali
        before = _tables(db)
        run_migrations()
        run_migrations()
        assert _tables(db) == before

    def test_drawdown_repair_preserves_post_migration_user_changes(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        conn.execute(
            """
            CREATE TABLE bot_configs (
              account_id INTEGER PRIMARY KEY,
              max_drawdown REAL NOT NULL,
              max_drawdown_enabled INTEGER NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO migrations (name, applied_at) VALUES ('038-max-drawdown-toggle', '2026-06-10 12:59:48')"
        )
        conn.executemany(
            "INSERT INTO bot_configs VALUES (?, ?, ?, ?)",
            [
                (1, 30, 0, "2026-06-10 12:00:00"),  # old 038 tarafindan bozulmus
                (2, 30, 0, "2026-06-10 13:00:00"),  # kullanici sonradan kapatmis
                (3, 12, 0, "2026-06-10 12:00:00"),  # ozel limit
                (4, 30, 1, "2026-06-10 12:00:00"),  # zaten acik
            ],
        )

        sql = next(sql for name, sql in MIGRATIONS if name == "039-max-drawdown-default-50-enabled")
        _exec_migration_sql(conn, "039-max-drawdown-default-50-enabled", sql)

        rows = {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                "SELECT account_id, max_drawdown, max_drawdown_enabled FROM bot_configs ORDER BY account_id"
            )
        }
        assert rows == {
            1: (50, 1),
            2: (30, 0),
            3: (12, 0),
            4: (30, 1),
        }


class TestSeed:
    def test_five_paper_accounts(self, db):
        n = db.execute("SELECT COUNT(*) c FROM accounts WHERE type='paper'").fetchone()["c"]
        assert n == 5

    def test_each_account_has_wallet_and_config(self, db):
        accts = db.execute("SELECT id FROM accounts").fetchall()
        for a in accts:
            w = db.execute("SELECT COUNT(*) c FROM paper_wallets WHERE account_id=?", (a["id"],)).fetchone()["c"]
            cfg = db.execute("SELECT COUNT(*) c FROM bot_configs WHERE account_id=?", (a["id"],)).fetchone()["c"]
            assert w == 1 and cfg == 1

    def test_wallet_balance_seeded(self, db):
        row = db.execute(
            "SELECT w.balance FROM paper_wallets w JOIN accounts a ON a.id=w.account_id WHERE a.name='Conservative'"
        ).fetchone()
        assert row["balance"] == 10000

    def test_default_account_flag(self, db):
        n = db.execute("SELECT COUNT(*) c FROM accounts WHERE is_default=1").fetchone()["c"]
        assert n == 1
