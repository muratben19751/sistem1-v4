import asyncio
import json
import math
import os
import re
import time
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db.database import query_one, query_all, execute
from ..engines.backtest_engine import run_backtest
from ..services.alert_signals import get_source_types
from ..core.logger import create_logger

router = APIRouter()
log = create_logger("backtest")


def _int_env(name, default, minimum):
    try:
        return max(minimum, int(os.environ.get(name) or default))
    except ValueError:
        return default


MAX_STORED_JOBS = _int_env("BACKTEST_MAX_STORED_JOBS", 20, 20)
MAX_RUNNING_JOBS = _int_env("BACKTEST_MAX_RUNNING_JOBS", 2, 1)
MAX_RANGE_DAYS = _int_env("BACKTEST_MAX_RANGE_DAYS", 180, 1)
MAX_SIGNALS = _int_env("BACKTEST_MAX_SIGNALS", 50000, 1000)
MAX_SYMBOLS = _int_env("BACKTEST_MAX_SYMBOLS", 300, 20)
MS_IN_DAY = 86_400_000

_jobs: dict[str, dict] = {}
_job_tasks: set[asyncio.Task] = set()


def _prune_jobs():
    if len(_jobs) <= MAX_STORED_JOBS:
        return
    ordered = sorted(_jobs.values(), key=lambda j: j["startedAt"])
    for j in ordered[:len(_jobs) - MAX_STORED_JOBS]:
        _jobs.pop(j["id"], None)


def _running_jobs_count() -> int:
    return sum(1 for j in _jobs.values() if j["status"] == "running")


async def _read_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return body if isinstance(body, dict) else {}


def _parse_account_id(raw):
    text = str(raw if raw is not None else "").strip()
    if not re.fullmatch(r"\d+", text):
        return None
    i = int(text)
    return i if i > 0 else None


def _build_config(body: dict):
    account_id = _parse_account_id(body.get("accountId"))
    if account_id is None:
        return {"error": "Invalid accountId", "status": 400}
    acc = query_one("SELECT a.name AS account_name, bc.* FROM accounts a LEFT JOIN bot_configs bc ON bc.account_id = a.id WHERE a.id = ?", (account_id,))
    if not acc:
        return {"error": "Account not found", "status": 404}
    acc = dict(acc)
    try:
        start_ms = float(body.get("startMs"))
        end_ms = float(body.get("endMs"))
    except (TypeError, ValueError):
        return {"error": "Invalid date range", "status": 400}
    if not math.isfinite(start_ms) or not math.isfinite(end_ms) or end_ms <= start_ms:
        return {"error": "Invalid date range", "status": 400}
    if (end_ms - start_ms) > MAX_RANGE_DAYS * MS_IN_DAY:
        return {"error": f"Date range too large (max {MAX_RANGE_DAYS} days)", "status": 400}
    enabled_raw = acc.get("enabled_rules")
    enabled_rules = None if enabled_raw is None else ([] if enabled_raw == "__none__" else [s for s in str(enabled_raw).split(",") if s])
    cfg = {
        "enabledRules": enabled_rules,
        "longMinScore": acc.get("long_min_score") if acc.get("long_min_score") is not None else 4,
        "shortMinScore": acc.get("short_min_score") if acc.get("short_min_score") is not None else -4,
        "tpPercent": acc.get("tp_percent") if acc.get("tp_percent") is not None else 5,
        "slPercent": acc.get("sl_percent") if acc.get("sl_percent") is not None else 3,
        "leverage": acc.get("leverage") if acc.get("leverage") is not None else 2,
        "positionSizePct": acc.get("position_size_pct") if acc.get("position_size_pct") is not None else 2,
        "maxPositions": acc.get("max_positions") if acc.get("max_positions") is not None else 5,
        "signalSource": (body.get("signalSource") if isinstance(body.get("signalSource"), str) and body.get("signalSource") else None) or acc.get("signal_source") or "all",
        "trailingStop": bool(acc.get("trailing_stop")),
        "trailingPercent": acc.get("trailing_percent") if acc.get("trailing_percent") is not None else 1,
    }
    ov = body.get("maxPositions")
    if isinstance(ov, int) and 0 < ov <= 100:
        cfg["maxPositions"] = ov
    primary_sources = get_source_types(acc.get("signal_source") or "")
    return {"accountId": account_id, "cfg": cfg, "accountName": acc["account_name"], "startMs": start_ms, "endMs": end_ms, "primarySources": primary_sources}


def _parse_max_signals(raw):
    if raw is None or str(raw).strip() == "":
        return {"value": None}
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return {"error": "Invalid maxSignals", "status": 400}
    if parsed <= 0:
        return {"error": "Invalid maxSignals", "status": 400}
    return {"value": min(parsed, MAX_SIGNALS)}


def _save_run(account_id, account_name, cfg, start_ms, end_ms, result):
    m = result["metrics"]
    execute(
        "INSERT INTO backtest_runs (account_id, account_name, signal_source, start_ms, end_ms, config_json, metrics_json, trades, total_pnl, win_rate, profit_factor, sharpe, max_drawdown, calmar) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (account_id, account_name, cfg["signalSource"], start_ms, end_ms, json.dumps(cfg), json.dumps(m),
         m["trades"], m["totalPnl"], m["winRate"], m["profitFactor"], m["sharpe"], m["maxDrawdown"], m["calmar"]),
    )


