import os

from ..core.logger import create_logger
from .database import query_one, transaction

log = create_logger("seed")

SEED_ACCOUNTS = [
    {"name": "Conservative", "strategy": "conservative", "balance": 10000, "leverage": 2, "color": "#3B82F6", "is_default": 1,
     "config": {"long_min_score": 4, "short_min_score": -4, "leverage": 2, "max_positions": 5, "tp_percent": 5, "sl_percent": 3, "max_drawdown": 50, "scan_interval": 30}},
    {"name": "Aggressive", "strategy": "aggressive", "balance": 10000, "leverage": 5, "color": "#EF4444", "is_default": 0,
     "config": {"long_min_score": 4, "short_min_score": -4, "leverage": 5, "max_positions": 5, "tp_percent": 8, "sl_percent": 5, "max_drawdown": 50, "scan_interval": 15}},
    {"name": "Scalper", "strategy": "scalper", "balance": 5000, "leverage": 3, "color": "#EAB308", "is_default": 0,
     "config": {"long_min_score": 4, "short_min_score": -4, "leverage": 3, "max_positions": 5, "tp_percent": 2, "sl_percent": 1.5, "max_drawdown": 50, "scan_interval": 10}},
    {"name": "Trend Follower", "strategy": "trend_follower", "balance": 10000, "leverage": 2, "color": "#22C55E", "is_default": 0,
     "config": {"long_min_score": 4, "short_min_score": -4, "leverage": 2, "max_positions": 5, "tp_percent": 10, "sl_percent": 5, "max_drawdown": 50, "scan_interval": 60,
                "enabled_rules": "rule_07_multi_tf,rule_02_h1_trend,rule_05_volume,rule_13_conviction"}},
    {"name": "Custom", "strategy": "custom", "balance": 10000, "leverage": 2, "color": "#A855F7", "is_default": 0,
     "config": {"long_min_score": 4, "short_min_score": -4, "leverage": 2, "max_positions": 5, "tp_percent": 5, "sl_percent": 3, "max_drawdown": 50, "scan_interval": 30}},
]


def seed_accounts():
    if str(os.environ.get("DISABLE_SEED") or "").strip().lower() in ("1", "true", "yes", "on"):
        log.info("Account seeding disabled by DISABLE_SEED")
        return
    count = query_one("SELECT COUNT(*) as cnt FROM accounts")
    if count and count["cnt"] > 0:
        log.info("Accounts already seeded, skipping")
        return

    with transaction() as conn:
        for acc in SEED_ACCOUNTS:
            cur = conn.execute(
                "INSERT INTO accounts (name, type, strategy, balance, initial_balance, leverage, color, is_default, engine) VALUES (?, 'paper', ?, ?, ?, ?, ?, ?, 'paper')",
                (acc["name"], acc["strategy"], acc["balance"], acc["balance"], acc["leverage"], acc["color"], acc["is_default"]),
            )
            account_id = cur.lastrowid
            c = acc["config"]
            conn.execute(
                "INSERT INTO bot_configs (account_id, long_min_score, short_min_score, leverage, max_positions, tp_percent, sl_percent, max_drawdown, max_drawdown_enabled, scan_interval, enabled_rules) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (account_id, c["long_min_score"], c["short_min_score"], c["leverage"], c["max_positions"],
                 c["tp_percent"], c["sl_percent"], c["max_drawdown"], c["scan_interval"], c.get("enabled_rules")),
            )
            conn.execute(
                "INSERT INTO paper_wallets (account_id, balance, initial_balance) VALUES (?, ?, ?)",
                (account_id, acc["balance"], acc["balance"]),
            )

    log.info(f"Seeded {len(SEED_ACCOUNTS)} paper accounts")
