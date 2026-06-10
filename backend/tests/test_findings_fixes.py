"""Denetim bulgulari icin eklenen duzeltmelerin testleri (High 1/3, Medium 6)."""
import asyncio
from types import SimpleNamespace

import pytest

from app.db.database import execute, query_one


def _mk_live_account(engine="demo"):
    cur = execute(
        "INSERT INTO accounts (name, type, engine, balance, initial_balance, leverage) VALUES (?, 'demo', ?, 1000, 1000, 2)",
        (f"RT_{engine}", engine),
    )
    aid = cur.lastrowid
    execute(
        "INSERT INTO open_positions (account_id, symbol, side, size, entry_price, mark_price, leverage) VALUES (?, 'BTCUSDT', 'long', 1.0, 100.0, 110.0, 2)",
        (aid,),
    )
    execute(
        "INSERT INTO trades (account_id, symbol, side, size, entry_price, leverage, fee, status) VALUES (?, 'BTCUSDT', 'long', 1.0, 100.0, 2, 0, 'open')",
        (aid,),
    )
    return aid


def _cleanup(aid):
    execute("DELETE FROM open_positions WHERE account_id = ?", (aid,))
    execute("DELETE FROM trades WHERE account_id = ?", (aid,))
    execute("DELETE FROM accounts WHERE id = ?", (aid,))


class TestReconcileLivePositions:
    async def test_delegates_to_guarded_engine_reconciliation_even_without_local_positions(self, db, monkeypatch):
        from app.agents import monitor
        aid = _mk_live_account()
        try:
            execute("DELETE FROM open_positions WHERE account_id = ?", (aid,))
            called = []

            class FakeEngine:
                async def update_mark_prices(self, account_id):
                    called.append(account_id)

            monkeypatch.setattr(monitor, "live_engine_for", lambda name: FakeEngine())
            await monitor.reconcile_live_positions()
            assert aid in called
        finally:
            _cleanup(aid)

    def test_partial_close_splits_closed_leg_and_remaining_open_trade(self, db):
        from app.engines.bybit_engine import _record_partial_close
        aid = _mk_live_account()
        try:
            execute("UPDATE trades SET fee = 1.0 WHERE account_id = ?", (aid,))
            execute(
                "UPDATE open_positions SET unrealized_pnl = 10.0 WHERE account_id = ?",
                (aid,),
            )
            pos = query_one("SELECT * FROM open_positions WHERE account_id = ?", (aid,))
            pnl, pnl_pct, remaining = _record_partial_close(
                aid, pos, 0.4, 110.0, 0.1, "manual_partial"
            )

            assert remaining == pytest.approx(0.6)
            assert pnl == pytest.approx(3.5)
            assert pnl_pct == pytest.approx(17.5)
            open_trade = query_one(
                "SELECT size, fee FROM trades WHERE account_id = ? AND status = 'open'", (aid,)
            )
            open_position = query_one(
                "SELECT size, unrealized_pnl FROM open_positions WHERE account_id = ?", (aid,)
            )
            closed_trade = query_one(
                "SELECT size, fee, pnl, exit_reason FROM trades WHERE account_id = ? AND status = 'closed'", (aid,)
            )
            assert open_trade["size"] == pytest.approx(0.6)
            assert open_trade["fee"] == pytest.approx(0.6)
            assert open_position["size"] == pytest.approx(0.6)
            assert open_position["unrealized_pnl"] == pytest.approx(6.0)
            assert closed_trade["size"] == pytest.approx(0.4)
            assert closed_trade["fee"] == pytest.approx(0.5)
            assert closed_trade["pnl"] == pytest.approx(3.5)
            assert closed_trade["exit_reason"] == "manual_partial"
        finally:
            _cleanup(aid)

    def test_partial_close_uses_exchange_resolved_fee(self, db):
        from app.engines.bybit_engine import _record_partial_close
        aid = _mk_live_account()
        try:
            execute("UPDATE trades SET fee = 1.0 WHERE account_id = ?", (aid,))
            pos = query_one("SELECT * FROM open_positions WHERE account_id = ?", (aid,))
            pnl, _, _ = _record_partial_close(
                aid,
                pos,
                0.4,
                110.0,
                0.1,
                "exchange_partial_sync",
                resolved_pnl=3.2,
                resolved_fee=0.33,
            )

            closed_trade = query_one(
                "SELECT fee, pnl FROM trades WHERE account_id = ? AND status = 'closed'",
                (aid,),
            )
            assert pnl == pytest.approx(3.2)
            assert closed_trade["pnl"] == pytest.approx(3.2)
            assert closed_trade["fee"] == pytest.approx(0.33)
        finally:
            _cleanup(aid)

    async def test_resolve_exchange_close_returns_official_fees(self, monkeypatch):
        from app.engines import bybit_engine

        async def fake_request(_base, _creds, _method, endpoint, _params):
            if endpoint == "/v5/position/closed-pnl":
                return {
                    "list": [{
                        "side": "Sell",
                        "closedSize": "0.4",
                        "avgEntryPrice": "100",
                        "avgExitPrice": "110",
                        "closedPnl": "3.2",
                        "openFee": "0.2",
                        "closeFee": "0.3",
                        "updatedTime": "1000",
                    }]
                }
            return {
                "list": [{
                    "side": "Sell",
                    "closedSize": "0.4",
                    "execTime": "1000",
                    "createType": "CreateByTakeProfit",
                }]
            }

        monkeypatch.setattr(bybit_engine, "_private_request", fake_request)
        result = await bybit_engine._resolve_exchange_close(
            "https://api.example.invalid",
            {"api_key": "key", "api_secret": "secret"},
            "BTCUSDT",
            "long",
            {"exitPrice": 105.0, "pnl": 2.0, "tpPrice": 110.0, "slPrice": 90.0},
            {"size": 0.4, "entryPrice": 100.0, "referenceMs": 1000.0},
        )

        assert result["pnlResolved"] is True
        assert result["pnl"] == pytest.approx(3.2)
        assert result["openFee"] == pytest.approx(0.2)
        assert result["closeFee"] == pytest.approx(0.3)
        assert result["reason"] == "take_profit"


