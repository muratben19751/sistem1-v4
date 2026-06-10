import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..db.database import query_one, query_all

router = APIRouter()

_DIGITS_RE = re.compile(r"^\d+$")


def _parse_positive_int(value, fallback: int) -> int:
    text = str(value if value is not None else "").strip()
    if not _DIGITS_RE.match(text):
        return fallback
    parsed = int(text)
    return parsed if parsed > 0 else fallback


def _parse_non_negative_int(value, fallback: int) -> int:
    text = str(value if value is not None else "").strip()
    if not _DIGITS_RE.match(text):
        return fallback
    parsed = int(text)
    return parsed if parsed >= 0 else fallback


def _parse_account_id(raw):
    if raw is None:
        return None
    text = raw.strip()
    if not _DIGITS_RE.match(text):
        return None
    parsed = int(text)
    return parsed if parsed > 0 else None


_FR_EXPR = """(
    COALESCE(
      (SELECT a.bybit_fr FROM alerts a
        WHERE a.symbol = trades.symbol AND a.bybit_fr IS NOT NULL
          AND ((trades.side='long' AND a.direction='UP') OR (trades.side='short' AND a.direction='DOWN'))
          AND abs(julianday(replace(replace(a.created_at,'T',' '),'Z','')) - julianday(replace(replace(trades.opened_at,'T',' '),'Z',''))) <= 0.0208333
        ORDER BY abs(julianday(replace(replace(a.created_at,'T',' '),'Z','')) - julianday(replace(replace(trades.opened_at,'T',' '),'Z',''))) ASC
        LIMIT 1),
      (SELECT fc.funding_rate FROM funding_cache fc
        WHERE fc.symbol = trades.symbol
          AND fc.funding_ts <= (julianday(replace(replace(trades.opened_at,'T',' '),'Z','')) - 2440587.5) * 86400000
        ORDER BY fc.funding_ts DESC LIMIT 1)
    )
  ) AS entry_fr"""


@router.get("")
async def get_trades(request: Request):
    raw_account_id = request.query_params.get("accountId")
    account_id = _parse_account_id(raw_account_id)
    if raw_account_id is not None and account_id is None:
        return JSONResponse(status_code=400, content={"error": "Invalid accountId"})
    limit = min(_parse_positive_int(request.query_params.get("limit"), 50), 500)
    offset = _parse_non_negative_int(request.query_params.get("offset"), 0)
    with_fr = request.query_params.get("withFr") == "1"
    status = str(request.query_params.get("status") or "").strip().lower()
    if status and status not in ("open", "closed"):
        return JSONResponse(status_code=400, content={"error": "Invalid status"})

    sel = f"*, {_FR_EXPR}" if with_fr else "*"

    where: list[str] = []
    params: list = []
    if account_id is not None:
        where.append("account_id = ?")
        params.append(account_id)
    if status:
        where.append("status = ?")
        params.append(status)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    rows = query_all(
        f"SELECT {sel} FROM trades {where_sql} ORDER BY opened_at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    )
    return [dict(r) for r in rows]


@router.get("/signal-summary")
async def get_signal_summary(request: Request):
    raw_account_id = request.query_params.get("accountId")
    account_id = _parse_account_id(raw_account_id)
    if raw_account_id is not None and account_id is None:
        return JSONResponse(status_code=400, content={"error": "Invalid accountId"})
    windows = [1, 2, 4, 5, 6, 7, 8, 9, 10, 24]
    now = datetime.now(timezone.utc)
    summary = []
    for hours in windows:
        since = (now - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        if account_id is not None:
            where = "WHERE opened_at >= ? AND account_id = ?"
            params = (since, account_id)
        else:
            where = "WHERE opened_at >= ?"
            params = (since,)
        total = query_one(f"SELECT COUNT(*) as c FROM trades {where}", params)
        wins = query_one(f"SELECT COUNT(*) as c FROM trades {where} AND pnl > 0 AND status = 'closed'", params)
        losses = query_one(f"SELECT COUNT(*) as c FROM trades {where} AND pnl <= 0 AND status = 'closed'", params)
        pnl_row = query_one(f"SELECT COALESCE(SUM(pnl), 0) as total FROM trades {where} AND status = 'closed'", params)
        open_count = query_one(f"SELECT COUNT(*) as c FROM trades {where} AND status = 'open'", params)
        summary.append({
            "hours": hours,
            "total": total["c"],
            "wins": wins["c"],
            "losses": losses["c"],
            "open": open_count["c"],
            "pnl": pnl_row["total"],
        })
    return summary


@router.get("/metrics")
async def get_trade_metrics(request: Request):
    raw_account_id = request.query_params.get("accountId")
    account_id = _parse_account_id(raw_account_id)
    if raw_account_id is not None and account_id is None:
        return JSONResponse(status_code=400, content={"error": "Invalid accountId"})
    hours = min(_parse_positive_int(request.query_params.get("hours"), 24), 24 * 365)
    where = [
        "status = 'closed'",
        "closed_at IS NOT NULL",
        "closed_at >= datetime('now', ?)",
    ]
    params: list = [f"-{hours} hours"]
    if account_id is not None:
        where.append("account_id = ?")
        params.append(account_id)
    row = query_one(
        f"""
        SELECT COUNT(*) AS closed_trades,
          COALESCE(SUM(pnl), 0) AS realized_pnl,
          COALESCE(SUM(fee), 0) AS fees
        FROM trades
        WHERE {' AND '.join(where)}
        """,
        params,
    )
    return {
        "hours": hours,
        "closedTrades": row["closed_trades"],
        "realizedPnl": row["realized_pnl"],
        "fees": row["fees"],
    }


@router.get("/{id}")
async def get_trade(id: str):
    trade_id = int(id) if _DIGITS_RE.match(id) else None
    if trade_id is None or trade_id <= 0:
        return JSONResponse(status_code=400, content={"error": "Invalid trade id"})
    trade = query_one("SELECT * FROM trades WHERE id = ?", (trade_id,))
    if not trade:
        return JSONResponse(status_code=404, content={"error": "Trade not found"})
    return dict(trade)
