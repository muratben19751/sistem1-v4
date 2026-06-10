from ..core.logger import create_logger

log = create_logger("bybit-ws")

# WebSocket katmani sonraki fazda implemente edilecek. Simdilik no-op stub'lar:
# market verisi REST uzerinden gelir, gercek-zamanli ticker akisi devre disi.

_ticker_callbacks = []


def on_bybit_ticker_update(callback) -> None:
    _ticker_callbacks.append(callback)


def start_bybit_public_ws() -> None:
    pass


def stop_bybit_websockets() -> None:
    pass


# --- Bybit private WS stubs (faz-2'de implemente edilecek) ---
# Henuz private WS yok; bu stub'lar None/no-op donerek engine'i REST fallback
# yollarina zorlar (order-status / execution-list polling + REST position fetch).

def prepare_bybit_private_ws(*a, **k):
    return None


def prime_bybit_private_ws_positions(*a, **k):
    return None


def get_bybit_ws_positions(*a, **k):
    return None


async def wait_for_bybit_ws_fill(*a, **k):
    return None