class TestStopBotClearsFlag:
    def test_clears_enabled_when_already_stopped(self, seeded_account):
        from app.services import bot_manager
        execute("UPDATE bot_configs SET bot_enabled = 1 WHERE account_id = ?", (seeded_account,))
        res = bot_manager.stop_bot(seeded_account)
        assert res["success"] is True
        assert query_one("SELECT bot_enabled FROM bot_configs WHERE account_id = ?", (seeded_account,))["bot_enabled"] == 0

    def test_preserve_enabled_keeps_flag(self, seeded_account):
        from app.services import bot_manager
        execute("UPDATE bot_configs SET bot_enabled = 1 WHERE account_id = ?", (seeded_account,))
        bot_manager.stop_bot(seeded_account, preserve_enabled=True)
        assert query_one("SELECT bot_enabled FROM bot_configs WHERE account_id = ?", (seeded_account,))["bot_enabled"] == 1


class TestAccountGate:
    async def test_serializes_per_account(self):
        from app.agents.risk import account_gate
        order = []

        async def worker(tag):
            async with account_gate(999):
                order.append(f"{tag}-in")
                import asyncio
                await asyncio.sleep(0.01)
                order.append(f"{tag}-out")

        import asyncio
        await asyncio.gather(worker("a"), worker("b"))
        # Kilit serilestirir: bir isin in/out'u digerinin arasinda kalmaz.
        assert order in (["a-in", "a-out", "b-in", "b-out"], ["b-in", "b-out", "a-in", "a-out"])


