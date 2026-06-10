import array
import math
import os
import sqlite3

from ..core.logger import create_logger
from ..core.time import now_ms
from ..db.database import DB_PATH, query_all, query_one, transaction
from ..lib.indicators import Kline
from .bybit_api import get_klines_range

log = create_logger("kline-cache")

INTERVAL_MS: dict[str, int] = {
    "1": 60_000,
    "3": 180_000,
    "5": 300_000,
    "15": 900_000,
    "30": 1_800_000,
    "60": 3_600_000,
    "120": 7_200_000,
    "240": 14_400_000,
    "D": 86_400_000,
    "W": 604_800_000,
}


def interval_ms(interval: str) -> int:
    return INTERVAL_MS.get(interval, 60_000)


SQL_META = "SELECT covered_start, covered_end FROM kline_cache_meta WHERE symbol = ? AND interval = ?"
SQL_INSERT = "INSERT OR IGNORE INTO kline_cache (symbol, interval, open_time, o, h, l, c, v) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
SQL_UPSERT_META = """
      INSERT INTO kline_cache_meta (symbol, interval, covered_start, covered_end, updated_at)
      VALUES (?, ?, ?, ?, datetime('now'))
      ON CONFLICT(symbol, interval) DO UPDATE SET covered_start = excluded.covered_start, covered_end = excluded.covered_end, updated_at = datetime('now')
    """
SQL_SELECT_BACK = "SELECT open_time, o, h, l, c, v FROM kline_cache WHERE symbol = ? AND interval = ? AND open_time <= ? ORDER BY open_time DESC LIMIT ?"
SQL_SELECT_FORWARD = "SELECT open_time, o, h, l, c, v FROM kline_cache WHERE symbol = ? AND interval = ? AND open_time > ? AND open_time <= ? ORDER BY open_time ASC"
SQL_SELECT_ALL = "SELECT open_time, o, h, l, c, v FROM kline_cache WHERE symbol = ? AND interval = ? ORDER BY open_time ASC"


# In-heap kline cache (sadece optimizer worker'inda aktif). Pencere sabit ve gecmis
# kline'lar degismedigi icin (symbol, interval) serisini bir kez materialize edip
# binary-search ile dilimleriz: SQLite round-trip + mapRows().reverse() churn'u kalkar.
# Veri KOLONSAL array('d') olarak tutulur (bar basina ~48B; object-array'e gore ~5.6x
# az) -> tum sembol seti her worker'da kompakt durur. ensureKlineRange yeni satir
# ekledigi anda ilgili anahtar invalidate edilir -> SQLite ile birebir tutarli.
# HEAP_MAX_BARS bellek tavanini korur (asilirsa SQLite'a duser).
class HeapCols:
    __slots__ = ("times", "o", "h", "l", "c", "v")

    def __init__(self, times, o, h, l, c, v):
        self.times = times
        self.o = o
        self.h = h
        self.l = l
        self.c = c
        self.v = v


_heap_enabled = False
_heap_store: dict[str, HeapCols] = {}
_heap_bars = 0
HEAP_MAX_BARS = max(100_000, int(os.environ.get("OPTIMIZER_HEAP_MAX_BARS") or 0) or 1_000_000)


def enable_kline_heap_cache() -> None:
    global _heap_enabled
    _heap_enabled = True


def configure_kline_heap_cache(max_bars: int) -> None:
    global HEAP_MAX_BARS, _heap_bars
    HEAP_MAX_BARS = max(100_000, int(max_bars))
    if _heap_bars > HEAP_MAX_BARS:
        _heap_store.clear()
        _heap_bars = 0


def _heap_key(symbol: str, interval: str) -> str:
    return symbol + "|" + interval


def _invalidate_heap(symbol: str, interval: str) -> None:
    global _heap_bars
    if not _heap_enabled:
        return
    key = _heap_key(symbol, interval)
    cols = _heap_store.get(key)
    if cols:
        _heap_bars -= len(cols.times)
        del _heap_store[key]


def _load_heap(symbol: str, interval: str) -> HeapCols | None:
    global _heap_bars
    key = _heap_key(symbol, interval)
    existing = _heap_store.get(key)
    if existing is not None:
        return existing
    if _heap_bars >= HEAP_MAX_BARS:
        return None
    rows = query_all(SQL_SELECT_ALL, (symbol, interval))
    n = len(rows)
    cols = HeapCols(
        array.array("d", bytes(8 * n)),
        array.array("d", bytes(8 * n)),
        array.array("d", bytes(8 * n)),
        array.array("d", bytes(8 * n)),
        array.array("d", bytes(8 * n)),
        array.array("d", bytes(8 * n)),
    )
    for i in range(n):
        r = rows[i]
        cols.times[i] = math.floor(r["open_time"] / 1000)
        cols.o[i] = r["o"]
        cols.h[i] = r["h"]
        cols.l[i] = r["l"]
        cols.c[i] = r["c"]
        cols.v[i] = r["v"]
    _heap_store[key] = cols
    _heap_bars += n
    return cols


# times (zaman artan) icinde time <= tSec olan en sagdaki index (yoksa -1).
def _upper_bound_idx(times, t_sec: int) -> int:
    lo = 0
    hi = len(times) - 1
    ans = -1
    while lo <= hi:
        mid = (lo + hi) >> 1
        if times[mid] <= t_sec:
            ans = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return ans


