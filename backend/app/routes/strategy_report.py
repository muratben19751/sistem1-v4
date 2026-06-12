"""Strateji raporu: denenmis (deploy edilmis) ve kapanmis stratejilerin listesi.

Iki kaynak birlesir:
- 'closed': hesap baska stratejiye verilirken trades_archive'e tasinan gecmis
  (arsiv satirlari eski strateji adiyla etiketlidir).
- 'stopped': durdurulmus ama hesabi henuz yeniden kullanilmamis deploy'lar
  (islemleri hala trades tablosunda).

Her satir, ayni isimli optimizer sonucunun backtest/OOS metrikleriyle
zenginlestirilir -> "backtest boyle demisti, gercekte boyle gitti" kiyasi.
"""
import asyncio

from fastapi import APIRouter

from ..db.database import query_all

router = APIRouter()

_ARCHIVE_SQL = """
SELECT account_name AS strategy, account_id,
  COUNT(*) AS trades,
  SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
  SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) AS losses,
  SUM(COALESCE(pnl, 0)) AS pnl,
  SUM(COALESCE(fee, 0)) AS fee,
  MIN(opened_at) AS first_trade,
  MAX(closed_at) AS last_trade,
  MAX(archived_at) AS ended_at
FROM trades_archive
WHERE status = 'closed' AND account_name IS NOT NULL AND account_name != ''
GROUP BY account_name, account_id
"""

_STOPPED_SQL = """
SELECT r.strategy_name AS strategy, a.id AS account_id, r.deployed_at,
  COUNT(t.id) AS trades,
  SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
  SUM(CASE WHEN t.pnl <= 0 THEN 1 ELSE 0 END) AS losses,
  SUM(COALESCE(t.pnl, 0)) AS pnl,
  SUM(COALESCE(t.fee, 0)) AS fee,
  MIN(t.opened_at) AS first_trade,
  MAX(t.closed_at) AS last_trade
FROM optimizer_results r
JOIN accounts a ON a.name = r.strategy_name
LEFT JOIN trades t ON t.account_id = a.id AND t.status = 'closed'
WHERE r.deploy_state = 'stopped'
GROUP BY r.strategy_name, a.id
"""

# Strateji basina en iyi (max calmar) optimizer sonucu -> backtest beklentisi.
_BACKTEST_SQL = """
SELECT r.strategy_name, r.calmar, r.win_rate, r.total_pnl, r.trades AS bt_trades,
  r.oos_calmar, r.oos_win_rate
FROM optimizer_results r
JOIN (
  SELECT strategy_name, MAX(calmar) AS mc FROM optimizer_results GROUP BY strategy_name
) b ON b.strategy_name = r.strategy_name AND b.mc = r.calmar
GROUP BY r.strategy_name
"""


def _row(source: str, r, bt: dict | None) -> dict:
    trades = int(r["trades"] or 0)
    wins = int(r["wins"] or 0)
    return {
        "strategy": r["strategy"],
        "status": source,
        "accountId": r["account_id"],
        "trades": trades,
        "wins": wins,
        "losses": int(r["losses"] or 0),
        "pnl": round(float(r["pnl"] or 0.0), 2),
        "fee": round(float(r["fee"] or 0.0), 2),
        "winRate": round(wins / trades * 100, 1) if trades > 0 else None,
        "firstTrade": r["first_trade"],
        "lastTrade": r["last_trade"],
        "endedAt": r["ended_at"] if "ended_at" in r.keys() else None,
        "btCalmar": bt["calmar"] if bt else None,
        "btWinRate": bt["win_rate"] if bt else None,
        "btPnl": bt["total_pnl"] if bt else None,
        "btTrades": bt["bt_trades"] if bt else None,
        "oosCalmar": bt["oos_calmar"] if bt else None,
        "oosWinRate": bt["oos_win_rate"] if bt else None,
    }


def _build_report() -> list[dict]:
    archived = query_all(_ARCHIVE_SQL)
    stopped = query_all(_STOPPED_SQL)
    backtests = {r["strategy_name"]: dict(r) for r in query_all(_BACKTEST_SQL)}
    out = [_row("closed", r, backtests.get(r["strategy"])) for r in archived]
    out += [_row("stopped", r, backtests.get(r["strategy"])) for r in stopped]
    out.sort(key=lambda x: x["lastTrade"] or x["endedAt"] or "", reverse=True)
    return out


@router.get("")
async def strategy_report():
    return await asyncio.to_thread(_build_report)