class TestOrderCancellationSafety:
    async def test_inflight_order_finishes_after_outer_task_is_cancelled(self, monkeypatch):
        from app.services import bot_manager

        started = asyncio.Event()
        release = asyncio.Event()
        completed = asyncio.Event()
        expected = SimpleNamespace(success=True)

        async def fake_execute(_params):
            from app.agents.execution import complete_exchange_operation

            async def operation():
                started.set()
                await release.wait()
                completed.set()
                return expected

            return await complete_exchange_operation(operation())

        monkeypatch.setattr(bot_manager, "execute_order", fake_execute)
        task = asyncio.create_task(
            bot_manager._execute_order_to_completion(999, {"symbol": "BTCUSDT"})
        )
        await started.wait()
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert completed.is_set()

    async def test_manual_exchange_operation_finishes_after_request_cancel(self):
        from app.agents.execution import complete_exchange_operation

        started = asyncio.Event()
        release = asyncio.Event()
        completed = asyncio.Event()

        async def operation():
            started.set()
            await release.wait()
            completed.set()
            return "done"

        task = asyncio.create_task(complete_exchange_operation(operation()))
        await started.wait()
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert completed.is_set()

    async def test_monitor_close_finishes_after_monitor_task_is_cancelled(self, monkeypatch):
        from app.agents import execution

        started = asyncio.Event()
        release = asyncio.Event()
        completed = asyncio.Event()
        expected = SimpleNamespace(success=True)

        class FakeEngine:
            async def close_position(self, *_args):
                started.set()
                await release.wait()
                completed.set()
                return expected

        monkeypatch.setattr(execution, "get_engine", lambda _account_id: FakeEngine())
        task = asyncio.create_task(
            execution.close_position(999, "BTCUSDT", "long", "sl_hit", 90.0)
        )
        await started.wait()
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert completed.is_set()

    async def test_manual_tp_sl_finishes_after_request_is_cancelled(self, monkeypatch):
        from app.routes import trading

        started = asyncio.Event()
        release = asyncio.Event()
        completed = asyncio.Event()

        class FakeRequest:
            async def json(self):
                return {"accountId": 1, "symbol": "BTCUSDT", "side": "long", "tp": 120}

        class FakeEngine:
            async def set_tp_sl(self, *_args):
                started.set()
                await release.wait()
                completed.set()

        monkeypatch.setattr(trading, "get_engine_for_account", lambda _account_id: FakeEngine())
        monkeypatch.setattr(
            trading,
            "query_one",
            lambda *_args: {"tp_price": 110.0, "sl_price": 90.0},
        )
        task = asyncio.create_task(trading.set_tp_sl(FakeRequest()))
        await started.wait()
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert completed.is_set()


class TestBotTaskLifecycle:
    async def test_start_does_not_launch_tasks_when_enabled_flag_cannot_persist(self, monkeypatch):
        from app.services import bot_manager

        account_id = 991
        bot_manager._bots.pop(account_id, None)

        def fake_query(sql, _params):
            if "FROM accounts" in sql:
                return {"id": account_id, "name": "Test", "engine": "paper"}
            return {"account_id": account_id, "signal_source": "scanner", "scan_interval": 30}

        monkeypatch.setattr(bot_manager, "query_one", fake_query)
        monkeypatch.setattr(bot_manager, "get_engine", lambda _name: SimpleNamespace(name="paper"))
        monkeypatch.setattr(bot_manager, "set_engine", lambda *_args: None)
        monkeypatch.setattr(
            bot_manager,
            "execute",
            lambda *_args: (_ for _ in ()).throw(RuntimeError("database unavailable")),
        )
        monkeypatch.setattr(
            bot_manager,
            "start_telegram_notifications",
            lambda *_args: pytest.fail("background services must not start"),
        )

        try:
            result = bot_manager.start_bot(account_id)
            state = bot_manager._get_state(account_id)
            assert result["success"] is False
            assert state["status"] == "stopped"
            assert all(
                state[key] is None
                for key in ("cycle_task", "scan_task", "snapshot_task", "initial_snapshot_task")
            )
        finally:
            bot_manager._bots.pop(account_id, None)

    async def test_stop_waits_for_owned_bot_task_cleanup(self, monkeypatch):
        from app.services import bot_manager

        account_id = 992
        started = asyncio.Event()
        cleaned = asyncio.Event()

        async def worker():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                cleaned.set()

        monkeypatch.setattr(bot_manager, "execute", lambda *_args: None)
        monkeypatch.setattr(bot_manager, "stop_monitor", lambda *_args: None)
        monkeypatch.setattr(bot_manager, "stop_telegram_notifications", lambda *_args: None)
        state = bot_manager._get_state(account_id)
        state["status"] = "running"
        task = bot_manager._own_task(account_id, "cycle_task", worker())
        await started.wait()

        try:
            bot_manager.stop_bot(account_id)
            await bot_manager.wait_for_bot_tasks()
            assert task.cancelled()
            assert cleaned.is_set()
        finally:
            bot_manager._bots.pop(account_id, None)
            bot_manager._stopping_tasks.discard(task)


