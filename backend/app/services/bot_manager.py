import asyncio
import os
import traceback
from datetime import datetime, timezone

from ..core.logger import create_logger
from ..core.event_bus import event_bus
from ..core.time import now_ms
from ..db.database import query_one, query_all, execute
from ..agents.strategy import analyze_symbol
from ..agents.risk import evaluate_risk, account_gate, set_cooldown
from ..agents.execution import execute_order, set_engine
from ..agents.monitor import start_monitor, stop_monitor, is_monitor_running, take_equity_snapshot, check_positions
from ..services.bybit_api import get_top_gainers, is_tradable_linear_symbol
from ..services.alert_signals import get_recent_alerts, get_source_types, needs_scanner, is_alert_only
from ..services.telegram import start_telegram_notifications, stop_telegram_notifications
from ..engines.registry import get_engine

log = create_logger("bot-manager")


def _int_env(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.environ.get(name) or default))
    except ValueError:
        return default


MIN_BOT_SCAN_INTERVAL_SEC = _int_env("MIN_BOT_SCAN_INTERVAL_SEC", 30, 5)
MAX_SCANNER_CANDIDATES = _int_env("MAX_SCANNER_CANDIDATES", 6, 1)
MAX_ALERT_CANDIDATES = _int_env("MAX_ALERT_CANDIDATES", 12, 1)
MAX_BOT_CANDIDATES = _int_env("MAX_BOT_CANDIDATES", 12, 1)
MAX_LOGS = 200
PERSIST_LEVELS = {"warn", "error"}

_bots: dict[int, dict] = {}
_stopping_tasks: set[asyncio.Task] = set()


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _create_state(account_id: int) -> dict:
    return {
        "status": "stopped", "accountId": account_id, "cycle_task": None, "scan_task": None,
        "snapshot_task": None, "initial_snapshot_task": None,
        "startedAt": None, "totalScans": 0, "totalSignals": 0, "totalOrders": 0,
        "lastScan": None, "logs": [], "scanning": False,
    }


def _get_state(account_id: int) -> dict:
    if account_id not in _bots:
        _bots[account_id] = _create_state(account_id)
    return _bots[account_id]


def _own_task(account_id: int, key: str, coroutine) -> asyncio.Task:
    state = _get_state(account_id)
    task = asyncio.create_task(coroutine)
    state[key] = task

    def cleanup(done: asyncio.Task) -> None:
        if state.get(key) is done:
            state[key] = None
        if done.cancelled():
            return
        error = done.exception()
        if error is not None:
            add_log(account_id, "error", f"Bot background task failed ({key}): {error}")

    task.add_done_callback(cleanup)
    return task


def _cancel_owned_task(task: asyncio.Task | None) -> None:
    if task is None or task.done():
        return
    _stopping_tasks.add(task)
    task.add_done_callback(_stopping_tasks.discard)
    task.cancel()