# Kolonlardan [lo, hi] araligini Kline[] olarak yeniden kur (yalniz dondurulen dilim icin alloc).
def _slice_cols(cols: HeapCols, lo: int, hi: int) -> list[Kline]:
    out: list[Kline] = [None] * (hi - lo + 1)  # type: ignore[list-item]
    for i in range(lo, hi + 1):
        out[i - lo] = Kline(time=cols.times[i], open=cols.o[i], high=cols.h[i], low=cols.l[i], close=cols.c[i], volume=cols.v[i])
    return out


# Ensure [startMs, endMs] for symbol+interval is present in kline_cache (fetch missing edges once).
async def ensure_kline_range(symbol: str, interval: str, start_ms: int, end_ms: int) -> None:
    if end_ms <= start_ms:
        return
    meta = query_one(SQL_META, (symbol, interval))
    if meta and meta["covered_start"] <= start_ms and meta["covered_end"] >= end_ms:
        return

    ranges: list[tuple[int, int]] = []
    if not meta:
        ranges.append((start_ms, end_ms))
    else:
        if start_ms < meta["covered_start"]:
            ranges.append((start_ms, meta["covered_start"]))
        if end_ms > meta["covered_end"]:
            ranges.append((meta["covered_end"], end_ms))

    tf_ms = interval_ms(interval)
    covered_start = meta["covered_start"] if meta else None
    covered_end = meta["covered_end"] if meta else None
    fetched = 0
    for s, e in ranges:
        klines = await get_klines_range(symbol, interval, s, e)
        if len(klines) > 0:
            with transaction() as conn:
                conn.executemany(
                    SQL_INSERT,
                    [(symbol, interval, k["time"] * 1000, k["open"], k["high"], k["low"], k["close"], k["volume"]) for k in klines],
                )
            fetched += len(klines)

            first_ms = klines[0]["time"] * 1000
            last_ms = klines[-1]["time"] * 1000
            if covered_start is None or covered_end is None:
                covered_start = first_ms
                covered_end = last_ms
            else:
                overlaps_existing = first_ms <= covered_end + tf_ms and last_ms >= covered_start - tf_ms
                if overlaps_existing:
                    if last_ms >= covered_start - tf_ms:
                        covered_start = min(covered_start, first_ms)
                    if first_ms <= covered_end + tf_ms:
                        covered_end = max(covered_end, last_ms)

    if covered_start is not None and covered_end is not None:
        with transaction() as conn:
            conn.execute(SQL_UPSERT_META, (symbol, interval, covered_start, covered_end))
    if fetched > 0:
        _invalidate_heap(symbol, interval)
        log.info(f"Cached {fetched} klines {symbol} {interval}")


def _map_rows(rows) -> list[Kline]:
    return [Kline(time=math.floor(r["open_time"] / 1000), open=r["o"], high=r["h"], low=r["l"], close=r["c"], volume=r["v"]) for r in rows]


# Last `count` bars with open_time <= beforeMs (look-ahead safe), ascending.
def get_cached_klines(symbol: str, interval: str, before_ms: int, count: int) -> list[Kline]:
    if _heap_enabled:
        cols = _load_heap(symbol, interval)
        if cols is not None:
            end = _upper_bound_idx(cols.times, math.floor(before_ms / 1000))
            if end < 0:
                return []
            return _slice_cols(cols, max(0, end - count + 1), end)
    rows = query_all(SQL_SELECT_BACK, (symbol, interval, before_ms, count))
    out = _map_rows(rows)
    out.reverse()
    return out


# Bars strictly after fromMsExclusive up to untilMs, ascending (for exit simulation).
def get_forward_klines(symbol: str, interval: str, from_ms_exclusive: int, until_ms: int) -> list[Kline]:
    if _heap_enabled:
        cols = _load_heap(symbol, interval)
        if cols is not None:
            lo = _upper_bound_idx(cols.times, math.floor(from_ms_exclusive / 1000)) + 1
            hi = _upper_bound_idx(cols.times, math.floor(until_ms / 1000))
            if hi < lo:
                return []
            return _slice_cols(cols, lo, hi)
    rows = query_all(SQL_SELECT_FORWARD, (symbol, interval, from_ms_exclusive, until_ms))
    return _map_rows(rows)


# Retention: drop klines for symbols no longer refreshed (stale) and rows older than the
# retention window so the cache cannot grow unbounded. Frees pages for reuse (no VACUUM).
def prune_kline_cache() -> dict:
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA busy_timeout = 15000")
    retention_days = max(1, int(os.environ.get("KLINE_RETENTION_DAYS") or 0) or 400)
    stale_days = max(1, int(os.environ.get("KLINE_STALE_DAYS") or 0) or 21)
    cutoff_ms = int(now_ms()) - retention_days * 86_400_000
    stale_arg = f"-{stale_days} days"

    try:
        by_stale = db.execute(
            """DELETE FROM kline_cache WHERE (symbol, interval) IN (
           SELECT symbol, interval FROM kline_cache_meta WHERE updated_at < datetime('now', ?)
         )""",
            (stale_arg,),
        ).rowcount or 0
        db.execute("DELETE FROM kline_cache_meta WHERE updated_at < datetime('now', ?)", (stale_arg,))

        by_age = db.execute("DELETE FROM kline_cache WHERE open_time < ?", (cutoff_ms,)).rowcount or 0
        db.execute("UPDATE kline_cache_meta SET covered_start = ? WHERE covered_start < ?", (cutoff_ms, cutoff_ms))
        db.commit()
        try:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()
    if by_age + by_stale > 0:
        log.info(f"Kline prune: {by_age} by-age + {by_stale} by-stale rows (retention {retention_days}d, stale {stale_days}d)")
    return {"byAge": by_age, "byStale": by_stale}