class TestMonitorTaskLifecycle:
    async def test_stop_waits_for_monitor_cleanup(self, monkeypatch):
        from app.agents import monitor

        account_id = 993
        started = asyncio.Event()
        cleaned = asyncio.Event()

        async def blocked_check(_account_id):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                cleaned.set()

        monkeypatch.setattr(monitor, "check_positions", blocked_check)
        monitor.start_monitor(account_id, 5000)
        task = monitor._monitors[account_id]["task"]
        await started.wait()

        try:
            monitor.stop_monitor(account_id)
            await monitor.wait_for_monitor_tasks()
            assert task.cancelled()
            assert cleaned.is_set()
        finally:
            monitor._monitors.pop(account_id, None)
            monitor._stopping_tasks.discard(task)


class TestAuxiliaryTaskLifecycle:
    @staticmethod
    async def _blocked_worker(started: asyncio.Event, cleaned: asyncio.Event):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            cleaned.set()

    async def test_scanner_stop_waits_for_cleanup(self, monkeypatch):
        from app.agents import scanner

        started = asyncio.Event()
        cleaned = asyncio.Event()
        monkeypatch.setattr(
            scanner,
            "run_scan",
            lambda: self._blocked_worker(started, cleaned),
        )
        scanner.start_auto_scan(5)
        task = scanner._scan_task
        await started.wait()

        scanner.stop_auto_scan()
        await scanner.wait_for_auto_scan_shutdown()

        assert task.cancelled()
        assert cleaned.is_set()

    async def test_replica_and_sniper_stops_wait_for_cleanup(self, monkeypatch):
        from app.agents import nw_sniper, replica_channels, replica_compare, replica_tuner

        cases = []
        for module, assign, stop, wait in (
            (
                nw_sniper,
                lambda task: setattr(nw_sniper, "_task", task),
                nw_sniper.stop_nw_sniper,
                nw_sniper.wait_for_nw_sniper_shutdown,
            ),
            (
                replica_channels,
                lambda task: replica_channels._tasks.__setitem__("fr", task),
                replica_channels.stop_replica_channels,
                replica_channels.wait_for_replica_channels_shutdown,
            ),
            (
                replica_compare,
                lambda task: (
                    replica_compare._tasks.__setitem__("fr", task),
                    setattr(replica_compare, "_started", True),
                ),
                replica_compare.stop_replica_compare,
                replica_compare.wait_for_replica_compare_shutdown,
            ),
            (
                replica_tuner,
                lambda task: setattr(replica_tuner, "_task", task),
                replica_tuner.stop_replica_tuner,
                replica_tuner.wait_for_replica_tuner_shutdown,
            ),
        ):
            started = asyncio.Event()
            cleaned = asyncio.Event()
            task = asyncio.create_task(self._blocked_worker(started, cleaned))
            assign(task)
            await started.wait()
            cases.append((task, cleaned, stop, wait))

        monkeypatch.setattr(replica_tuner, "_ensure_state_loaded", lambda: None)
        monkeypatch.setattr(replica_tuner, "_persist_state", lambda: None)
        for task, cleaned, stop, wait in cases:
            stop()
            await wait()
            assert task.cancelled()
            assert cleaned.is_set()

    async def test_telegram_enrichment_tasks_are_cancelled_and_awaited(self, monkeypatch):
        from app.services import telegram_listener

        started = asyncio.Event()
        cleaned = asyncio.Event()

        async def blocked_enrichment(_alert_id, _symbol):
            await self._blocked_worker(started, cleaned)

        monkeypatch.setattr(telegram_listener, "_enrich_bybit_fr", blocked_enrichment)
        telegram_listener.enrich_bybit_fr(1, "BTCUSDT")
        await started.wait()
        task = next(iter(telegram_listener._enrichment_tasks))

        await telegram_listener.cancel_alert_enrichment_tasks()

        assert task.cancelled()
        assert cleaned.is_set()


class TestStartupMaintenanceLifecycle:
    async def test_shutdown_waits_for_thread_wrapper_instead_of_cancelling_it(self):
        from app import main

        started = asyncio.Event()
        release = asyncio.Event()
        completed = asyncio.Event()

        async def maintenance():
            started.set()
            await release.wait()
            completed.set()

        task = asyncio.create_task(maintenance())
        main._startup_maintenance_tasks.append(task)
        await started.wait()
        waiter = asyncio.create_task(main._wait_for_startup_maintenance_tasks())
        await asyncio.sleep(0)
        assert not waiter.done()
        release.set()
        await waiter
        assert completed.is_set()
        assert main._startup_maintenance_tasks == []


