import asyncio
import html
import os
from collections.abc import Callable

import httpx

from ..core.config import config
from ..core.event_bus import event_bus
from ..core.logger import create_logger
from ..db.database import query_all, query_one

log = create_logger("telegram-notify")

TELEGRAM_API = "https://api.telegram.org/bot"


def _timeout_sec() -> float:
    try:
        return max(5.0, float(os.environ.get("TELEGRAM_SEND_TIMEOUT_MS") or 10_000) / 1000.0)
    except ValueError:
        return 10.0


SEND_TIMEOUT_SEC = _timeout_sec()

_client: httpx.AsyncClient | None = None
_listeners: dict[int, tuple[Callable, Callable]] = {}
_hourly_tasks: dict[int, asyncio.Task] = {}
_send_tasks: set[asyncio.Task] = set()


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=SEND_TIMEOUT_SEC)
    return _client


def _safe(value) -> str:
    return html.escape(str(value), quote=False)


def _format_pnl(value) -> str:
    try:
        pnl = float(value)
    except (TypeError, ValueError):
        return "-"
    sign = "+" if pnl >= 0 else ""
    return f"{sign}{pnl:.2f} USDT"


async def _send_message(text: str) -> bool:
    token = config.telegram.notify_bot_token
    chat_id = config.telegram.notify_chat_id
    if not token or not chat_id:
        return False
    try:
        response = await _get_client().post(
            f"{TELEGRAM_API}{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        )
        if not response.is_success:
            log.warn(f"Telegram send failed: {response.status_code}")
            return False
        return True
    except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as err:
        log.warn(f"Telegram send failed: {type(err).__name__}")
        return False
    except Exception as err:  # noqa: BLE001
        log.error(f"Telegram send error: {err}")
        return False


def _schedule(coro) -> None:
    try:
        task = asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        coro.close()
        log.warn("Telegram notification skipped: no running event loop")
        return
    _send_tasks.add(task)
    task.add_done_callback(_send_tasks.discard)


def _notify_trade_entry(data: dict) -> None:
    message = "\n".join(
        (
            "<b>POZISYON ACILDI</b>",
            f"Sembol: <b>{_safe(data.get('symbol', '-'))}</b>",
            f"Yon: <b>{_safe(str(data.get('side', '-')).upper())}</b>",
            f"Fiyat: {_safe(data.get('entryPrice') or data.get('fillPrice') or '-')}",
            f"Buyukluk: {_safe(data.get('size') or '-')} USDT",
        )
    )
    _schedule(_send_message(message))


def _notify_trade_exit(data: dict) -> None:
    pnl = data.get("pnl")
    outcome = "KAZANC" if isinstance(pnl, (int, float)) and pnl >= 0 else "KAYIP"
    message = "\n".join(
        (
            f"<b>POZISYON KAPANDI - {outcome}</b>",
            f"Sembol: <b>{_safe(data.get('symbol', '-'))}</b>",
            f"Yon: <b>{_safe(str(data.get('side', '-')).upper())}</b>",
            f"PnL: <b>{_safe(_format_pnl(pnl))}</b>",
            f"Sebep: {_safe(data.get('reason') or '-')}",
        )
    )
    _schedule(_send_message(message))


async def _generate_hourly_report(account_id: int) -> None:
    account = query_one("SELECT name FROM accounts WHERE id = ?", (account_id,))
    if not account:
        return
    wallet = query_one("SELECT balance FROM paper_wallets WHERE account_id = ?", (account_id,))
    positions = query_all("SELECT id FROM open_positions WHERE account_id = ?", (account_id,))
    recent_trades = query_all(
        """
        SELECT pnl, closed_at FROM trades
        WHERE account_id = ? AND status = 'closed' AND date(closed_at) = date('now')
        ORDER BY closed_at DESC
        """,
        (account_id,),
    )
    today_pnl = sum(float(row["pnl"] or 0) for row in recent_trades)
    today_wins = sum(1 for row in recent_trades if float(row["pnl"] or 0) > 0)
    balance = float(wallet["balance"]) if wallet else 0.0
    message = "\n".join(
        (
            "<b>SAATLIK RAPOR</b>",
            f"Hesap: {_safe(account['name'])}",
            f"Bakiye: {balance:.2f} USDT",
            f"Acik Pozisyon: {len(positions)}",
            "",
            "<b>Bugun:</b>",
            f"Trade: {len(recent_trades)}",
            f"PnL: {_safe(_format_pnl(today_pnl))}",
            f"Kazanc: {today_wins}/{len(recent_trades)}",
        )
    )
    await _send_message(message)


async def _hourly_report_loop(account_id: int) -> None:
    try:
        while True:
            await asyncio.sleep(60 * 60)
            await _generate_hourly_report(account_id)
    except asyncio.CancelledError:
        raise


def start_telegram_notifications(account_id: int) -> None:
    if not config.telegram.notify_bot_token or not config.telegram.notify_chat_id:
        log.info("Telegram notifications disabled (no bot token or chat id)")
        return

    stop_telegram_notifications(account_id)

    def entry_handler(data) -> None:
        if isinstance(data, dict) and data.get("accountId") == account_id:
            _notify_trade_entry(data)

    def exit_handler(data) -> None:
        if isinstance(data, dict) and data.get("accountId") == account_id:
            _notify_trade_exit(data)

    _listeners[account_id] = (entry_handler, exit_handler)
    event_bus.on("order:filled", entry_handler)
    event_bus.on("position:closed", exit_handler)
    _hourly_tasks[account_id] = asyncio.create_task(_hourly_report_loop(account_id))
    _schedule(
        _send_message(
            f"<b>Bot baslatildi</b> (Account #{account_id})\nTelegram bildirimleri aktif."
        )
    )
    log.info(f"Telegram notifications started for account {account_id}")


def stop_telegram_notifications(account_id: int | None = None) -> None:
    account_ids = [account_id] if account_id is not None else list(set(_listeners) | set(_hourly_tasks))
    for current_id in account_ids:
        listeners = _listeners.pop(current_id, None)
        if listeners:
            event_bus.off("order:filled", listeners[0])
            event_bus.off("position:closed", listeners[1])
        task = _hourly_tasks.pop(current_id, None)
        if task:
            task.cancel()
    if account_id is not None or account_ids:
        log.info("Telegram notifications stopped")


async def close_telegram_notifications() -> None:
    global _client
    hourly_tasks = list(_hourly_tasks.values())
    stop_telegram_notifications()
    if hourly_tasks:
        await asyncio.gather(*hourly_tasks, return_exceptions=True)
    for task in list(_send_tasks):
        task.cancel()
    if _send_tasks:
        await asyncio.gather(*_send_tasks, return_exceptions=True)
        _send_tasks.clear()
    if _client is not None:
        await _client.aclose()
        _client = None
