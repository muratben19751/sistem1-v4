import json
import math
import os
import re
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db.database import query_one, query_all, execute, transaction
from ..services.bot_manager import start_bot, stop_bot

router = APIRouter()

STATUS_KEY = "optimizer_status"
CONTROL_KEY = "optimizer_control"
STATUS_STALE_MS = 20_000

try:
    BACKTEST_DAYS = max(7, int(os.environ.get("OPTIMIZER_BACKTEST_DAYS") or 365))
except ValueError:
    BACKTEST_DAYS = 365

try:
    JUNK_MIN_TRADES = max(1, int(os.environ.get("OPTIMIZER_JUNK_MIN_TRADES") or 20))
except ValueError:
    JUNK_MIN_TRADES = 20

try:
    CONTROL_COOLDOWN_MS = max(500, int(os.environ.get("OPTIMIZER_CONTROL_COOLDOWN_MS") or 5000))
except ValueError:
    CONTROL_COOLDOWN_MS = 5000

_last_control_at = 0.0
_DIGITS_RE = re.compile(r"^\d+$")


def _now_ms() -> float:
    return time.time() * 1000.0


def reserve_control_window() -> float:
    global _last_control_at
    now = _now_ms()
    retry_after_ms = _last_control_at + CONTROL_COOLDOWN_MS - now
    if retry_after_ms > 0:
        return retry_after_ms
    _last_control_at = now
    return 0


def read_app_config(key: str) -> str | None:
    try:
        r = query_one("SELECT value FROM app_config WHERE key = ?", (key,))
        return r["value"] if r else None
    except Exception:  # noqa: BLE001
        return None


def write_app_config(key: str, value: str) -> None:
    try:
        execute(
            """
            INSERT INTO app_config (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
            """,
            (key, value),
        )
    except Exception:  # noqa: BLE001
        pass


def get_optimizer_status() -> dict:
    fallback = {"running": False, "generation": 1, "evaluated": 0, "currentName": "", "bestCalmar": 0,
                "populationSize": 0, "index": 0, "backtestDays": BACKTEST_DAYS}
    raw = read_app_config(STATUS_KEY)
    if not raw:
        return fallback
    try:
        s = json.loads(raw)
        stale = isinstance(s.get("ts"), (int, float)) and _now_ms() - s["ts"] > STATUS_STALE_MS
        return {
            "running": False if stale else bool(s.get("running")),
            "generation": s.get("generation", 1),
            "evaluated": s.get("evaluated", 0),
            "currentName": s.get("currentName", ""),
            "bestCalmar": s.get("bestCalmar", 0),
            "populationSize": s.get("populationSize", 0),
            "index": s.get("index", 0),
            "backtestDays": s.get("backtestDays", BACKTEST_DAYS),
        }
    except Exception:  # noqa: BLE001
        return fallback


def _result_conds(prefix: str, only_year: bool, hide_junk: bool) -> str:
    c: list[str] = []
    if only_year:
        c.append(f"{prefix}backtest_days >= 365")
    if hide_junk:
        c.append(f"{prefix}max_drawdown > 0")
        c.append(f"{prefix}trades >= {JUNK_MIN_TRADES}")
    return "WHERE " + " AND ".join(c) if c else ""