class TestReplicaTuner:
    def test_skips_adjustment_until_replica_scan_completes(self, monkeypatch):
        from app.agents import replica_tuner

        monkeypatch.setattr(replica_tuner, "MIN_REAL", 1)
        monkeypatch.setattr(replica_tuner, "WINDOW_MIN", 120)
        decision = replica_tuner._decide(
            {
                "channel": "fr",
                "realSymbols": 10,
                "replicaSymbols": 0,
                "matched": 0,
                "realLatestTs": 1_000,
                "replicaLatestTs": None,
                "replicaScanCompletedTs": None,
            },
            10_000,
        )

        assert decision["action"] == "skip"
        assert decision["reason"] == "replica_tarama_hazir_degil"

    def test_state_load_can_retry_after_transient_database_error(self, monkeypatch):
        from app.agents import replica_tuner

        calls = 0

        def fake_query(_sql, _params):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("database temporarily unavailable")
            return None

        monkeypatch.setattr(replica_tuner, "_state_loaded", False)
        monkeypatch.setattr(replica_tuner, "query_one", fake_query)
        replica_tuner._ensure_state_loaded()
        assert replica_tuner._state_loaded is False
        replica_tuner._ensure_state_loaded()
        assert replica_tuner._state_loaded is True
        assert calls == 2


class TestReplicaTaskLifecycle:
    async def test_failed_channel_ingest_does_not_consume_cooldown(self, monkeypatch):
        from app.agents import replica_buffer, replica_channels

        replica_buffer._last_emit.clear()
        monkeypatch.setattr(replica_channels, "process_incoming_alert", lambda *_args, **_kwargs: None)
        signal = {"raw": "unparseable", "symbol": "BTCUSDT", "direction": "UP"}

        accepted = await replica_channels._ingest(signal, "hammer_local", False, 60_000)

        assert accepted is False
        assert "hammer|BTCUSDT|UP" not in replica_buffer._last_emit

    async def test_failed_sniper_ingest_does_not_consume_cooldown(self, monkeypatch):
        from app.agents import nw_sniper, replica_buffer

        replica_buffer._last_emit.clear()

        async def one_symbol():
            return ["BTCUSDT"]

        async def one_signal(_symbol):
            return {
                "raw": "unparseable",
                "symbol": "BTCUSDT",
                "direction": "UP",
                "strategy": "test",
            }

        monkeypatch.setattr(nw_sniper, "_pick_universe", one_symbol)
        monkeypatch.setattr(nw_sniper, "_analyze", one_signal)
        monkeypatch.setattr(nw_sniper, "process_incoming_alert", lambda *_args, **_kwargs: None)

        signals = await nw_sniper.run_nw_sniper_scan()

        assert len(signals) == 1
        assert "sniper|BTCUSDT|UP" not in replica_buffer._last_emit

    async def test_failed_channel_scan_does_not_record_completion(self, monkeypatch):
        from app.agents import replica_buffer, replica_channels

        replica_buffer._last_scan.pop("fr", None)

        async def fail_universe():
            raise RuntimeError("temporary API failure")

        monkeypatch.setattr(replica_channels, "_liquid_universe", fail_universe)
        with pytest.raises(RuntimeError, match="temporary API failure"):
            await replica_channels.run_fr_scan()

        assert replica_channels._running["fr"] is False
        assert replica_buffer.get_replica_scan_time("fr") is None

    async def test_failed_sniper_scan_does_not_record_completion(self, monkeypatch):
        from app.agents import nw_sniper, replica_buffer

        replica_buffer._last_scan.pop("sniper", None)

        async def fail_universe():
            raise RuntimeError("temporary API failure")

        monkeypatch.setattr(nw_sniper, "_pick_universe", fail_universe)
        assert await nw_sniper.run_nw_sniper_scan() == []
        assert nw_sniper._scanning is False
        assert replica_buffer.get_replica_scan_time("sniper") is None

    async def test_periodic_channel_retries_after_transient_error(self):
        from app.agents import replica_channels

        retried = asyncio.Event()
        calls = 0

        async def flaky_scan():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("temporary API failure")
            retried.set()

        task = asyncio.create_task(replica_channels._periodic(flaky_scan, 0))
        try:
            await asyncio.wait_for(retried.wait(), timeout=1)
            assert calls >= 2
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    async def test_finished_channel_task_is_not_reported_running(self, monkeypatch):
        from app.agents import replica_channels

        done_task = asyncio.create_task(asyncio.sleep(0))
        await done_task
        monkeypatch.setitem(replica_channels._tasks, "fr", done_task)
        monkeypatch.setitem(replica_channels._tasks, "hammer", None)
        monkeypatch.setitem(replica_channels._tasks, "m1", None)

        assert replica_channels.are_replica_channels_running() is False

    async def test_auto_scanner_retries_and_done_task_is_not_running(self, monkeypatch):
        from app.agents import scanner

        retried = asyncio.Event()
        calls = 0

        async def flaky_scan():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("temporary API failure")
            retried.set()
            return {}

        monkeypatch.setattr(scanner, "run_scan", flaky_scan)
        task = asyncio.create_task(scanner._auto_scan_loop(0))
        scanner._scan_task = task
        try:
            await asyncio.wait_for(retried.wait(), timeout=1)
        finally:
            scanner._scan_task = None
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert calls >= 2
        done_task = asyncio.create_task(asyncio.sleep(0))
        await done_task
        scanner._scan_task = done_task
        try:
            assert scanner.is_scan_running() is False
        finally:
            scanner._scan_task = None

    async def test_finished_tuner_task_is_not_reported_running(self, monkeypatch):
        from app.agents import replica_tuner

        done_task = asyncio.create_task(asyncio.sleep(0))
        await done_task
        monkeypatch.setattr(replica_tuner, "_task", done_task)
        monkeypatch.setattr(replica_tuner, "_ensure_state_loaded", lambda: None)

        assert replica_tuner.tuner_state()["running"] is False

    async def test_global_price_loop_retries_after_tick_failure(self, monkeypatch):
        from app.agents import monitor

        retried = asyncio.Event()
        calls = 0

        async def flaky_tick():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("temporary database failure")
            retried.set()

        async def no_reconcile():
            return None

        monkeypatch.setattr(monitor, "_global_tick", flaky_tick)
        monkeypatch.setattr(monitor, "reconcile_live_positions", no_reconcile)
        monitor._global_running["flag"] = True
        task = asyncio.create_task(monitor._global_loop(0))
        try:
            await asyncio.wait_for(retried.wait(), timeout=1)
            assert calls >= 2
        finally:
            monitor._global_running["flag"] = False
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


