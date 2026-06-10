import asyncio
import inspect
from collections import defaultdict
from typing import Any, Callable

from .logger import create_logger

log = create_logger("event-bus")


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def on(self, event: str, handler: Callable) -> None:
        self._handlers[event].append(handler)

    def off(self, event: str, handler: Callable) -> None:
        if handler in self._handlers[event]:
            self._handlers[event].remove(handler)

    def _log_async_result(self, event: str, future) -> None:
        # run_coroutine_threadsafe'in concurrent.futures.Future'i icindeki istisna,
        # geri alinmazsa sessizce kaybolur -> done-callback ile logla.
        try:
            err = future.exception()
        except Exception:  # noqa: BLE001 - iptal/zaten-cozulmus
            return
        if err is not None:
            log.error(f"async handler error for {event}: {err}")

    def emit(self, event: str, data: Any = None) -> None:
        for handler in list(self._handlers[event]):
            try:
                if inspect.iscoroutinefunction(handler):
                    if self._loop is not None:
                        fut = asyncio.run_coroutine_threadsafe(handler(data), self._loop)
                        fut.add_done_callback(lambda f, e=event: self._log_async_result(e, f))
                    else:
                        log.warn(f"async handler for '{event}' dropped: no event loop set")
                else:
                    handler(data)
            except Exception as err:  # noqa: BLE001
                log.error(f"handler error for {event}: {err}")


event_bus = EventBus()
