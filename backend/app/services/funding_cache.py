from ..core.logger import create_logger
from ..db.database import query_all, query_one, transaction
from .bybit_api import get_funding_rate_history_range

log = create_logger("funding-cache")

SQL_META = "SELECT covered_start, covered_end FROM funding_cache_meta WHERE symbol = ?"
SQL_INSERT = "INSERT OR IGNORE INTO funding_cache (symbol, funding_ts, funding_rate) VALUES (?, ?, ?)"
SQL_UPSERT_META = """
      INSERT INTO funding_cache_meta (symbol, covered_start, covered_end, updated_at)
      VALUES (?, ?, ?, datetime('now'))
      ON CONFLICT(symbol) DO UPDATE SET covered_start = excluded.covered_start, covered_end = excluded.covered_end, updated_at = datetime('now')
    """
SQL_SELECT_BACK = "SELECT funding_ts, funding_rate FROM funding_cache WHERE symbol = ? AND funding_ts <= ? ORDER BY funding_ts DESC LIMIT ?"
SQL_SELECT_AT = "SELECT funding_rate FROM funding_cache WHERE symbol = ? AND funding_ts <= ? ORDER BY funding_ts DESC LIMIT 1"


# [startMs, endMs] araligindaki Bybit settlement funding'lerini cache'le. Funding seyrek
# (8s/4s/1s) oldugu icin aralik genisledikce birlesik araligi bir kez cekmek yeterli.
# Sembol Bybit'te yoksa bos doner ama meta yine isaretlenir (refetch dongusu olmaz).
async def ensure_funding_range(symbol: str, start_ms: int, end_ms: int) -> None:
    if end_ms <= start_ms:
        return
    meta = query_one(SQL_META, (symbol,))
    if meta and meta["covered_start"] <= start_ms and meta["covered_end"] >= end_ms:
        return

    fetch_start = min(start_ms, meta["covered_start"]) if meta else start_ms
    fetch_end = max(end_ms, meta["covered_end"]) if meta else end_ms
    items = await get_funding_rate_history_range(symbol, fetch_start, fetch_end)
    if len(items) == 0:
        # get_funding_rate_history_range agtaki/Bybit hatasini yutup [] doner. Bos sonucu
        # "kapsandi" diye isaretlersek gecici bir hata o pencereyi KALICI bos birakir
        # (kline_cache gibi: yalnizca veri geldiyse coverage'i genislet -> kendini onarir).
        return
    with transaction() as conn:
        conn.executemany(SQL_INSERT, [(symbol, it["fundingRateTimestamp"], it["fundingRate"]) for it in items])
    log.info(f"Cached {len(items)} funding {symbol}")
    covered_start = min(meta["covered_start"], start_ms) if meta else start_ms
    covered_end = max(meta["covered_end"], end_ms) if meta else end_ms
    with transaction() as conn:
        conn.execute(SQL_UPSERT_META, (symbol, covered_start, covered_end))


# funding_ts <= beforeMs olan son `count` settlement (look-ahead korumali), artan sirada.
def get_cached_funding_history(symbol: str, as_of_ms: int, limit: int) -> list[dict]:
    rows = query_all(SQL_SELECT_BACK, (symbol, as_of_ms, limit))
    out = [{"fundingRate": r["funding_rate"], "fundingRateTimestamp": r["funding_ts"]} for r in rows]
    out.reverse()
    return out


# ms anindaki gecerli (en yakin <= ms) Bybit funding rate (kesir), yoksa null.
def get_cached_funding_at(symbol: str, as_of_ms: int) -> float | None:
    row = query_one(SQL_SELECT_AT, (symbol, as_of_ms))
    return row["funding_rate"] if row else None