class TestOptimizerTaskLifecycle:
    def test_process_pool_workers_are_terminated(self, monkeypatch):
        from app.agents import backtest_optimizer

        class FakePool:
            def __init__(self):
                self.terminated = False

            def terminate_workers(self):
                self.terminated = True

        pool = FakePool()
        monkeypatch.setattr(backtest_optimizer, "_pool", pool)

        backtest_optimizer._shutdown_pool()

        assert pool.terminated is True
        assert backtest_optimizer._pool is None

    async def test_stop_cancels_owned_optimizer_loop(self, monkeypatch):
        from app.agents import backtest_optimizer

        started = asyncio.Event()
        cleaned = asyncio.Event()

        async def fake_loop():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                cleaned.set()

        monkeypatch.setattr(backtest_optimizer, "loop", fake_loop)
        monkeypatch.setattr(backtest_optimizer, "persist_status", lambda: None)
        monkeypatch.setattr(backtest_optimizer, "emit_log", lambda *_args: None)
        monkeypatch.setattr(backtest_optimizer, "population", [object()])
        monkeypatch.setattr(backtest_optimizer, "running", False)
        monkeypatch.setattr(backtest_optimizer, "_optimizer_loop_task", None)

        backtest_optimizer.start_backtest_optimizer()
        task = backtest_optimizer._optimizer_loop_task
        assert task is not None
        await started.wait()

        backtest_optimizer.stop_backtest_optimizer()
        await backtest_optimizer.wait_for_optimizer_shutdown()
        assert task.cancelled()
        assert cleaned.is_set()
        assert backtest_optimizer._optimizer_loop_task is None
        assert backtest_optimizer.running is False