async def _run_job(job, account_id, cfg, account_name, start_ms, end_ms, max_signals, max_symbols, taker, slippage, primary_sources):
    try:
        def on_progress(p):
            job["progress"] = p
        result = await run_backtest({
            "strategyConfig": cfg, "startMs": start_ms, "endMs": end_ms,
            "maxSignals": max_signals, "maxSymbols": max_symbols, "taker": taker,
            "slippage": slippage, "primarySources": primary_sources, "onProgress": on_progress,
        })
        try:
            _save_run(account_id, account_name, cfg, start_ms, end_ms, result)
        except Exception as e:  # noqa: BLE001
            log.warn(f"saveRun: {e}")
        job["result"] = {**result, "config": cfg, "accountName": account_name}
        job["progress"] = {"phase": "done", "done": 1, "total": 1}
        job["status"] = "done"
    except asyncio.CancelledError:
        job["error"] = "Backtest cancelled"
        job["result"] = None
        job["progress"] = {"phase": "cancelled", "done": 0, "total": 0}
        job["status"] = "cancelled"
        raise
    except Exception as err:  # noqa: BLE001
        job["error"] = str(err)
        job["result"] = None
        job["progress"] = {"phase": "done", "done": 0, "total": 0}
        job["status"] = "error"
        log.error(f"Backtest job {job['id']} failed: {err}")


async def cancel_backtest_jobs() -> None:
    tasks = [task for task in _job_tasks if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _job_tasks.clear()


@router.post("/start")
async def start(request: Request):
    body = await _read_body(request)
    if _running_jobs_count() >= MAX_RUNNING_JOBS:
        return JSONResponse(status_code=429, content={"error": f"Too many running backtests (max {MAX_RUNNING_JOBS})"})
    built = _build_config(body)
    if "error" in built:
        return JSONResponse(status_code=built["status"], content={"error": built["error"]})
    ms = _parse_max_signals(body.get("maxSignals"))
    if "error" in ms:
        return JSONResponse(status_code=ms["status"], content={"error": ms["error"]})
    req_max_symbols = body.get("maxSymbols")
    max_symbols = min(req_max_symbols, MAX_SYMBOLS) if isinstance(req_max_symbols, int) and req_max_symbols > 0 else MAX_SYMBOLS
    try:
        rt = float(body.get("taker"))
        taker = rt if 0 <= rt <= 5 else None
    except (TypeError, ValueError):
        taker = None
    try:
        rs = float(body.get("slippage"))
        slippage = rs if 0 <= rs <= 5 else None
    except (TypeError, ValueError):
        slippage = None
    job_id = uuid.uuid4().hex
    job = {"id": job_id, "status": "running", "progress": {"phase": "preload", "done": 0, "total": 0}, "result": None, "error": None, "startedAt": time.time() * 1000}
    _jobs[job_id] = job
    _prune_jobs()
    task = asyncio.create_task(
        _run_job(
            job,
            built["accountId"],
            built["cfg"],
            built["accountName"],
            built["startMs"],
            built["endMs"],
            ms["value"],
            max_symbols,
            taker,
            slippage,
            built["primarySources"],
        )
    )
    _job_tasks.add(task)
    task.add_done_callback(_job_tasks.discard)
    return {"jobId": job_id}


@router.get("/job/{job_id}")
async def job(job_id: str):
    j = _jobs.get(job_id)
    if not j:
        return JSONResponse(status_code=404, content={"error": "Job not found"})
    return {"status": j["status"], "progress": j["progress"], "error": j["error"], "result": j["result"] if j["status"] == "done" else None}


@router.post("/run")
async def run(request: Request):
    body = await _read_body(request)
    built = _build_config(body)
    if "error" in built:
        return JSONResponse(status_code=built["status"], content={"error": built["error"]})
    ms = _parse_max_signals(body.get("maxSignals"))
    if "error" in ms:
        return JSONResponse(status_code=ms["status"], content={"error": ms["error"]})
    try:
        result = await run_backtest({"strategyConfig": built["cfg"], "startMs": built["startMs"], "endMs": built["endMs"],
                                     "maxSignals": ms["value"], "maxSymbols": MAX_SYMBOLS, "primarySources": built["primarySources"]})
        _save_run(built["accountId"], built["accountName"], built["cfg"], built["startMs"], built["endMs"], result)
        return {**result, "config": built["cfg"], "accountName": built["accountName"]}
    except Exception as err:  # noqa: BLE001
        log.error(f"Backtest failed: {err}")
        return JSONResponse(status_code=500, content={"error": str(err)})


@router.get("/runs")
async def runs():
    rows = query_all("SELECT id, account_id, account_name, signal_source, start_ms, end_ms, trades, total_pnl, win_rate, profit_factor, sharpe, max_drawdown, calmar, created_at FROM backtest_runs ORDER BY created_at DESC LIMIT 100")
    return [dict(r) for r in rows]


@router.get("/runs/{run_id}")
async def run_detail(run_id: str):
    if not re.fullmatch(r"\d+", run_id):
        return JSONResponse(status_code=400, content={"error": "Invalid id"})
    row = query_one("SELECT * FROM backtest_runs WHERE id = ?", (int(run_id),))
    if not row:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    return dict(row)