def get_optimizer_results(limit: int = 50, unique: bool = False, only_year: bool = False, hide_junk: bool = False):
    cols = """r.id, r.strategy_name, r.config_json, r.trades, r.wins, r.losses, r.total_pnl, r.win_rate,
             r.profit_factor, r.sharpe_estimate, r.max_drawdown, r.calmar, r.generation, r.tested_at, r.backtest_days,
             r.deployed_account_id, r.deployed_at, a.id AS live_account_id, a.name AS live_account_name,
             bc.bot_enabled AS live_bot_enabled"""
    if not unique:
        rows = query_all(
            f"""
            SELECT {cols}
            FROM optimizer_results r
            LEFT JOIN accounts a ON a.id = r.deployed_account_id
            LEFT JOIN bot_configs bc ON bc.account_id = a.id
            {_result_conds('r.', only_year, hide_junk)}
            ORDER BY r.calmar DESC, r.total_pnl DESC LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in rows]
    rows = query_all(
        f"""
        SELECT {cols}
        FROM optimizer_results r
        LEFT JOIN accounts a ON a.id = r.deployed_account_id
        LEFT JOIN bot_configs bc ON bc.account_id = a.id
        WHERE r.id IN (
          SELECT id FROM (
            SELECT id, ROW_NUMBER() OVER (
              PARTITION BY trades, wins, losses, total_pnl, calmar, max_drawdown
              ORDER BY (deployed_account_id IS NOT NULL) DESC, generation ASC, id ASC
            ) AS rn
            FROM optimizer_results
            {_result_conds('', only_year, hide_junk)}
          ) WHERE rn = 1
        )
        ORDER BY r.calmar DESC, r.total_pnl DESC LIMIT ?
        """,
        (limit,),
    )
    return [dict(r) for r in rows]


def get_optimizer_insights(limit: int = 30):
    rows = query_all(
        "SELECT id, strategy_name, message, type, created_at FROM optimizer_insights ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


def get_optimizer_stats() -> dict:
    # Tum optimizer_results uzerinden ozet: toplam test, cop, saglam (robFit>0), en iyiler.
    # robFit config_json._wf icinde; json_extract (JSON1) ile cikarilir.
    fallback = {"total": 0, "junk": 0, "robust": 0, "wfCount": 0, "bestRobFit": None,
                "bestCalmar": 0, "junkPct": 0}
    try:
        row = query_one(
            """
            SELECT
              COUNT(*) AS total,
              COALESCE(SUM(CASE WHEN max_drawdown <= 0 OR trades < ? THEN 1 ELSE 0 END), 0) AS junk,
              COALESCE(SUM(CASE WHEN json_extract(config_json, '$._wf.robustFitness') > 0 THEN 1 ELSE 0 END), 0) AS robust,
              COALESCE(SUM(CASE WHEN config_json LIKE '%"_wf"%' THEN 1 ELSE 0 END), 0) AS wf_count,
              MAX(json_extract(config_json, '$._wf.robustFitness')) AS best_robfit,
              MAX(calmar) AS best_calmar
            FROM optimizer_results
            """,
            (JUNK_MIN_TRADES,),
        )
    except Exception:  # noqa: BLE001
        return fallback
    if not row:
        return fallback
    total = row["total"] or 0
    junk = row["junk"] or 0
    return {
        "total": total,
        "junk": junk,
        "robust": row["robust"] or 0,
        "wfCount": row["wf_count"] or 0,
        "bestRobFit": row["best_robfit"],
        "bestCalmar": row["best_calmar"] or 0,
        "junkPct": round(junk * 100 / total, 1) if total else 0,
    }


@router.get("/status")
async def status():
    return get_optimizer_status()


@router.get("/stats")
async def stats():
    return get_optimizer_stats()


_PARITY_INDEX = Path(__file__).resolve().parents[2] / "tools" / "lean_oracle" / "oracle_export" / "parity_index.json"


def _parity_index() -> dict:
    try:
        return json.loads(_PARITY_INDEX.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


@router.get("/results")
async def results(request: Request):
    q = request.query_params
    rows = get_optimizer_results(300, q.get("unique") != "0", q.get("year") == "1", q.get("junk") != "0")
    idx = _parity_index()
    for r in rows:
        p = idx.get(r["strategy_name"])
        r["leanParity"] = p["verdict"] if p else None
        r["leanParityDetail"] = p
    return rows


@router.get("/insights")
async def insights():
    return get_optimizer_insights(30)


@router.post("/start")
async def start():
    st = get_optimizer_status()
    if st["running"]:
        return st
    retry_after_ms = reserve_control_window()
    if retry_after_ms > 0:
        return JSONResponse(status_code=429, content={"error": "Optimizer control cooldown active", "retryAfterMs": retry_after_ms})
    write_app_config(CONTROL_KEY, "run")
    return get_optimizer_status()


@router.post("/stop")
async def stop():
    retry_after_ms = reserve_control_window()
    if retry_after_ms > 0:
        return JSONResponse(status_code=429, content={"error": "Optimizer control cooldown active", "retryAfterMs": retry_after_ms})
    write_app_config(CONTROL_KEY, "stop")
    return get_optimizer_status()


def _clamp_pct(v, d: float) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return d
    return n if (n == n and 0 <= n <= 100) else d


def _clamp_score(v, d: float) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return d
    return n if (n == n and -100 <= n <= 100) else d


def _to_int(v, fallback: int = 0) -> int:
    try:
        n = float(v)
        if n != n:
            return fallback
        return int(round(n))
    except (TypeError, ValueError):
        return fallback


def _parse_positive_id(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return int(value) if math.isfinite(value) and value.is_integer() and value > 0 else None
    text = str(value if value is not None else "").strip()
    if not _DIGITS_RE.fullmatch(text):
        return None
    parsed = int(text)
    return parsed if parsed > 0 else None


async def _read_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return body if isinstance(body, dict) else {}


@router.post("/apply")
async def apply(request: Request):
    body = await _read_body(request)
    account_id = _parse_positive_id(body.get("accountId"))
    if account_id is None:
        return JSONResponse(status_code=400, content={"error": "Invalid accountId"})
    acc = query_one("SELECT id FROM accounts WHERE id = ?", (account_id,))
    if not acc:
        return JSONResponse(status_code=404, content={"error": "Account not found"})
    result_id = body.get("resultId")
    if result_id is not None:
        parsed_result_id = _parse_positive_id(result_id)
        if parsed_result_id is None:
            return JSONResponse(status_code=400, content={"error": "Invalid resultId"})
        cfg_row = query_one("SELECT strategy_name, config_json FROM optimizer_results WHERE id = ?", (parsed_result_id,))
    else:
        cfg_row = query_one("SELECT strategy_name, config_json FROM optimizer_results ORDER BY calmar DESC LIMIT 1")
    if not cfg_row:
        return JSONResponse(status_code=404, content={"error": "Optimizer result not found"})

    try:
        c = json.loads(cfg_row["config_json"])
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": "Bad config_json"})

    enabled_rules = ",".join(c["enabledRules"]) if isinstance(c.get("enabledRules"), list) and c["enabledRules"] else "__none__"
    leverage = max(1, min(125, _to_int(c.get("leverage"), 1) or 1))
    max_positions = max(1, min(100, _to_int(c.get("maxPositions"), 3) or 3))

    execute(
        """
        UPDATE bot_configs SET enabled_rules = ?, long_min_score = ?, short_min_score = ?, tp_percent = ?, sl_percent = ?,
          leverage = ?, position_size_pct = ?, max_positions = ?, signal_source = ?, updated_at = datetime('now')
        WHERE account_id = ?
        """,
        (enabled_rules, _clamp_score(c.get("longMinScore"), 3), _clamp_score(c.get("shortMinScore"), -3),
         _clamp_pct(c.get("tpPercent"), 5), _clamp_pct(c.get("slPercent"), 3), leverage,
         _clamp_pct(c.get("positionSizePct"), 3), max_positions, str(c.get("signalSource") or "all"), account_id),
    )
    apply_name = (cfg_row["strategy_name"] or "Strateji")[:80]
    execute("UPDATE accounts SET name = ?, updated_at = datetime('now') WHERE id = ?", (apply_name, account_id))
    return {"success": True, "name": apply_name, "applied": {"enabledRules": enabled_rules, **c, "leverage": leverage, "maxPositions": max_positions}}


@router.post("/deploy")
async def deploy(request: Request):
    body = await _read_body(request)
    result_id = body.get("resultId")
    if result_id is not None:
        parsed_result_id = _parse_positive_id(result_id)
        if parsed_result_id is None:
            return JSONResponse(status_code=400, content={"error": "Invalid resultId"})
        row = query_one("SELECT id, strategy_name, config_json FROM optimizer_results WHERE id = ?", (parsed_result_id,))
    else:
        row = query_one("SELECT id, strategy_name, config_json FROM optimizer_results ORDER BY calmar DESC LIMIT 1")
    if not row:
        return JSONResponse(status_code=404, content={"error": "Optimizer result not found"})

    try:
        c = json.loads(row["config_json"])
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": "Bad config_json"})

    enabled_rules = ",".join(c["enabledRules"]) if isinstance(c.get("enabledRules"), list) and c["enabledRules"] else "__none__"
    leverage = max(1, min(125, _to_int(c.get("leverage"), 1) or 1))
    max_positions = max(1, min(100, _to_int(c.get("maxPositions"), 3) or 3))

    raw_target_id = body.get("accountId")
    target_id = _parse_positive_id(raw_target_id) if raw_target_id is not None else None
    if raw_target_id is not None and target_id is None:
        return JSONResponse(status_code=400, content={"error": "Invalid accountId"})
    if target_id is not None:
        acc = query_one("SELECT id, name FROM accounts WHERE id = ?", (target_id,))
        if not acc:
            return JSONResponse(status_code=404, content={"error": "Account not found"})
        new_name = (row["strategy_name"] or "Strateji")[:80]
        stop_bot(target_id)
        execute(
            """
            UPDATE bot_configs SET enabled_rules = ?, long_min_score = ?, short_min_score = ?, tp_percent = ?, sl_percent = ?,
              leverage = ?, position_size_pct = ?, max_positions = ?, signal_source = ?, updated_at = datetime('now')
            WHERE account_id = ?
            """,
            (enabled_rules, _clamp_score(c.get("longMinScore"), 3), _clamp_score(c.get("shortMinScore"), -3),
             _clamp_pct(c.get("tpPercent"), 5), _clamp_pct(c.get("slPercent"), 3), leverage,
             _clamp_pct(c.get("positionSizePct"), 3), max_positions, str(c.get("signalSource") or "all"), target_id),
        )
        execute("UPDATE accounts SET name = ?, updated_at = datetime('now') WHERE id = ?", (new_name, target_id))
        execute("UPDATE optimizer_results SET deployed_account_id = ?, deployed_at = datetime('now') WHERE id = ?", (target_id, row["id"]))
        started = start_bot(target_id)
        return {"success": True, "accountId": target_id, "name": new_name, "started": started["success"], "startError": started.get("error")}

    name = ("Canli: " + (row["strategy_name"] or "Strateji"))[:80]

    with transaction() as conn:
        r = conn.execute(
            "INSERT INTO accounts (name, type, engine, balance, initial_balance, leverage, color) VALUES (?, 'paper', 'paper', 10000, 10000, ?, '#22d3ee')",
            (name, leverage),
        )
        account_id = int(r.lastrowid)
        conn.execute(
            """
            INSERT INTO bot_configs (account_id, long_min_score, short_min_score, leverage, max_positions, tp_percent, sl_percent, max_drawdown, max_drawdown_enabled, signal_source, position_size_pct, enabled_rules)
            VALUES (?, ?, ?, ?, ?, ?, ?, 50, 1, ?, ?, ?)
            """,
            (account_id, _clamp_score(c.get("longMinScore"), 3), _clamp_score(c.get("shortMinScore"), -3), leverage, max_positions,
             _clamp_pct(c.get("tpPercent"), 5), _clamp_pct(c.get("slPercent"), 3), str(c.get("signalSource") or "all"), _clamp_pct(c.get("positionSizePct"), 3), enabled_rules),
        )
        conn.execute("INSERT INTO paper_wallets (account_id, balance, initial_balance) VALUES (?, 10000, 10000)", (account_id,))
        conn.execute("UPDATE optimizer_results SET deployed_account_id = ?, deployed_at = datetime('now') WHERE id = ?", (account_id, row["id"]))

    started = start_bot(account_id)
    return {"success": True, "accountId": account_id, "name": name, "started": started["success"], "startError": started.get("error")}