class TestBacktestTaskLifecycle:
    async def test_shutdown_cancels_owned_backtest_jobs(self, monkeypatch):
        from app.routes import backtest

        started = asyncio.Event()
        job = {
            "id": "shutdown-test",
            "status": "running",
            "progress": {},
            "result": None,
            "error": None,
        }

        async def slow_backtest(_params):
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(backtest, "run_backtest", slow_backtest)
        task = asyncio.create_task(
            backtest._run_job(job, 1, {}, "Test", 0, 1, None, 1, None, None, [])
        )
        backtest._job_tasks.add(task)
        task.add_done_callback(backtest._job_tasks.discard)
        await started.wait()

        await backtest.cancel_backtest_jobs()

        assert task.cancelled()
        assert job["status"] == "cancelled"
        assert not backtest._job_tasks


class TestBybitReconciliationCounters:
    def test_prunes_counters_outside_current_position_lifecycle(self):
        from app.engines import bybit_engine

        account_id = 987654
        prefix = f"{account_id}:"
        keep_missing = f"{prefix}position:101"
        drop_missing = f"{prefix}position:99"
        keep_orphan = f"{prefix}SOLUSDT:short"
        drop_orphan = f"{prefix}XRPUSDT:long"
        bybit_engine._missing_remote_positions.update({
            keep_missing: 2,
            drop_missing: 2,
        })
        bybit_engine._orphan_remote_positions.update({
            keep_orphan: 1,
            drop_orphan: 1,
        })
        try:
            bybit_engine._prune_reconciliation_counters(
                account_id,
                {101},
                {"BTCUSDT:long", "SOLUSDT:short"},
                {"BTCUSDT:long"},
            )

            assert bybit_engine._missing_remote_positions.get(keep_missing) == 2
            assert drop_missing not in bybit_engine._missing_remote_positions
            assert bybit_engine._orphan_remote_positions.get(keep_orphan) == 1
            assert drop_orphan not in bybit_engine._orphan_remote_positions
        finally:
            for store in (
                bybit_engine._missing_remote_positions,
                bybit_engine._orphan_remote_positions,
            ):
                for key in list(store):
                    if key.startswith(prefix):
                        store.pop(key, None)

    def test_missing_counter_key_changes_with_position_lifecycle(self):
        from app.engines.bybit_engine import _missing_position_key

        assert _missing_position_key(7, 101) != _missing_position_key(7, 102)

    def test_exchange_error_status_requires_reconciliation_after_fill(self):
        from app.engines.bybit_engine import _exchange_error_status

        assert _exchange_error_status(False) == "failed"
        assert _exchange_error_status(True) == "reconcile_required"

    def test_exchange_order_audit_failure_aborts_before_submission(self, monkeypatch):
        from app.engines import bybit_engine

        def fail_execute(*_args, **_kwargs):
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(bybit_engine, "execute", fail_execute)
        with pytest.raises(RuntimeError, match="audit record failed"):
            bybit_engine._record_exchange_order(
                1, "BTCUSDT", "long", "open", "s1-open-test", 0.1
            )


class TestTrailingStop:
    async def test_live_trailing_stop_is_sent_to_exchange(self, seeded_account):
        from app.agents.monitor import _update_trailing_stop

        execute(
            """
            INSERT INTO open_positions (
              account_id, symbol, side, size, entry_price, mark_price, leverage,
              tp_price, sl_price, trailing_stop, trailing_highest
            ) VALUES (?, 'BTCUSDT', 'long', 1, 100, 110, 2, 120, 95, 1, 105)
            """,
            (seeded_account,),
        )
        calls = []

        class FakeEngine:
            async def set_tp_sl(self, account_id, symbol, side, tp, sl):
                calls.append((account_id, symbol, side, tp, sl))
                execute(
                    "UPDATE open_positions SET tp_price = ?, sl_price = ? WHERE account_id = ? AND symbol = ? AND side = ?",
                    (tp, sl, account_id, symbol, side),
                )

        try:
            pos = query_one(
                "SELECT * FROM open_positions WHERE account_id = ? AND symbol = 'BTCUSDT'",
                (seeded_account,),
            )
            await _update_trailing_stop(pos, 110.0, seeded_account, FakeEngine())
            assert calls
            assert calls[0][4] > 95
            updated = query_one(
                "SELECT sl_price, trailing_highest FROM open_positions WHERE id = ?", (pos["id"],)
            )
            assert updated["sl_price"] == pytest.approx(calls[0][4])
            assert updated["trailing_highest"] == pytest.approx(110.0)
        finally:
            execute("DELETE FROM open_positions WHERE account_id = ? AND symbol = 'BTCUSDT'", (seeded_account,))