async def wait_for_bot_tasks() -> None:
    while True:
        pending = [task for task in _stopping_tasks if not task.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


def add_log(account_id: int, level: str, message: str, persist: bool = False) -> None:
    state = _get_state(account_id)
    entry = {"time": _iso(), "level": level, "message": message}
    state["logs"].append(entry)
    if len(state["logs"]) > MAX_LOGS:
        state["logs"].pop(0)
    event_bus.emit("bot:log", {**entry, "accountId": account_id})
    if persist or level in PERSIST_LEVELS:
        try:
            execute("INSERT INTO bot_logs (account_id, level, message, created_at, persist) VALUES (?, ?, ?, ?, ?)",
                    (account_id, level, message, entry["time"], 1 if persist else 0))
        except Exception:  # noqa: BLE001
            pass


async def _filter_tradable(account_id: int, candidates: list[dict]) -> list[dict]:
    filtered = []
    seen: set[str] = set()
    skipped_invalid = 0
    skipped_dup = 0
    for c in candidates:
        c["symbol"] = c["symbol"].upper()
        if c["symbol"] in seen:
            skipped_dup += 1
            continue
        seen.add(c["symbol"])
        if not await is_tradable_linear_symbol(c["symbol"]):
            skipped_invalid += 1
            continue
        filtered.append(c)
    if skipped_invalid:
        add_log(account_id, "info", f"Skipped {skipped_invalid} non-tradable Bybit symbol(s) before analysis")
    if skipped_dup:
        add_log(account_id, "info", f"Skipped {skipped_dup} duplicate candidate(s)")
    return filtered


def _filter_actionable(account_id: int, candidates: list[dict], max_positions: int) -> list[dict]:
    open_rows = query_all("SELECT symbol FROM open_positions WHERE account_id = ?", (account_id,))
    open_symbols = {r["symbol"] for r in open_rows}
    remaining = max(0, max_positions - len(open_rows))
    if remaining <= 0:
        return []
    skipped_open = 0
    actionable = []
    for c in candidates:
        if c["symbol"] in open_symbols:
            skipped_open += 1
            continue
        actionable.append(c)
    if skipped_open:
        add_log(account_id, "info", f"Skipped {skipped_open} candidate(s) with existing open position")
    budget = max(remaining, remaining * 2)
    capped = actionable[:min(MAX_BOT_CANDIDATES, budget)]
    if len(actionable) > len(capped):
        add_log(account_id, "info", f"Candidate cap: {len(capped)}/{len(actionable)} will be analyzed")
    return capped


def _active_rule_keys(signal) -> str:
    return ",".join(f"{r['key']}:{r['score']}" for r in signal.rules if r["score"] != 0)


async def _execute_order_to_completion(account_id: int, params: dict):
    """Keep the bot-level cancellation log while execution owns task shielding."""
    try:
        return await execute_order(params)
    except asyncio.CancelledError:
        add_log(account_id, "warn", "Bot stop requested while an order was in flight; waiting for reconciliation")
        raise


def _trigger_from_alert(a: dict) -> dict:
    src = "sniper" if a["sourceType"] == "4s_sniper" else a["sourceType"]
    return {
        "source": src, "signalType": a["signalType"], "direction": a["direction"],
        "rawMessage": a["rawMessage"], "rsiData": a["rsiData"], "srsiData": a["srsiData"],
        "boostValue": a["boostValue"], "stars": a["stars"],
    }


async def run_bot_cycle(account_id: int) -> None:
    state = _get_state(account_id)
    if state["status"] != "running":
        return
    if state["scanning"]:
        add_log(account_id, "info", "Previous scan still running, skipping")
        return
    state["scanning"] = True
    try:
        await _run_bot_cycle_inner(account_id, state)
    finally:
        state["scanning"] = False


async def _run_bot_cycle_inner(account_id: int, state: dict) -> None:
    bot_config = query_one("SELECT * FROM bot_configs WHERE account_id = ?", (account_id,))
    if not bot_config:
        return
    signal_source = bot_config["signal_source"] or "scanner"
    open_count = query_one("SELECT COUNT(*) as cnt FROM open_positions WHERE account_id = ?", (account_id,))["cnt"]
    if open_count >= bot_config["max_positions"]:
        state["totalScans"] += 1
        state["lastScan"] = _iso()
        add_log(account_id, "info", f"Max positions reached ({open_count}/{bot_config['max_positions']}); skipping new analysis")
        await check_positions(account_id)
        return

    state["totalScans"] += 1
    state["lastScan"] = _iso()
    add_log(account_id, "info", f"Scan started [source: {signal_source}]")

    try:
        candidates: list[dict] = []
        if needs_scanner(signal_source):
            gainers = await get_top_gainers(15)
            for t in gainers[:MAX_SCANNER_CANDIDATES]:
                candidates.append({"symbol": t["symbol"], "source": "scanner", "forcedSide": None, "alertBoost": 0, "trigger": None})
            add_log(account_id, "info", f"Scanner: {len(candidates)} top gainers")

        src_types = get_source_types(signal_source)
        if src_types:
            freshness = bot_config["alert_freshness_minutes"] or 30
            all_alerts = get_recent_alerts(src_types, freshness)
            alerts = all_alerts[:MAX_ALERT_CANDIDATES]
            if len(all_alerts) > len(alerts):
                add_log(account_id, "info", f"Alert cap: {len(alerts)}/{len(all_alerts)} fresh alerts considered", True)

            if is_alert_only(signal_source):
                candidates = [{
                    "symbol": a["symbol"], "source": "alert",
                    "forcedSide": "long" if a["direction"] == "UP" else "short",
                    "alertBoost": 0, "trigger": _trigger_from_alert(a),
                } for a in alerts]
                add_log(account_id, "info", f"Alert candidates: {len(alerts)} from {','.join(src_types)}", True)
            else:
                alert_map: dict[str, dict] = {}
                for a in alerts:
                    if a["symbol"] not in alert_map:
                        alert_map[a["symbol"]] = a
                _boost_raw = bot_config["alert_score_boost"]
                boost = 2.0 if _boost_raw is None else _boost_raw  # 0 gecerli (alarm destegi kapali)
                for c in candidates:
                    matched = alert_map.get(c["symbol"])
                    if matched:
                        c["alertBoost"] = boost
                        c["trigger"] = _trigger_from_alert(matched)
                added = 0
                existing_symbols = {c["symbol"] for c in candidates}
                for a in alerts:
                    if a["symbol"] not in existing_symbols:
                        candidates.append({
                            "symbol": a["symbol"], "source": "alert",
                            "forcedSide": "long" if a["direction"] == "UP" else "short",
                            "alertBoost": 0, "trigger": _trigger_from_alert(a),
                        })
                        existing_symbols.add(a["symbol"])
                        added += 1
                if alerts:
                    add_log(account_id, "info", f"Alerts: {len(alerts)} matched, {added} extra added")

            if not alerts and is_alert_only(signal_source):
                add_log(account_id, "info", f"No fresh alerts (window: {freshness}min)")

        candidates = await _filter_tradable(account_id, candidates)
        candidates = _filter_actionable(account_id, candidates, bot_config["max_positions"])
        add_log(account_id, "info", f"Candidates: {len(candidates)} tradable/actionable symbols")

        enabled = bot_config["enabled_rules"]
        enabled_rules = [] if enabled == "__none__" else (enabled.split(",") if enabled else None)

        for candidate in candidates:
            if state["status"] != "running":
                break
            try:
                signal = await analyze_symbol(candidate["symbol"], enabled_rules, account_id, candidate.get("trigger"))
                adjusted_score = signal.total_score
                if candidate["alertBoost"] > 0:
                    trig = candidate.get("trigger") or {}
                    alert_side = "long" if trig.get("direction") == "UP" else "short" if trig.get("direction") == "DOWN" else None
                    score_side = "long" if signal.total_score >= 0 else "short"
                    if not alert_side or alert_side == score_side:
                        adjusted_score += candidate["alertBoost"]
                        add_log(account_id, "info", f"{candidate['symbol']}: score {signal.total_score} + boost {candidate['alertBoost']} = {adjusted_score}")

                side = candidate["forcedSide"] or signal.side
                if side == "neutral":
                    continue

                state["totalSignals"] += 1
                add_log(account_id, "info", f"Signal: {candidate['symbol']} score={adjusted_score} side={side} [{candidate['source']}]")

                # Hesap kilidi: risk-kontrol + emir-acma atomik (max_positions yarisini onler).
                async with account_gate(account_id):
                    risk_result = await evaluate_risk({
                        "accountId": account_id, "symbol": candidate["symbol"], "side": side,
                        "score": adjusted_score, "price": signal.market_data.ticker["lastPrice"],
                    })
                    if not risk_result["approved"]:
                        add_log(account_id, "info", f"Risk rejected {candidate['symbol']}: {risk_result['reason']}")
                        event_bus.emit("risk:rejected", {"symbol": candidate["symbol"], "reason": risk_result["reason"]})
                        continue

                    trig = candidate.get("trigger") or {}
                    trigger_src = trig.get("source")
                    entry_reason = (f"scanner+{trigger_src}" if candidate["source"] == "scanner" else trigger_src) if trigger_src else candidate["source"]

                    order_result = await _execute_order_to_completion(account_id, {
                        "accountId": account_id, "symbol": candidate["symbol"], "side": side,
                        "size": risk_result["size"], "leverage": risk_result["leverage"],
                        "tpPercent": bot_config["tp_percent"], "slPercent": bot_config["sl_percent"],
                        "signalScore": adjusted_score, "activeRules": _active_rule_keys(signal),
                        "entryReason": entry_reason, "triggerSource": trigger_src,
                        "triggerStars": trig.get("stars"),
                        "minScoreUsed": bot_config["long_min_score"] if side == "long" else bot_config["short_min_score"],
                    })
                if order_result.success:
                    state["totalOrders"] += 1
                    add_log(account_id, "info", f"Order filled: {side} {candidate['symbol']} @ {order_result.fill_price}")
                else:
                    # Cooldown: ayni sembol her taramada yeniden denenip ayni hatayi
                    # uretmesin (kalici emir redleri gunlerce log/API spam'i yapiyordu).
                    set_cooldown(account_id, candidate["symbol"])
                    add_log(account_id, "error", f"Order failed: {candidate['symbol']} - {order_result.error} (15m cooldown)")
            except Exception as err:  # noqa: BLE001
                detail = str(err) or type(err).__name__  # bos mesajli (httpx timeout vb.) hatalari acikla
                add_log(account_id, "error", f"Analysis failed for {candidate['symbol']}: {detail}")
                log.error(f"Analysis failed for {candidate['symbol']} (acc {account_id}): {type(err).__name__}: {err!r}\n{traceback.format_exc()}")

        await check_positions(account_id)
        add_log(account_id, "info", "Scan complete")
    except Exception as err:  # noqa: BLE001
        add_log(account_id, "error", f"Scan cycle error: {err}")


async def _scan_loop(account_id: int, interval_sec: int) -> None:
    state = _get_state(account_id)
    while state["status"] == "running":
        await asyncio.sleep(interval_sec)
        if state["status"] != "running":
            break
        try:
            await run_bot_cycle(account_id)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001 - tek tik hatasi tarama dongusunu oldurmesin (zombi bot)
            add_log(account_id, "error", f"Scan cycle crashed; loop continues: {err}")
            log.error(f"Scan loop tick failed for account {account_id}: {err}")


async def _snapshot_loop(account_id: int) -> None:
    state = _get_state(account_id)
    while state["status"] == "running":
        await asyncio.sleep(60)
        if state["status"] != "running":
            break
        try:
            await take_equity_snapshot(account_id)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            add_log(account_id, "error", f"Equity snapshot failed: {err}")


async def _take_initial_snapshot(account_id: int) -> None:
    try:
        await take_equity_snapshot(account_id)
    except asyncio.CancelledError:
        raise
    except Exception as err:  # noqa: BLE001
        add_log(account_id, "error", f"Initial equity snapshot failed: {err}")


def start_bot(account_id: int) -> dict:
    state = _get_state(account_id)
    if state["status"] == "running":
        return {"success": True}
    account = query_one("SELECT * FROM accounts WHERE id = ?", (account_id,))
    if not account:
        return {"success": False, "error": "Account not found"}
    bot_config = query_one("SELECT * FROM bot_configs WHERE account_id = ?", (account_id,))
    if not bot_config:
        return {"success": False, "error": "No bot config"}

    engine = get_engine(account["engine"])
    set_engine(account_id, engine)
    try:
        execute("UPDATE bot_configs SET bot_enabled = 1 WHERE account_id = ?", (account_id,))
    except Exception as err:  # noqa: BLE001
        log.error(f"Bot start persistence failed for account {account_id}: {err}")
        return {"success": False, "error": "Bot could not be enabled in persistent storage"}

    state["status"] = "running"
    state["startedAt"] = _iso()
    state["totalScans"] = 0
    state["totalSignals"] = 0
    state["totalOrders"] = 0
    # Temiz tarama bayragi: hizli stop->start (apply) sonrasi iptal edilen eski cycle
    # ile yeni cycle ayni 'scanning' bayragini paylasinca takilip kaliyordu -> yeni scan
    # loop her turda "skipping" deyip hic taramaz (bot calisir gorunur ama olu).
    state["scanning"] = False
    state["logs"] = []

    try:
        add_log(account_id, "info", f"Engine: {engine.name}")
        start_telegram_notifications(account_id)
        add_log(account_id, "info", f"Bot started for account \"{account['name']}\" (ID: {account_id})")
        add_log(account_id, "info", f"Signal source: {bot_config['signal_source'] or 'scanner'}")

        _own_task(account_id, "cycle_task", run_bot_cycle(account_id))
        scan_interval_sec = max(MIN_BOT_SCAN_INTERVAL_SEC, bot_config["scan_interval"] or 30)
        _own_task(account_id, "scan_task", _scan_loop(account_id, scan_interval_sec))
        start_monitor(account_id, 5000)
        _own_task(account_id, "snapshot_task", _snapshot_loop(account_id))
        _own_task(account_id, "initial_snapshot_task", _take_initial_snapshot(account_id))
    except Exception as err:  # noqa: BLE001
        state["status"] = "stopped"
        for key in ("cycle_task", "scan_task", "snapshot_task", "initial_snapshot_task"):
            _cancel_owned_task(state.get(key))
            state[key] = None
        try:
            stop_monitor(account_id)
        except Exception:  # noqa: BLE001
            pass
        try:
            stop_telegram_notifications(account_id)
        except Exception:  # noqa: BLE001
            pass
        try:
            execute("UPDATE bot_configs SET bot_enabled = 0 WHERE account_id = ?", (account_id,))
        except Exception as rollback_err:  # noqa: BLE001
            log.error(f"Bot start rollback persistence failed for account {account_id}: {rollback_err}")
        log.error(f"Bot start failed for account {account_id}: {err}")
        return {"success": False, "error": "Bot background services could not be started"}

    log.info(f"Bot started for account {account_id}")
    event_bus.emit("bot:started", {"accountId": account_id})
    return {"success": True}


def stop_bot(account_id: int, preserve_enabled: bool = False) -> dict:
    state = _get_state(account_id)
    was_running = state["status"] == "running"
    state["status"] = "stopped"
    state["scanning"] = False  # iptal edilen cycle'in bayragi takili kalmasin
    for key in ("cycle_task", "scan_task", "snapshot_task", "initial_snapshot_task"):
        task = state.get(key)
        _cancel_owned_task(task)
        state[key] = None
    stop_monitor(account_id)
    stop_telegram_notifications(account_id)
    if not preserve_enabled:
        execute("UPDATE bot_configs SET bot_enabled = 0 WHERE account_id = ?", (account_id,))
    if was_running:
        add_log(account_id, "info", "Bot stopped")
        log.info(f"Bot stopped for account {account_id}")
        event_bus.emit("bot:stopped", {"accountId": account_id})
    return {"success": True}


def stop_all_bots(preserve_enabled: bool = False) -> None:
    for account_id, state in list(_bots.items()):
        if state["status"] == "running":
            stop_bot(account_id, preserve_enabled)


def get_bot_status(account_id: int) -> dict:
    state = _get_state(account_id)
    return {
        "status": state["status"], "accountId": state["accountId"], "startedAt": state["startedAt"],
        "totalScans": state["totalScans"], "totalSignals": state["totalSignals"],
        "totalOrders": state["totalOrders"], "lastScan": state["lastScan"],
        "monitorRunning": is_monitor_running(account_id),
    }


def get_all_bot_statuses() -> list[dict]:
    return [get_bot_status(aid) for aid, s in _bots.items() if s["status"] == "running"]


def get_bot_logs(account_id: int, limit: int = 50, offset: int = 0) -> list[dict]:
    safe_limit = min(max(int(limit or 50), 1), 10000)
    safe_offset = max(int(offset or 0), 0)
    rows = query_all("SELECT level, message, created_at as time FROM bot_logs WHERE account_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                     (account_id, safe_limit, safe_offset))
    return [dict(r) for r in reversed(rows)]


def auto_start_bots() -> None:
    filtered = query_all("SELECT account_id FROM bot_configs WHERE bot_enabled = 1")
    if not filtered:
        return
    log.info(f"Auto-starting {len(filtered)} bot(s)")
    for row in filtered:
        result = start_bot(row["account_id"])
        if not result["success"]:
            log.error(f"Auto-start failed for account {row['account_id']}: {result.get('error')}")
