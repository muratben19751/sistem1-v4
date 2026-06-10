import asyncio
import json
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect

from .core.logger import create_logger
from .core.event_bus import event_bus
from .db.database import query_one
from .middleware.auth import is_auth_token_valid

log = create_logger("websocket")

_clients: set[WebSocket] = set()
_loop: asyncio.AbstractEventLoop | None = None
_event_handlers: dict[str, object] = {}
_broadcast_queue: asyncio.Queue | None = None
_broadcast_task: asyncio.Task | None = None
_dropped_messages = 0
MAX_BROADCAST_QUEUE = 1000
SEND_TIMEOUT_SEC = 2.0

EVENTS = [
    "scan:complete", "signal:generated", "risk:approved", "risk:rejected",
    "order:placed", "order:filled", "position:opened", "position:closed",
    "position:updated", "alert:received", "learning:updated",
    "bot:log", "bot:started", "bot:stopped", "risk:circuit_breaker",
    "delist:new", "delist:escalated",
    "optimizer:log", "optimizer:progress", "optimizer:cycle-complete",
]


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_safe_int(value, fallback=0) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return fallback


def _sanitize(event: str, data):
    if event == "optimizer:log":
        obj = data if isinstance(data, dict) else {}
        return {"level": obj.get("level", "info"), "message": obj.get("message", str(data or "")), "time": obj.get("time", _iso())}
    if event == "optimizer:progress":
        obj = data if isinstance(data, dict) else {}
        return {"generation": _to_safe_int(obj.get("generation")), "index": _to_safe_int(obj.get("index")),
                "total": _to_safe_int(obj.get("total")), "name": obj.get("name", "") if isinstance(obj.get("name"), str) else ""}
    if event == "optimizer:cycle-complete":
        obj = data if isinstance(data, dict) else {}
        return {"generation": _to_safe_int(obj.get("generation"))}
    return data


async def _broadcast(message: dict) -> None:
    try:
        payload = json.dumps(message, default=str)
    except Exception as err:  # noqa: BLE001
        log.warn(f"WebSocket payload serialization failed: {err}")
        return
    async def send(ws: WebSocket) -> None:
        try:
            await asyncio.wait_for(ws.send_text(payload), timeout=SEND_TIMEOUT_SEC)
        except Exception:  # noqa: BLE001
            _clients.discard(ws)

    if _clients:
        await asyncio.gather(*(send(ws) for ws in list(_clients)))


async def _broadcast_worker() -> None:
    assert _broadcast_queue is not None
    while True:
        message = await _broadcast_queue.get()
        try:
            await _broadcast(message)
        finally:
            _broadcast_queue.task_done()


def _enqueue_message(message: dict) -> None:
    global _dropped_messages
    if _broadcast_queue is None:
        return
    try:
        _broadcast_queue.put_nowait(message)
    except asyncio.QueueFull:
        _dropped_messages += 1
        if _dropped_messages == 1 or _dropped_messages % 100 == 0:
            log.warn(f"WebSocket broadcast queue full; dropped {_dropped_messages} message(s)")


def _make_handler(event: str):
    def handler(data):
        if _loop is None:
            return
        msg = {"type": event, "data": _sanitize(event, data), "timestamp": _iso()}
        _loop.call_soon_threadsafe(_enqueue_message, msg)
    return handler


def init_event_bridge(loop: asyncio.AbstractEventLoop) -> None:
    global _loop, _broadcast_queue, _broadcast_task
    _loop = loop
    if _broadcast_task is not None:
        _broadcast_task.cancel()
    _broadcast_queue = asyncio.Queue(maxsize=MAX_BROADCAST_QUEUE)
    _broadcast_task = asyncio.create_task(_broadcast_worker())
    event_bus.set_loop(loop)
    for event in EVENTS:
        old_handler = _event_handlers.get(event)
        if old_handler is not None:
            event_bus.off(event, old_handler)
        handler = _make_handler(event)
        _event_handlers[event] = handler
        event_bus.on(event, handler)
    log.info("WebSocket event bridge initialized")


async def close_event_bridge() -> None:
    global _loop, _broadcast_queue, _broadcast_task
    for event, handler in list(_event_handlers.items()):
        event_bus.off(event, handler)
    _event_handlers.clear()
    if _broadcast_task is not None:
        _broadcast_task.cancel()
        try:
            await _broadcast_task
        except asyncio.CancelledError:
            pass
    _broadcast_task = None
    _broadcast_queue = None
    _loop = None


async def websocket_endpoint(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token") or websocket.cookies.get("sistem1_auth")
    if not is_auth_token_valid(token):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    _clients.add(websocket)
    log.info("Client connected")
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong", "ts": msg.get("ts")}))
            except Exception:  # noqa: BLE001
                pass
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)
        log.info("Client disconnected")


_opt_log_last_time = {"ts": ""}


async def optimizer_log_bridge_loop() -> None:
    while True:
        await asyncio.sleep(2)
        try:
            r = query_one("SELECT value FROM app_config WHERE key = 'optimizer_log'")
            raw = r["value"] if r else None
        except Exception:  # noqa: BLE001
            continue
        if not raw:
            continue
        try:
            entries = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(entries, list) or not entries:
            continue
        last = _opt_log_last_time["ts"]
        fresh = [e for e in entries if e.get("time", "") > last] if last else entries[-5:]
        _opt_log_last_time["ts"] = entries[-1].get("time", "")
        for e in fresh:
            await _broadcast({"type": "optimizer:log", "data": _sanitize("optimizer:log", e), "timestamp": _iso()})
