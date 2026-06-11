from ..core.logger import create_logger
from .database import init_db

log = create_logger("database")


def _is_ignorable(err: Exception) -> bool:
    return "duplicate column name" in str(err).lower()


def _exec_migration_sql(conn, name: str, sql: str) -> None:
    for stmt in (s.strip() for s in sql.split(";")):
        if not stmt:
            continue
        try:
            conn.execute(stmt)
        except Exception as err:  # noqa: BLE001
            if _is_ignorable(err):
                preview = " ".join(stmt.split())[:120]
                log.warn(f"Migration {name}: skipping already-applied column change ({preview})")
                continue
            raise


def run_migrations():
    conn = init_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS migrations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()
    applied = {r["name"] for r in conn.execute("SELECT name FROM migrations").fetchall()}

    for name, sql in MIGRATIONS:
        if name in applied:
            continue
        log.info(f"Running migration: {name}")
        try:
            _exec_migration_sql(conn, name, sql)
            conn.execute("INSERT INTO migrations (name) VALUES (?)", (name,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    log.info("All migrations applied")
    return conn


MIGRATIONS: list[tuple[str, str]] = [
    ("001-initial", """
        CREATE TABLE IF NOT EXISTS accounts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          type TEXT NOT NULL DEFAULT 'paper',
          strategy TEXT,
          balance REAL NOT NULL DEFAULT 10000,
          initial_balance REAL NOT NULL DEFAULT 10000,
          leverage INTEGER NOT NULL DEFAULT 2,
          color TEXT NOT NULL DEFAULT '#3B82F6',
          is_default INTEGER NOT NULL DEFAULT 0,
          is_active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS bot_configs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          account_id INTEGER NOT NULL UNIQUE,
          long_min_score REAL NOT NULL DEFAULT 4,
          short_min_score REAL NOT NULL DEFAULT -4,
          leverage INTEGER NOT NULL DEFAULT 2,
          max_positions INTEGER NOT NULL DEFAULT 5,
          tp_percent REAL NOT NULL DEFAULT 5,
          sl_percent REAL NOT NULL DEFAULT 3,
          max_drawdown REAL NOT NULL DEFAULT 50,
          scan_interval INTEGER NOT NULL DEFAULT 30,
          trailing_stop INTEGER NOT NULL DEFAULT 0,
          trailing_percent REAL NOT NULL DEFAULT 1,
          enabled_rules TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (account_id) REFERENCES accounts(id)
        );
        CREATE TABLE IF NOT EXISTS trades (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          account_id INTEGER NOT NULL,
          symbol TEXT NOT NULL,
          side TEXT NOT NULL,
          size REAL NOT NULL,
          entry_price REAL NOT NULL,
          exit_price REAL,
          leverage INTEGER NOT NULL DEFAULT 1,
          pnl REAL,
          pnl_percent REAL,
          fee REAL NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'open',
          active_rules TEXT,
          signal_score REAL,
          entry_reason TEXT,
          exit_reason TEXT,
          opened_at TEXT NOT NULL DEFAULT (datetime('now')),
          closed_at TEXT,
          duration_seconds INTEGER,
          FOREIGN KEY (account_id) REFERENCES accounts(id)
        );
        CREATE TABLE IF NOT EXISTS open_positions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          account_id INTEGER NOT NULL,
          symbol TEXT NOT NULL,
          side TEXT NOT NULL,
          size REAL NOT NULL,
          entry_price REAL NOT NULL,
          mark_price REAL,
          leverage INTEGER NOT NULL DEFAULT 1,
          unrealized_pnl REAL DEFAULT 0,
          tp_price REAL,
          sl_price REAL,
          trailing_stop INTEGER NOT NULL DEFAULT 0,
          trailing_highest REAL,
          trailing_lowest REAL,
          opened_at TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (account_id) REFERENCES accounts(id),
          UNIQUE(account_id, symbol, side)
        );
        CREATE TABLE IF NOT EXISTS equity_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          account_id INTEGER NOT NULL,
          equity REAL NOT NULL,
          balance REAL NOT NULL,
          unrealized_pnl REAL NOT NULL DEFAULT 0,
          drawdown REAL NOT NULL DEFAULT 0,
          recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (account_id) REFERENCES accounts(id)
        );
        CREATE TABLE IF NOT EXISTS paper_wallets (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          account_id INTEGER NOT NULL UNIQUE,
          balance REAL NOT NULL DEFAULT 10000,
          initial_balance REAL NOT NULL DEFAULT 10000,
          total_pnl REAL NOT NULL DEFAULT 0,
          total_trades INTEGER NOT NULL DEFAULT 0,
          winning_trades INTEGER NOT NULL DEFAULT 0,
          losing_trades INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (account_id) REFERENCES accounts(id)
        );
        CREATE TABLE IF NOT EXISTS alerts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          symbol TEXT NOT NULL,
          direction TEXT NOT NULL,
          signal_type TEXT,
          rsi_h1 REAL,
          rsi_h4 REAL,
          rsi_d1 REAL,
          srsi REAL,
          boost_value REAL,
          price REAL,
          raw_message TEXT,
          source TEXT,
          matched_with_bot INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS learning_weights (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          account_id INTEGER NOT NULL,
          rule_key TEXT NOT NULL,
          weight REAL NOT NULL DEFAULT 1.0,
          trades_count INTEGER NOT NULL DEFAULT 0,
          win_rate REAL NOT NULL DEFAULT 0,
          avg_pnl REAL NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (account_id) REFERENCES accounts(id),
          UNIQUE(account_id, rule_key)
        );
        CREATE TABLE IF NOT EXISTS user_preferences (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          key TEXT NOT NULL UNIQUE,
          value TEXT NOT NULL,
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS app_config (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          key TEXT NOT NULL UNIQUE,
          value TEXT NOT NULL,
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_trades_account ON trades(account_id);
        CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
        CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
        CREATE INDEX IF NOT EXISTS idx_positions_account ON open_positions(account_id);
        CREATE INDEX IF NOT EXISTS idx_equity_account ON equity_snapshots(account_id);
        CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol);
        CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at);
    """),
    ("002-real-accounts", """
        ALTER TABLE accounts ADD COLUMN api_key TEXT;
        ALTER TABLE accounts ADD COLUMN api_secret TEXT;
        ALTER TABLE accounts ADD COLUMN engine TEXT NOT NULL DEFAULT 'paper';
    """),
    ("003-alert-sources", """
        ALTER TABLE alerts ADD COLUMN source_type TEXT NOT NULL DEFAULT 'unknown';
        ALTER TABLE alerts ADD COLUMN rsi_data TEXT;
        ALTER TABLE alerts ADD COLUMN srsi_data TEXT;
        ALTER TABLE alerts ADD COLUMN previous_price REAL;
        ALTER TABLE alerts ADD COLUMN rsi_1m REAL;
        ALTER TABLE alerts ADD COLUMN rsi_5m REAL;
        ALTER TABLE alerts ADD COLUMN srsi_1m REAL;
        ALTER TABLE alerts ADD COLUMN srsi_5m REAL;
        ALTER TABLE alerts ADD COLUMN srsi_1h REAL;
        ALTER TABLE alerts ADD COLUMN srsi_4h REAL;
        ALTER TABLE alerts ADD COLUMN srsi_1d REAL;
    """),
    ("004-signal-source", """
        ALTER TABLE bot_configs ADD COLUMN signal_source TEXT NOT NULL DEFAULT 'scanner';
        ALTER TABLE bot_configs ADD COLUMN alert_freshness_minutes INTEGER NOT NULL DEFAULT 30;
        ALTER TABLE bot_configs ADD COLUMN alert_score_boost REAL NOT NULL DEFAULT 2.0;
    """),
    ("005-indexes", """
        CREATE INDEX IF NOT EXISTS idx_trades_opened ON trades(opened_at);
        CREATE INDEX IF NOT EXISTS idx_trades_closed ON trades(closed_at);
        CREATE INDEX IF NOT EXISTS idx_equity_recorded ON equity_snapshots(recorded_at);
        CREATE INDEX IF NOT EXISTS idx_trades_account_status ON trades(account_id, status);
    """),
    ("008-bot-enabled", """
        ALTER TABLE bot_configs ADD COLUMN bot_enabled INTEGER NOT NULL DEFAULT 0;
    """),
    ("007-position-size-pct", """
        ALTER TABLE bot_configs ADD COLUMN position_size_pct REAL NOT NULL DEFAULT 2;
    """),
    ("006-weight-history", """
        CREATE TABLE IF NOT EXISTS weight_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          account_id INTEGER NOT NULL,
          rule_key TEXT NOT NULL,
          trade_id INTEGER,
          symbol TEXT,
          side TEXT,
          pnl REAL,
          old_weight REAL NOT NULL,
          new_weight REAL NOT NULL,
          adjustment REAL NOT NULL,
          trades_count INTEGER NOT NULL,
          win_rate REAL NOT NULL,
          reason TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (account_id) REFERENCES accounts(id)
        );
        CREATE INDEX IF NOT EXISTS idx_wh_account_rule ON weight_history(account_id, rule_key);
        CREATE INDEX IF NOT EXISTS idx_wh_created ON weight_history(created_at);
    """),
    ("010-rule-sources", """
        ALTER TABLE bot_configs ADD COLUMN rule_sources TEXT;
    """),
    ("009-fr-fields", """
        ALTER TABLE alerts ADD COLUMN funding_rate REAL;
        ALTER TABLE alerts ADD COLUMN previous_funding REAL;
        ALTER TABLE alerts ADD COLUMN time_remaining TEXT;
        ALTER TABLE alerts ADD COLUMN funding_changed INTEGER NOT NULL DEFAULT 0;
    """),
    ("011-optimizer", """
        CREATE TABLE IF NOT EXISTS optimizer_results (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          strategy_name TEXT NOT NULL,
          config_json TEXT,
          trades INTEGER NOT NULL DEFAULT 0,
          wins INTEGER NOT NULL DEFAULT 0,
          losses INTEGER NOT NULL DEFAULT 0,
          total_pnl REAL NOT NULL DEFAULT 0,
          win_rate REAL NOT NULL DEFAULT 0,
          avg_pnl REAL NOT NULL DEFAULT 0,
          tested_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_optimizer_pnl ON optimizer_results(total_pnl DESC);
    """),
    ("012-optimizer-insights-todos", """
        CREATE TABLE IF NOT EXISTS optimizer_insights (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          strategy_name TEXT NOT NULL,
          message TEXT NOT NULL,
          type TEXT NOT NULL DEFAULT 'info',
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS optimizer_todos (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          priority TEXT NOT NULL DEFAULT 'med',
          message TEXT NOT NULL,
          strategy_name TEXT,
          done INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_opt_insights_created ON optimizer_insights(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_opt_todos_done ON optimizer_todos(done, priority);
    """),
    ("013-optimizer-advanced-metrics", """
        ALTER TABLE optimizer_results ADD COLUMN profit_factor REAL NOT NULL DEFAULT 0;
        ALTER TABLE optimizer_results ADD COLUMN sharpe_estimate REAL NOT NULL DEFAULT 0;
        ALTER TABLE optimizer_results ADD COLUMN avg_win REAL NOT NULL DEFAULT 0;
        ALTER TABLE optimizer_results ADD COLUMN avg_loss REAL NOT NULL DEFAULT 0;
        ALTER TABLE optimizer_results ADD COLUMN generation INTEGER NOT NULL DEFAULT 1;
    """),
    ("014-alert-stars", """
        ALTER TABLE alerts ADD COLUMN stars INTEGER NOT NULL DEFAULT 0;
    """),
    ("015-delist-warnings", """
        CREATE TABLE IF NOT EXISTS delist_warnings (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          exchange TEXT NOT NULL,
          symbol TEXT NOT NULL,
          market_type TEXT NOT NULL DEFAULT 'spot',
          delist_date TEXT NOT NULL,
          announcement_url TEXT,
          announcement_title TEXT,
          announcement_id TEXT NOT NULL,
          alert_level TEXT NOT NULL DEFAULT 'new',
          has_open_position INTEGER NOT NULL DEFAULT 0,
          notified_levels TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          UNIQUE(exchange, announcement_id)
        );
        CREATE INDEX IF NOT EXISTS idx_delist_symbol ON delist_warnings(symbol);
        CREATE INDEX IF NOT EXISTS idx_delist_level ON delist_warnings(alert_level);
        CREATE INDEX IF NOT EXISTS idx_delist_date ON delist_warnings(delist_date);
    """),
    ("016-bot-logs", """
        CREATE TABLE IF NOT EXISTS bot_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          account_id INTEGER NOT NULL,
          level TEXT NOT NULL DEFAULT 'info',
          message TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (account_id) REFERENCES accounts(id)
        );
        CREATE INDEX IF NOT EXISTS idx_bot_logs_account ON bot_logs(account_id, created_at DESC);
    """),
    ("017-trade-genius", """
        CREATE TABLE IF NOT EXISTS genius_rules (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          rule_key TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          ts_body TEXT NOT NULL,
          side_hint TEXT NOT NULL DEFAULT 'both',
          status TEXT NOT NULL DEFAULT 'active',
          trades INTEGER NOT NULL DEFAULT 0,
          wins INTEGER NOT NULL DEFAULT 0,
          losses INTEGER NOT NULL DEFAULT 0,
          total_pnl REAL NOT NULL DEFAULT 0,
          win_rate REAL NOT NULL DEFAULT 0,
          consecutive_errors INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          retired_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_genius_rules_status ON genius_rules(status);
        CREATE TABLE IF NOT EXISTS genius_thoughts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL DEFAULT (datetime('now')),
          kind TEXT NOT NULL DEFAULT 'reasoning',
          text TEXT NOT NULL,
          related_rule_id INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_genius_thoughts_ts ON genius_thoughts(ts DESC);
        CREATE TABLE IF NOT EXISTS genius_state (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          balance REAL NOT NULL DEFAULT 10000,
          peak_balance REAL NOT NULL DEFAULT 10000,
          target REAL NOT NULL DEFAULT 200000,
          cycles_run INTEGER NOT NULL DEFAULT 0,
          last_cycle_at TEXT
        );
        INSERT OR IGNORE INTO genius_state (id, balance, peak_balance, target, cycles_run)
          VALUES (1, 10000, 10000, 200000, 0);
        INSERT INTO accounts (name, type, strategy, balance, initial_balance, leverage, color, is_active, engine)
        SELECT 'Trade Genius', 'paper', 'llm-genius', 10000, 10000, 2, '#a855f7', 1, 'paper'
        WHERE NOT EXISTS (SELECT 1 FROM accounts WHERE name = 'Trade Genius');
        INSERT INTO paper_wallets (account_id, balance, initial_balance)
        SELECT id, 10000, 10000
        FROM accounts
        WHERE name = 'Trade Genius'
          AND NOT EXISTS (SELECT 1 FROM paper_wallets WHERE account_id = accounts.id);
        INSERT INTO bot_configs (
          account_id, long_min_score, short_min_score, leverage, max_positions,
          tp_percent, sl_percent, max_drawdown, scan_interval, enabled_rules,
          signal_source, alert_freshness_minutes, alert_score_boost,
          position_size_pct, bot_enabled
        )
        SELECT id, 2.5, -99, 2, 2, 3, 1.5, 6, 90, '__none__',
          'scanner+hammer+sniper+fr', 20, 1, 1, 0
        FROM accounts
        WHERE name = 'Trade Genius'
          AND NOT EXISTS (SELECT 1 FROM bot_configs WHERE account_id = accounts.id);
    """),
    ("018-rule-labels", """
        CREATE TABLE IF NOT EXISTS rule_labels (
          rule_key TEXT PRIMARY KEY,
          custom_name TEXT,
          custom_note TEXT,
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """),
    ("019-position-intra-range", """
        ALTER TABLE open_positions ADD COLUMN intra_high REAL;
        ALTER TABLE open_positions ADD COLUMN intra_low REAL;
        UPDATE open_positions SET intra_high = entry_price WHERE intra_high IS NULL;
        UPDATE open_positions SET intra_low = entry_price WHERE intra_low IS NULL;
    """),
    ("020-telegram-ingest-events", """
        CREATE TABLE IF NOT EXISTS telegram_ingest_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_type TEXT NOT NULL,
          status TEXT NOT NULL,
          symbol TEXT,
          direction TEXT,
          error TEXT,
          raw_message TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_telegram_ingest_source_created
          ON telegram_ingest_events(source_type, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_telegram_ingest_status_created
          ON telegram_ingest_events(status, created_at DESC);
    """),
    ("021-bot-logs-persist", """
        ALTER TABLE bot_logs ADD COLUMN persist INTEGER NOT NULL DEFAULT 0;
    """),
    ("022-trader-club-account", ""),
    ("023-exchange-orders", """
        CREATE TABLE IF NOT EXISTS exchange_orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          account_id INTEGER NOT NULL,
          symbol TEXT NOT NULL,
          side TEXT NOT NULL,
          action TEXT NOT NULL,
          order_link_id TEXT NOT NULL UNIQUE,
          exchange_order_id TEXT,
          status TEXT NOT NULL DEFAULT 'pending',
          requested_qty REAL,
          filled_qty REAL,
          avg_price REAL,
          fee REAL NOT NULL DEFAULT 0,
          error TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (account_id) REFERENCES accounts(id)
        );
        CREATE INDEX IF NOT EXISTS idx_exchange_orders_account_status
          ON exchange_orders(account_id, status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_exchange_orders_symbol
          ON exchange_orders(symbol, created_at DESC);
    """),
    ("024-remove-trade-genius", """
        DELETE FROM open_positions WHERE account_id IN (SELECT id FROM accounts WHERE name = 'Trade Genius');
        DELETE FROM trades WHERE account_id IN (SELECT id FROM accounts WHERE name = 'Trade Genius');
        DELETE FROM equity_snapshots WHERE account_id IN (SELECT id FROM accounts WHERE name = 'Trade Genius');
        DELETE FROM learning_weights WHERE account_id IN (SELECT id FROM accounts WHERE name = 'Trade Genius');
        DELETE FROM weight_history WHERE account_id IN (SELECT id FROM accounts WHERE name = 'Trade Genius');
        DELETE FROM bot_logs WHERE account_id IN (SELECT id FROM accounts WHERE name = 'Trade Genius');
        DELETE FROM exchange_orders WHERE account_id IN (SELECT id FROM accounts WHERE name = 'Trade Genius');
        DELETE FROM bot_configs WHERE account_id IN (SELECT id FROM accounts WHERE name = 'Trade Genius');
        DELETE FROM paper_wallets WHERE account_id IN (SELECT id FROM accounts WHERE name = 'Trade Genius');
        DELETE FROM accounts WHERE name = 'Trade Genius';
        DROP TABLE IF EXISTS genius_rules;
        DROP TABLE IF EXISTS genius_thoughts;
        DROP TABLE IF EXISTS genius_state;
    """),
    ("025-fix-trade-duration-utc", """
        UPDATE trades
        SET duration_seconds = CAST(ROUND((julianday(closed_at) - julianday(opened_at)) * 86400) AS INTEGER)
        WHERE status = 'closed' AND closed_at IS NOT NULL AND opened_at IS NOT NULL;
    """),
    ("026-trade-trigger-meta", """
        ALTER TABLE trades ADD COLUMN trigger_source TEXT;
        ALTER TABLE trades ADD COLUMN trigger_stars INTEGER;
        ALTER TABLE trades ADD COLUMN min_score_used REAL;
        ALTER TABLE trades ADD COLUMN note TEXT;
    """),
    ("027-backtest-optimizer", """
        CREATE TABLE IF NOT EXISTS kline_cache (
          symbol TEXT NOT NULL,
          interval TEXT NOT NULL,
          open_time INTEGER NOT NULL,
          o REAL, h REAL, l REAL, c REAL, v REAL,
          PRIMARY KEY (symbol, interval, open_time)
        ) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS kline_cache_meta (
          symbol TEXT NOT NULL,
          interval TEXT NOT NULL,
          covered_start INTEGER NOT NULL,
          covered_end INTEGER NOT NULL,
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          PRIMARY KEY (symbol, interval)
        );
        ALTER TABLE optimizer_results ADD COLUMN max_drawdown REAL NOT NULL DEFAULT 0;
        ALTER TABLE optimizer_results ADD COLUMN calmar REAL NOT NULL DEFAULT 0;
        CREATE TABLE IF NOT EXISTS backtest_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          account_id INTEGER,
          account_name TEXT,
          signal_source TEXT,
          start_ms INTEGER,
          end_ms INTEGER,
          config_json TEXT,
          metrics_json TEXT,
          trades INTEGER NOT NULL DEFAULT 0,
          total_pnl REAL NOT NULL DEFAULT 0,
          win_rate REAL NOT NULL DEFAULT 0,
          profit_factor REAL NOT NULL DEFAULT 0,
          sharpe REAL NOT NULL DEFAULT 0,
          max_drawdown REAL NOT NULL DEFAULT 0,
          calmar REAL NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_backtest_runs_created ON backtest_runs(created_at DESC);
    """),
    ("028-performance-history-indexes", """
        CREATE INDEX IF NOT EXISTS idx_alerts_source_created
          ON alerts(source_type, created_at);
        CREATE INDEX IF NOT EXISTS idx_equity_account_recorded
          ON equity_snapshots(account_id, recorded_at);
        CREATE INDEX IF NOT EXISTS idx_trades_account_status_closed
          ON trades(account_id, status, closed_at);
    """),
    ("029-optimizer-deployed-link", """
        ALTER TABLE optimizer_results ADD COLUMN deployed_account_id INTEGER;
        UPDATE optimizer_results
        SET deployed_account_id = (
          SELECT a.id FROM accounts a
          WHERE a.name = 'Canli: ' || optimizer_results.strategy_name
          ORDER BY a.id DESC LIMIT 1
        )
        WHERE deployed_account_id IS NULL
          AND calmar = (
            SELECT MAX(r2.calmar) FROM optimizer_results r2
            WHERE r2.strategy_name = optimizer_results.strategy_name
          )
          AND EXISTS (
            SELECT 1 FROM accounts a
            WHERE a.name = 'Canli: ' || optimizer_results.strategy_name
          );
    """),
    ("030-funding-cache", """
        ALTER TABLE alerts ADD COLUMN bybit_fr REAL;
        CREATE TABLE IF NOT EXISTS funding_cache (
          symbol TEXT NOT NULL,
          funding_ts INTEGER NOT NULL,
          funding_rate REAL,
          PRIMARY KEY (symbol, funding_ts)
        ) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS funding_cache_meta (
          symbol TEXT NOT NULL PRIMARY KEY,
          covered_start INTEGER NOT NULL,
          covered_end INTEGER NOT NULL,
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """),
    ("031-optimizer-backtest-days", """
        ALTER TABLE optimizer_results ADD COLUMN backtest_days INTEGER NOT NULL DEFAULT 0;
    """),
    ("032-remove-trader-club", """
        DELETE FROM open_positions WHERE account_id IN (SELECT id FROM accounts WHERE name = 'Trader Club');
        DELETE FROM trades WHERE account_id IN (SELECT id FROM accounts WHERE name = 'Trader Club');
        DELETE FROM equity_snapshots WHERE account_id IN (SELECT id FROM accounts WHERE name = 'Trader Club');
        DELETE FROM learning_weights WHERE account_id IN (SELECT id FROM accounts WHERE name = 'Trader Club');
        DELETE FROM weight_history WHERE account_id IN (SELECT id FROM accounts WHERE name = 'Trader Club');
        DELETE FROM bot_logs WHERE account_id IN (SELECT id FROM accounts WHERE name = 'Trader Club');
        DELETE FROM exchange_orders WHERE account_id IN (SELECT id FROM accounts WHERE name = 'Trader Club');
        DELETE FROM bot_configs WHERE account_id IN (SELECT id FROM accounts WHERE name = 'Trader Club');
        DELETE FROM paper_wallets WHERE account_id IN (SELECT id FROM accounts WHERE name = 'Trader Club');
        DELETE FROM accounts WHERE name = 'Trader Club';
        DELETE FROM alerts WHERE source_type = 'trader_club';
    """),
    ("033-runtime-hardening-indexes", """
        CREATE INDEX IF NOT EXISTS idx_trades_account_opened_desc
          ON trades(account_id, opened_at DESC);
        CREATE INDEX IF NOT EXISTS idx_trades_account_status_opened
          ON trades(account_id, status, opened_at DESC);
        CREATE INDEX IF NOT EXISTS idx_trades_status_opened_desc
          ON trades(status, opened_at DESC);
        CREATE INDEX IF NOT EXISTS idx_trades_status_closed_desc
          ON trades(status, closed_at DESC);
        CREATE INDEX IF NOT EXISTS idx_equity_account_recorded_desc
          ON equity_snapshots(account_id, recorded_at DESC);
        CREATE INDEX IF NOT EXISTS idx_alerts_symbol_created_jd
          ON alerts(symbol, julianday(replace(replace(created_at, 'T', ' '), 'Z', '')));
    """),
    ("034-optimizer-deployed-at", """
        ALTER TABLE optimizer_results ADD COLUMN deployed_at TEXT;
        UPDATE optimizer_results
        SET deployed_at = (SELECT a.created_at FROM accounts a WHERE a.id = optimizer_results.deployed_account_id)
        WHERE deployed_account_id IS NOT NULL AND deployed_at IS NULL;
    """),
    ("035-alert-source-created-index", """
        CREATE INDEX IF NOT EXISTS idx_alerts_source_created_at
          ON alerts(source, created_at);
    """),
    ("036-default-max-drawdown-50", """
        UPDATE bot_configs SET max_drawdown = 50;
    """),
    ("037-trades-archive", """
        CREATE TABLE IF NOT EXISTS trades_archive (
          archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
          archived_at TEXT NOT NULL DEFAULT (datetime('now')),
          account_name TEXT,
          orig_trade_id INTEGER,
          account_id INTEGER NOT NULL,
          symbol TEXT, side TEXT, size REAL, entry_price REAL, exit_price REAL,
          leverage INTEGER, pnl REAL, pnl_percent REAL, fee REAL, status TEXT,
          active_rules TEXT, signal_score REAL, entry_reason TEXT, exit_reason TEXT,
          opened_at TEXT, closed_at TEXT, duration_seconds INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_trades_archive_account ON trades_archive(account_id, archived_at DESC);
    """),
    ("038-max-drawdown-toggle", """
        ALTER TABLE bot_configs ADD COLUMN max_drawdown_enabled INTEGER NOT NULL DEFAULT 1;
        UPDATE bot_configs SET max_drawdown = 50;
    """),
    # 038 ilk surumde DEFAULT 0 + max_drawdown=30 yaziyordu. Yalnizca o migration'dan
    # sonra kullanici tarafindan kaydedilmemis satirlari onar; yeni tercihlere dokunma.
    ("039-max-drawdown-default-50-enabled", """
        UPDATE bot_configs
        SET max_drawdown = 50, max_drawdown_enabled = 1
        WHERE max_drawdown = 30
          AND max_drawdown_enabled = 0
          AND updated_at <= (
            SELECT applied_at FROM migrations WHERE name = '038-max-drawdown-toggle'
          );
    """),
    # Strateji deploy durumu (CANLI/STOPPED) artik API bagintisindan BAGIMSIZ, stratejiye
    # yapisik: 'live' | 'stopped' | NULL. Boylece bir API yeniden kullanilsa bile eski
    # stratejinin STOPPED rozeti kaybolmaz. Mevcut deployed sonuclari 'live' isaretle.
    ("040-optimizer-deploy-state", """
        ALTER TABLE optimizer_results ADD COLUMN deploy_state TEXT;
        UPDATE optimizer_results SET deploy_state = 'live' WHERE deployed_account_id IS NOT NULL;
    """),
    ("041-bot-logs-id-index", """
        CREATE INDEX IF NOT EXISTS idx_bot_logs_account_id_id ON bot_logs(account_id, id DESC);
    """),
]
