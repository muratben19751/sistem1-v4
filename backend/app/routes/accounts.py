import asyncio
import math
import os
import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db.database import query_one, query_all, execute, transaction
from ..engines.registry import live_engine_for
from ..services.bot_manager import stop_bot
from ..core.secrets import (
    encrypt_secret,
    get_invalid_credential_account_ids,
    mark_credentials_valid,
)

router = APIRouter()

_DIGITS_RE = re.compile(r"^\d+$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _js_round(value: float) -> int:
    return math.floor(value + 0.5)


def _parse_account_id(raw):
    text = str(raw if raw is not None else "").strip()
    if not _DIGITS_RE.match(text):
        return None
    value = int(text)
    return value if value > 0 else None


def _parse_finite_number(raw):
    if isinstance(raw, bool):
        return 1.0 if raw else 0.0
    if isinstance(raw, (int, float)):
        return float(raw) if math.isfinite(float(raw)) else None
    if raw is None:
        return 0.0
    if isinstance(raw, str):
        s = raw.strip()
        if s == "":
            return 0.0
        try:
            n = float(s)
        except ValueError:
            return None
        return n if math.isfinite(n) else None
    return None


def _js_number(raw):
    if isinstance(raw, bool):
        return 1.0 if raw else 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    if raw is None:
        return 0.0
    if isinstance(raw, str):
        s = raw.strip()
        if s == "":
            return 0.0
        try:
            return float(s)
        except ValueError:
            return float("nan")
    return float("nan")


def _is_js_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def normalize_config_value(key: str, value):
    if key == "signal_source":
        if not isinstance(value, str) or len(value.strip()) == 0:
            return {"error": "signal_source required"}
        return {"value": value.strip()}
    if key in ("enabled_rules", "rule_sources"):
        return {"value": None if value is None else str(value)}

    n = _parse_finite_number(value)
    if n is None:
        return {"error": f"{key} must be numeric"}

    if key == "leverage":
        if not float(n).is_integer() or n < 1 or n > 125:
            return {"error": "leverage must be an integer between 1 and 125"}
        return {"value": int(n)}
    if key == "max_positions":
        if not float(n).is_integer() or n < 1 or n > 100:
            return {"error": "max_positions must be an integer between 1 and 100"}
        return {"value": int(n)}
    if key == "scan_interval":
        if not float(n).is_integer() or n < 5 or n > 3600:
            return {"error": "scan_interval must be between 5 and 3600 seconds"}
        return {"value": int(n)}
    if key in ("trailing_stop", "max_drawdown_enabled"):
        return {"value": 1 if n else 0}
    if key in ("tp_percent", "sl_percent", "trailing_percent"):
        if n < 0 or n > 100:
            return {"error": f"{key} must be between 0 and 100"}
        return {"value": n}
    if key in ("max_drawdown", "position_size_pct"):
        if n <= 0 or n > 100:
            return {"error": f"{key} must be > 0 and <= 100"}
        return {"value": n}
    if key == "alert_freshness_minutes":
        if not float(n).is_integer() or n < 1 or n > 1440:
            return {"error": "alert_freshness_minutes must be between 1 and 1440"}
        return {"value": int(n)}
    if key == "alert_score_boost":
        if n < 0 or n > 20:
            return {"error": "alert_score_boost must be between 0 and 20"}
        return {"value": n}
    if key in ("long_min_score", "short_min_score"):
        if n < -100 or n > 100:
            return {"error": f"{key} must be between -100 and 100"}
        return {"value": n}
    return {"value": value}


def normalize_account_value(key: str, value):
    if key == "name":
        if not isinstance(value, str) or len(value.strip()) == 0:
            return {"error": "name required"}
        name = value.strip()
        if len(name) > 80:
            return {"error": "name too long"}
        return {"value": name}
    if key == "color":
        if not isinstance(value, str) or not _COLOR_RE.match(value.strip()):
            return {"error": "invalid color"}
        return {"value": value.strip()}
    return {"error": "invalid account field"}


def normalize_secret(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if len(text) > 0 else None


LIVE_BALANCE_TIMEOUT_MS = int(os.environ.get("LIVE_BALANCE_TIMEOUT_MS") or 0) or 2500


async def enrich_live_balance(row: dict) -> dict:
    engine = live_engine_for(row.get("engine"))
    if not engine or row.get("has_api_credentials") != 1 or row.get("credentials_valid") == 0:
        return row
    try:
        balance = await asyncio.wait_for(engine.get_balance(row["id"]), timeout=LIVE_BALANCE_TIMEOUT_MS / 1000)
    except Exception:  # noqa: BLE001
        return row
    has_valid_values = all(
        isinstance(v, (int, float)) and math.isfinite(v)
        for v in (balance.balance, balance.equity, balance.available_balance, balance.unrealized_pnl)
    )
    if not has_valid_values:
        return row
    return {
        **row,
        "wallet_balance": balance.balance,
        "available_balance": balance.available_balance,
        "account_equity": balance.equity,
        "open_unrealized_pnl": balance.unrealized_pnl,
        "reserved_margin": max(0, balance.equity - balance.available_balance - balance.unrealized_pnl),
    }


async def enrich_live_balances(rows: list[dict]) -> list[dict]:
    return list(await asyncio.gather(*(enrich_live_balance(row) for row in rows)))


def attach_credential_status(rows: list[dict]) -> list[dict]:
    invalid_ids = set(get_invalid_credential_account_ids())
    for row in rows:
        row["credentials_valid"] = (
            0 if row.get("has_api_credentials") == 1 and row["id"] in invalid_ids
            else 1 if row.get("has_api_credentials") == 1
            else None
        )
    return rows


def attach_category_win_rates(rows: list[dict]) -> list[dict]:
    if len(rows) == 0:
        return rows
    ids = [r["id"] for r in rows if isinstance(r.get("id"), int)]
    if len(ids) == 0:
        return rows
    placeholders = ",".join("?" for _ in ids)
    stats = query_all(
        f"""SELECT account_id,
           SUM(CASE WHEN entry_reason IN ('manual','manual_suggested','manual_order') THEN 1 ELSE 0 END) as manual_total,
           SUM(CASE WHEN entry_reason IN ('manual','manual_suggested','manual_order') AND pnl > 0 THEN 1 ELSE 0 END) as manual_wins,
           SUM(CASE WHEN (entry_reason IS NULL OR entry_reason NOT IN ('manual','manual_suggested','manual_order')) AND COALESCE(duration_seconds, 0) < 14400 THEN 1 ELSE 0 END) as scalp_total,
           SUM(CASE WHEN (entry_reason IS NULL OR entry_reason NOT IN ('manual','manual_suggested','manual_order')) AND COALESCE(duration_seconds, 0) < 14400 AND pnl > 0 THEN 1 ELSE 0 END) as scalp_wins,
           SUM(CASE WHEN (entry_reason IS NULL OR entry_reason NOT IN ('manual','manual_suggested','manual_order')) AND COALESCE(duration_seconds, 0) >= 14400 THEN 1 ELSE 0 END) as swing_total,
           SUM(CASE WHEN (entry_reason IS NULL OR entry_reason NOT IN ('manual','manual_suggested','manual_order')) AND COALESCE(duration_seconds, 0) >= 14400 AND pnl > 0 THEN 1 ELSE 0 END) as swing_wins
         FROM trades
         WHERE status = 'closed' AND pnl IS NOT NULL AND account_id IN ({placeholders})
         GROUP BY account_id""",
        ids,
    )
    stats_map = {s["account_id"]: s for s in stats}
    for row in rows:
        s = stats_map.get(row["id"])
        m = s["manual_total"] if s else 0
        sc = s["scalp_total"] if s else 0
        sw = s["swing_total"] if s else 0
        row["wr_scalp"] = _js_round((s["scalp_wins"] / sc) * 1000) / 10 if sc > 0 else 0
        row["n_scalp"] = sc
        row["wr_swing"] = _js_round((s["swing_wins"] / sw) * 1000) / 10 if sw > 0 else 0
        row["n_swing"] = sw
        row["wr_manual"] = _js_round((s["manual_wins"] / m) * 1000) / 10 if m > 0 else 0
        row["n_manual"] = m
    return rows


def attach_drawdowns(rows: list[dict]) -> list[dict]:
    if len(rows) == 0:
        return rows
    ids = [r["id"] for r in rows if isinstance(r.get("id"), int)]
    if len(ids) == 0:
        return rows
    placeholders = ",".join("?" for _ in ids)
    peak_rows = query_all(
        f"SELECT account_id, MAX(equity) as peak FROM equity_snapshots WHERE account_id IN ({placeholders}) GROUP BY account_id",
        ids,
    )
    peak_map = {p["account_id"]: (p["peak"] if p["peak"] is not None else 0) for p in peak_rows}
    for row in rows:
        current = float(row.get("account_equity") if row.get("account_equity") is not None
                        else row.get("wallet_balance") if row.get("wallet_balance") is not None
                        else row.get("balance") if row.get("balance") is not None else 0)
        initial = float(row.get("initial_balance") if row.get("initial_balance") is not None else 0)
        snapshot_peak = peak_map.get(row["id"], 0)
        peak = max(initial, snapshot_peak, current)
        drawdown = max(0, ((peak - current) / peak) * 100) if peak > 0 else 0
        row["peak_equity"] = _js_round(peak * 100) / 100
        row["current_drawdown"] = _js_round(drawdown * 100) / 100
    return rows


_LIST_SELECT = """
    SELECT a.id, a.name, a.type, a.strategy, a.balance, a.initial_balance, a.leverage,
      a.color, a.is_default, a.is_active, a.created_at, a.updated_at, a.engine,
      CASE WHEN a.api_key IS NOT NULL AND a.api_secret IS NOT NULL THEN 1 ELSE 0 END as has_api_credentials,
      bc.long_min_score, bc.short_min_score, bc.leverage as bot_leverage,
      bc.max_positions, bc.tp_percent, bc.sl_percent, bc.max_drawdown, bc.max_drawdown_enabled, bc.scan_interval,
      bc.trailing_stop, bc.trailing_percent, bc.enabled_rules, bc.rule_sources,
      bc.signal_source, bc.alert_freshness_minutes, bc.alert_score_boost, bc.position_size_pct, bc.bot_enabled,
      pw.balance as wallet_balance,
      COALESCE(pw.total_pnl, ts.t_pnl, 0) as total_pnl,
      COALESCE(pw.total_trades, ts.t_total, 0) as total_trades,
      COALESCE(pw.winning_trades, ts.t_wins, 0) as winning_trades,
      COALESCE(pw.losing_trades, ts.t_losses, 0) as losing_trades,
      COALESCE(pm.reserved_margin, 0) as reserved_margin,
      COALESCE(pm.open_unrealized_pnl, 0) as open_unrealized_pnl,
      COALESCE(pw.balance, a.balance) as available_balance,
      COALESCE(pw.balance, a.balance) + COALESCE(pm.reserved_margin, 0) + COALESCE(pm.open_unrealized_pnl, 0) as account_equity
    FROM accounts a
    LEFT JOIN bot_configs bc ON bc.account_id = a.id
    LEFT JOIN paper_wallets pw ON pw.account_id = a.id
    LEFT JOIN (
      SELECT account_id,
        SUM(entry_price * size / CASE WHEN leverage > 0 THEN leverage ELSE 1 END) as reserved_margin,
        SUM(COALESCE(unrealized_pnl, 0)) as open_unrealized_pnl
      FROM open_positions
      GROUP BY account_id
    ) pm ON pm.account_id = a.id
    LEFT JOIN (
      SELECT account_id,
        COUNT(*) as t_total,
        SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as t_wins,
        SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as t_losses,
        SUM(COALESCE(pnl, 0)) as t_pnl
      FROM trades WHERE status = 'closed'
      GROUP BY account_id
    ) ts ON ts.account_id = a.id
"""


@router.get("")
async def list_accounts():
    # Agir tarama/aggregate SQL (trades/open_positions/equity_snapshots) event loop'u
    # bloklamasin -> thread'e al (alerts.py /stats ile ayni desen).
    rows = await asyncio.to_thread(query_all, _LIST_SELECT + " ORDER BY a.is_default DESC, a.id ASC")
    accounts = attach_credential_status([dict(r) for r in rows])
    accounts = await enrich_live_balances(accounts)
    return await asyncio.to_thread(lambda: attach_category_win_rates(attach_drawdowns(accounts)))


@router.get("/{id}")
async def get_account(id: str):
    account_id = _parse_account_id(id)
    if account_id is None:
        return JSONResponse(status_code=400, content={"error": "Invalid account id"})
    detail_select = """
    SELECT a.id, a.name, a.type, a.strategy, a.balance, a.initial_balance, a.leverage,
      a.color, a.is_default, a.is_active, a.created_at, a.updated_at, a.engine,
      CASE WHEN a.api_key IS NOT NULL AND a.api_secret IS NOT NULL THEN 1 ELSE 0 END as has_api_credentials,
      bc.id as bot_config_id, bc.account_id, bc.long_min_score, bc.short_min_score,
      bc.leverage as bot_leverage, bc.max_positions, bc.tp_percent, bc.sl_percent,
      bc.max_drawdown, bc.max_drawdown_enabled, bc.scan_interval, bc.trailing_stop, bc.trailing_percent,
      bc.enabled_rules, bc.rule_sources, bc.signal_source, bc.alert_freshness_minutes,
      bc.alert_score_boost, bc.position_size_pct, bc.bot_enabled,
      pw.balance as wallet_balance,
      COALESCE(pw.total_pnl, ts.t_pnl, 0) as total_pnl,
      COALESCE(pw.total_trades, ts.t_total, 0) as total_trades,
      COALESCE(pw.winning_trades, ts.t_wins, 0) as winning_trades,
      COALESCE(pw.losing_trades, ts.t_losses, 0) as losing_trades,
      COALESCE(pm.reserved_margin, 0) as reserved_margin,
      COALESCE(pm.open_unrealized_pnl, 0) as open_unrealized_pnl,
      COALESCE(pw.balance, a.balance) as available_balance,
      COALESCE(pw.balance, a.balance) + COALESCE(pm.reserved_margin, 0) + COALESCE(pm.open_unrealized_pnl, 0) as account_equity
    FROM accounts a
    LEFT JOIN bot_configs bc ON bc.account_id = a.id
    LEFT JOIN paper_wallets pw ON pw.account_id = a.id
    LEFT JOIN (
      SELECT account_id,
        SUM(entry_price * size / CASE WHEN leverage > 0 THEN leverage ELSE 1 END) as reserved_margin,
        SUM(COALESCE(unrealized_pnl, 0)) as open_unrealized_pnl
      FROM open_positions
      GROUP BY account_id
    ) pm ON pm.account_id = a.id
    LEFT JOIN (
      SELECT account_id,
        COUNT(*) as t_total,
        SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as t_wins,
        SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as t_losses,
        SUM(COALESCE(pnl, 0)) as t_pnl
      FROM trades WHERE status = 'closed'
      GROUP BY account_id
    ) ts ON ts.account_id = a.id
    WHERE a.id = ?
    """
    account = query_one(detail_select, (account_id,))
    if not account:
        return JSONResponse(status_code=404, content={"error": "Account not found"})
    enriched = await enrich_live_balance(attach_credential_status([dict(account)])[0])
    return attach_category_win_rates(attach_drawdowns([enriched]))[0]


@router.get("/{id}/equity")
async def get_account_equity(id: str):
    account_id = _parse_account_id(id)
    if account_id is None:
        return JSONResponse(status_code=400, content={"error": "Invalid account id"})
    snapshots = query_all(
        "SELECT * FROM equity_snapshots WHERE account_id = ? ORDER BY recorded_at ASC",
        (account_id,),
    )
    return [dict(r) for r in snapshots]


VALID_SOURCES = [
    "scanner", "hammer", "sniper", "fr", "m1_a", "v3_a",
    "hammer+sniper", "hammer+fr", "sniper+fr", "hammer+sniper+fr",
    "hammer+sniper+fr+m1_a",
    "scanner+hammer", "scanner+sniper", "scanner+fr", "scanner+m1_a", "scanner+v3_a", "scanner+hammer+sniper+fr",
    "scanner+hammer+sniper+fr+m1_a",
    "all",
]

_CONFIG_ALLOWED = [
    "long_min_score", "short_min_score", "leverage", "max_positions",
    "tp_percent", "sl_percent", "max_drawdown", "max_drawdown_enabled", "scan_interval",
    "trailing_stop", "trailing_percent", "enabled_rules", "rule_sources",
    "signal_source", "alert_freshness_minutes", "alert_score_boost", "position_size_pct",
]
_ACCOUNT_ALLOWED = ["name", "color"]


@router.put("/{id}/config")
async def update_account_config(id: str, request: Request):
    account_id = _parse_account_id(id)
    if account_id is None:
        return JSONResponse(status_code=400, content={"error": "Invalid account id"})
    account = query_one("SELECT id FROM accounts WHERE id = ?", (account_id,))
    if not account:
        return JSONResponse(status_code=404, content={"error": "Account not found"})
    try:
        fields = await request.json()
    except Exception:  # noqa: BLE001
        fields = None
    if fields is None or not isinstance(fields, dict):
        return JSONResponse(status_code=400, content={"error": "Invalid request body"})
    if fields.get("signal_source") and fields["signal_source"] not in VALID_SOURCES:
        return JSONResponse(status_code=400, content={"error": "Invalid signal_source"})

    sets: list[str] = []
    values: list = []
    acc_sets: list[str] = []
    acc_values: list = []
    for key, val in fields.items():
        if key in _CONFIG_ALLOWED:
            normalized = normalize_config_value(key, val)
            if "error" in normalized:
                return JSONResponse(status_code=400, content={"error": normalized["error"]})
            sets.append(f"{key} = ?")
            values.append(normalized["value"])
        elif key in _ACCOUNT_ALLOWED:
            normalized = normalize_account_value(key, val)
            if "error" in normalized:
                return JSONResponse(status_code=400, content={"error": normalized["error"]})
            acc_sets.append(f"{key} = ?")
            acc_values.append(normalized["value"])
    if len(sets) == 0 and len(acc_sets) == 0:
        return JSONResponse(status_code=400, content={"error": "No valid fields"})
    if len(sets) > 0:
        values.append(account_id)
        execute(f"UPDATE bot_configs SET {', '.join(sets)}, updated_at = datetime('now') WHERE account_id = ?", values)
    if len(acc_sets) > 0:
        acc_values.append(account_id)
        execute(f"UPDATE accounts SET {', '.join(acc_sets)}, updated_at = datetime('now') WHERE id = ?", acc_values)
    return {"success": True}


@router.post("")
async def create_account(request: Request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    name = body.get("name")
    type_ = body.get("type")
    engine = body.get("engine")
    api_key = body.get("apiKey")
    api_secret = body.get("apiSecret")
    balance = body.get("balance")
    leverage = body.get("leverage")
    color = body.get("color")

    normalized_name = normalize_account_value("name", name)
    if "error" in normalized_name:
        return JSONResponse(status_code=400, content={"error": normalized_name["error"]})
    normalized_color = {"value": "#3B82F6"} if color is None else normalize_account_value("color", color)
    if "error" in normalized_color:
        return JSONResponse(status_code=400, content={"error": normalized_color["error"]})

    account_type = type_ or "paper"
    if account_type not in ("paper", "real", "demo"):
        return JSONResponse(status_code=400, content={"error": "Invalid account type"})
    account_engine = engine or ("bybit" if account_type == "real" else "demo" if account_type == "demo" else "paper")
    if account_engine not in ("paper", "bybit", "demo"):
        return JSONResponse(status_code=400, content={"error": "Invalid account engine"})
    if account_type == "real" and account_engine != "bybit":
        return JSONResponse(status_code=400, content={"error": "Real accounts must use the Bybit engine"})
    if account_type == "demo" and account_engine != "demo":
        return JSONResponse(status_code=400, content={"error": "Demo accounts must use the demo engine"})
    if account_type == "paper" and account_engine != "paper":
        return JSONResponse(status_code=400, content={"error": "Paper accounts must use the paper engine"})
    needs_credentials = account_type in ("real", "demo")
    normalized_api_key = normalize_secret(api_key)
    normalized_api_secret = normalize_secret(api_secret)
    if needs_credentials and (not normalized_api_key or not normalized_api_secret):
        return JSONResponse(status_code=400, content={"error": "API key and secret are required for real/demo accounts"})
    parsed_balance = _js_number(balance if balance is not None else 10000)
    parsed_leverage = _js_number(leverage if leverage is not None else 2)
    if not math.isfinite(parsed_balance) or parsed_balance <= 0:
        return JSONResponse(status_code=400, content={"error": "Invalid balance"})
    if not float(parsed_leverage).is_integer() or parsed_leverage < 1 or parsed_leverage > 125:
        return JSONResponse(status_code=400, content={"error": "Invalid leverage"})
    parsed_leverage = int(parsed_leverage)

    with transaction() as conn:
        cur = conn.execute(
            """
            INSERT INTO accounts (name, type, engine, api_key, api_secret, balance, initial_balance, leverage, color)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_name["value"],
                account_type,
                account_engine,
                encrypt_secret(normalized_api_key) if needs_credentials else None,
                encrypt_secret(normalized_api_secret) if needs_credentials else None,
                parsed_balance,
                parsed_balance,
                parsed_leverage,
                normalized_color["value"],
            ),
        )
        new_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO bot_configs (account_id, long_min_score, short_min_score, leverage, max_positions, tp_percent, sl_percent, max_drawdown, max_drawdown_enabled, scan_interval)
            VALUES (?, 5, -5, ?, 3, 5, 3, 50, 0, 30)
            """,
            (new_id, parsed_leverage),
        )
        if account_type == "paper":
            conn.execute(
                """
                INSERT INTO paper_wallets (account_id, balance, initial_balance)
                VALUES (?, ?, ?)
                """,
                (new_id, parsed_balance, parsed_balance),
            )

    return {"success": True, "accountId": new_id}


@router.put("/{id}/credentials")
async def update_credentials(id: str, request: Request):
    account_id = _parse_account_id(id)
    if account_id is None:
        return JSONResponse(status_code=400, content={"error": "Invalid account id"})
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    api_key = body.get("apiKey")
    api_secret = body.get("apiSecret")
    account = query_one("SELECT * FROM accounts WHERE id = ?", (account_id,))
    if not account:
        return JSONResponse(status_code=404, content={"error": "Account not found"})
    normalized_api_key = normalize_secret(api_key)
    normalized_api_secret = normalize_secret(api_secret)
    if not normalized_api_key or not normalized_api_secret:
        return JSONResponse(status_code=400, content={"error": "API key and secret are required"})

    execute(
        "UPDATE accounts SET api_key = ?, api_secret = ?, updated_at = datetime('now') WHERE id = ?",
        (encrypt_secret(normalized_api_key), encrypt_secret(normalized_api_secret), account_id),
    )
    mark_credentials_valid(account_id)
    return {"success": True}


@router.post("/{id}/demo-funds")
async def request_demo_funds(id: str, request: Request):
    account_id = _parse_account_id(id)
    if account_id is None:
        return JSONResponse(status_code=400, content={"error": "Invalid account id"})
    account = query_one("SELECT * FROM accounts WHERE id = ?", (account_id,))
    if not account:
        return JSONResponse(status_code=404, content={"error": "Account not found"})
    if account["engine"] != "demo":
        return JSONResponse(status_code=400, content={"error": "Demo funds can only be requested for demo accounts"})
    engine = live_engine_for("demo")
    if not engine:
        return JSONResponse(status_code=500, content={"error": "Demo engine unavailable"})
    # TODO Faz: real engine — engine.request_demo_funds
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    coin = body.get("coin") if isinstance(body.get("coin"), str) else "USDT"
    amount = body.get("amount")
    amount_str = amount if isinstance(amount, str) else str(amount if amount is not None else "100000")
    # Bybit demo-funds ondalikli tutari SESSIZCE reddediyor (basari doner, para gelmez);
    # tam sayiya yukari yuvarla.
    try:
        amount_str = str(int(math.ceil(float(amount_str))))
    except (TypeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "Invalid amount"})
    try:
        await engine.request_demo_funds(account_id, coin, amount_str)
        return {"success": True}
    except Exception as err:  # noqa: BLE001
        return JSONResponse(status_code=502, content={"error": str(err) or "Demo funds request failed"})


@router.delete("/{id}")
async def delete_account(id: str):
    account_id = _parse_account_id(id)
    if account_id is None:
        return JSONResponse(status_code=400, content={"error": "Invalid account id"})
    account = query_one("SELECT * FROM accounts WHERE id = ?", (account_id,))
    if not account:
        return JSONResponse(status_code=404, content={"error": "Account not found"})
    if account["type"] == "real" or account["engine"] == "bybit" or account["engine"] == "demo":
        return JSONResponse(status_code=400, content={"error": "Real/Bybit accounts cannot be deleted from the dashboard. Close exchange positions and remove credentials manually."})

    stop_bot(account_id)
    with transaction() as conn:
        # Varsayilan hesap siliniyorsa baska bir hesabi otomatik varsayilan yap (paper tercihli).
        if account["is_default"]:
            other = conn.execute(
                "SELECT id FROM accounts WHERE id != ? ORDER BY (engine = 'paper') DESC, id ASC LIMIT 1",
                (account_id,),
            ).fetchone()
            if other:
                conn.execute("UPDATE accounts SET is_default = 1 WHERE id = ?", (other["id"],))
        conn.execute("DELETE FROM open_positions WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM trades WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM equity_snapshots WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM paper_wallets WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM bot_configs WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM learning_weights WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM weight_history WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM bot_logs WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM exchange_orders WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))

    return {"success": True}


@router.post("/{id}/default")
async def set_default_account(id: str):
    account_id = _parse_account_id(id)
    if account_id is None:
        return JSONResponse(status_code=400, content={"error": "Invalid account id"})
    account = query_one("SELECT id FROM accounts WHERE id = ?", (account_id,))
    if not account:
        return JSONResponse(status_code=404, content={"error": "Account not found"})
    with transaction() as conn:
        conn.execute("UPDATE accounts SET is_default = 0 WHERE is_default = 1")
        conn.execute("UPDATE accounts SET is_default = 1, updated_at = datetime('now') WHERE id = ?", (account_id,))
    return {"success": True}


@router.put("/{id}/equity")
async def update_account_equity(id: str, request: Request):
    account_id = _parse_account_id(id)
    if account_id is None:
        return JSONResponse(status_code=400, content={"error": "Invalid account id"})
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    balance = body.get("balance")
    if not _is_js_number(balance) or not math.isfinite(balance) or balance < 0:
        return JSONResponse(status_code=400, content={"error": "Invalid balance"})
    account = query_one("SELECT * FROM accounts WHERE id = ?", (account_id,))
    if not account:
        return JSONResponse(status_code=404, content={"error": "Account not found"})
    if account["type"] == "real" or account["engine"] == "bybit" or account["engine"] == "demo":
        return JSONResponse(status_code=400, content={"error": "Balance editing is only supported for paper accounts"})

    with transaction() as conn:
        conn.execute("UPDATE paper_wallets SET balance = ?, updated_at = datetime('now') WHERE account_id = ?", (balance, account_id))
        conn.execute("UPDATE accounts SET balance = ?, updated_at = datetime('now') WHERE id = ?", (balance, account_id))

    return {"success": True}


@router.post("/{id}/reset")
async def reset_account(id: str, request: Request):
    account_id = _parse_account_id(id)
    if account_id is None:
        return JSONResponse(status_code=400, content={"error": "Invalid account id"})
    account = query_one("SELECT * FROM accounts WHERE id = ?", (account_id,))
    if not account:
        return JSONResponse(status_code=404, content={"error": "Account not found"})
    if account["type"] == "real" or account["engine"] == "bybit" or account["engine"] == "demo":
        return JSONResponse(status_code=400, content={"error": "Reset is only supported for paper accounts"})
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    clear_trades = bool((body or {}).get("clearTrades", True))

    stop_bot(account_id)
    archived = 0
    with transaction() as conn:
        # Cuzdan / pozisyon / equity her durumda sifirlanir; ad bosaltilir (bos bot slotu).
        conn.execute("UPDATE paper_wallets SET balance = initial_balance, total_pnl = 0, total_trades = 0, winning_trades = 0, losing_trades = 0 WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM open_positions WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM equity_snapshots WHERE account_id = ?", (account_id,))
        # Trade gecmisi opsiyonel: silinecekse ONCE trades_archive'e tasinir (ayri tutulur), sonra temizlenir.
        if clear_trades:
            cur = conn.execute(
                """
                INSERT INTO trades_archive
                  (account_name, orig_trade_id, account_id, symbol, side, size, entry_price, exit_price,
                   leverage, pnl, pnl_percent, fee, status, active_rules, signal_score, entry_reason,
                   exit_reason, opened_at, closed_at, duration_seconds)
                SELECT ?, id, account_id, symbol, side, size, entry_price, exit_price,
                   leverage, pnl, pnl_percent, fee, status, active_rules, signal_score, entry_reason,
                   exit_reason, opened_at, closed_at, duration_seconds
                FROM trades WHERE account_id = ?
                """,
                (account["name"], account_id),
            )
            archived = cur.rowcount or 0
            conn.execute("DELETE FROM trades WHERE account_id = ?", (account_id,))
        conn.execute("UPDATE accounts SET name = '', updated_at = datetime('now') WHERE id = ?", (account_id,))

    return {"success": True, "clearedTrades": clear_trades, "archived": archived}