# --- Code-review (Haziran 2026) ek bulgu duzeltmeleri ---

class TestCodeReviewFixes:
    def test_simulate_exit_no_tp_or_no_sl_does_not_crash(self, monkeypatch):
        """HIGH: simulate_exit tp_price/sl_price None iken TypeError vermemeli (v3: low<=null=false)."""
        from app.lib.indicators import Kline
        from app.engines import backtest_engine

        bars = [
            Kline(time=1000, open=100.0, high=120.0, low=80.0, close=110.0, volume=1.0),
            Kline(time=1300, open=110.0, high=130.0, low=90.0, close=120.0, volume=1.0),
        ]
        monkeypatch.setattr(backtest_engine, "get_forward_klines", lambda *a, **k: bars)
        cfg = {"trailingStop": False, "trailingPercent": 0}

        # SL yok (None) -> sadece TP kontrol edilir, cokme olmamali
        out = backtest_engine.simulate_exit("BTCUSDT", "long", 999, 100.0, 105.0, None, "5", 10_000, 0.0, cfg)
        assert out is not None and out["reason"] in ("tp_hit", "window_end")

        # TP yok (None) -> sadece SL kontrol edilir
        out2 = backtest_engine.simulate_exit("BTCUSDT", "long", 999, 100.0, None, 85.0, "5", 10_000, 0.0, cfg)
        assert out2 is not None and out2["reason"] in ("sl_hit", "window_end")

        # Hem TP hem SL yok -> window_end, cokme yok
        out3 = backtest_engine.simulate_exit("BTCUSDT", "short", 999, 100.0, None, None, "5", 10_000, 0.0, cfg)
        assert out3 is not None and out3["reason"] == "window_end"

    def test_swing_high_rsi_none_for_negative_offset_index(self):
        """HIGH: i-offset<0 olan swing noktalari gelecek-bar RSI'ina SARMAMALI (v3: undefined)."""
        from app.lib.indicators import _find_swing_highs

        prices = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
                  9, 8, 7, 6, 7, 8, 9, 10, 11, 10, 9, 8, 7, 6]
        rsi_series = [50, 51, 52, 53, 54, 55, 56, 57, 58, 59]  # offset = 24-10 = 14
        pts = _find_swing_highs(prices, rsi_series, 5, 14)
        by_idx = {p["index"]: p for p in pts}
        assert 9 in by_idx and by_idx[9]["rsi"] is None          # i-offset=-5 -> None
        assert 18 in by_idx and by_idx[18]["rsi"] == 54          # i-offset=4 -> rsi_series[4]

    def test_detect_rsi_divergence_short_series_no_crash(self):
        from app.lib.indicators import Kline, detect_rsi_divergence
        kl = [Kline(time=i, open=100 + i, high=101 + i, low=99 + i, close=100 + (i % 7), volume=1.0)
              for i in range(40)]
        res = detect_rsi_divergence(kl)
        assert res["type"] in ("none", "bullish", "bearish", "forming_bullish", "forming_bearish")

    def test_time_based_rules_use_eval_ms(self):
        """MED: 16/17 kurallari backtest'te sinyal anini (eval_ms) kullanmali, kosum saatini degil."""
        from datetime import datetime, timezone
        from app.strategies.rules.rule_interface import MarketData
        from app.strategies.rules.rule_16_fr_settlement_timing import rule_16_fr_settlement_timing

        # 02:00 UTC -> EN IYI saat (+2). Kosum saatinden bagimsiz olmali.
        ts = int(datetime(2025, 6, 2, 2, 30, tzinfo=timezone.utc).timestamp() * 1000)
        md = MarketData(symbol="BTCUSDT", eval_ms=ts)
        res = rule_16_fr_settlement_timing.evaluate(md)
        assert res.score == 2

    def test_js_round_parity_half_up(self):
        from app.agents.strategy import _round2
        assert _round2(1.125) == 1.13   # banker's olsa 1.12 olurdu
        assert _round2(0.625) == 0.63   # banker's olsa 0.62 olurdu
