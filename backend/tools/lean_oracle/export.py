"""EXPORT: kendi run_backtest()'imi kosup giris sinyallerini + metrikleri + mumlari
LEAN'in replay edebilecegi bir paket olarak diske yazar.

Sinyal/skorlama LEAN'de yeniden yazilmaz; LEAN yalnizca icra (giris->TP/SL/cikis, fee,
slippage, kaldirac, portfoy) simulasyonu yapar. Burada motorumun URETTIGI girisleri
disa aktaririz.

Tamamen salt-okunur: ana DB'den kline_cache / alerts / optimizer_results OKUNUR; hicbir
sey yazilmaz. --offline (varsayilan) modunda ag'a cikilmaz (ensure_* no-op'lanir).
"""
import argparse
import asyncio
import csv
import json
import re
from pathlib import Path

from . import BACKEND_ROOT  # noqa: F401  (sys.path bootstrap)
from app.core.config import config
from app.core.time import format_db_time_ms, now_ms
from app.db.database import query_all, query_one
from app.engines import backtest_engine as be
from app.services.kline_cache import interval_ms

EXPORT_ROOT = Path(__file__).resolve().parent / "oracle_export"


def parse_window_days(window: str) -> int:
    m = re.fullmatch(r"(\d+)\s*d", str(window).strip(), re.IGNORECASE)
    if not m:
        raise ValueError(f"Gecersiz pencere: {window!r} (orn. 90d)")
    return int(m.group(1))


def parse_symbols_arg(symbols: str) -> int:
    """TOP<N> -> maxSymbols. 'ALL' -> buyuk sayi."""
    s = str(symbols).strip().upper()
    if s == "ALL":
        return 500
    m = re.fullmatch(r"TOP(\d+)", s)
    if not m:
        raise ValueError(f"Gecersiz --symbols: {symbols!r} (TOP10 veya ALL)")
    return int(m.group(1))


def resolve_strategy(name: str | None) -> tuple[str, dict]:
    if name:
        row = query_one(
            "SELECT strategy_name, config_json FROM optimizer_results WHERE strategy_name = ? "
            "ORDER BY calmar DESC LIMIT 1",
            (name,),
        )
        if not row:
            raise SystemExit(f"Strateji bulunamadi: {name}")
    else:
        row = query_one(
            "SELECT strategy_name, config_json FROM optimizer_results "
            "WHERE trades >= 20 AND calmar > 0 ORDER BY calmar DESC LIMIT 1"
        )
        if not row:
            raise SystemExit("Uygun strateji yok (trades>=20 & calmar>0).")
    cfg = json.loads(row["config_json"])
    cfg.pop("_wf", None)
    return row["strategy_name"], cfg


def anchor_end_ms() -> float:
    row = query_one("SELECT MAX(created_at) AS m FROM alerts")
    if row and row["m"]:
        from app.core.time import parse_db_time_ms
        v = parse_db_time_ms(row["m"])
        if v == v:
            return v
    return now_ms()


def _noop_async(*_a, **_k):
    return None


async def _async_noop(*_a, **_k):
    return None


def export_klines(symbol: str, interval: str, start_ms: int, end_ms: int, out_csv: Path) -> int:
    rows = query_all(
        "SELECT open_time, o, h, l, c, v FROM kline_cache "
        "WHERE symbol = ? AND interval = ? AND open_time >= ? AND open_time <= ? ORDER BY open_time ASC",
        (symbol, interval, start_ms, end_ms),
    )
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_ms", "open", "high", "low", "close", "volume"])
        for r in rows:
            w.writerow([r["open_time"], r["o"], r["h"], r["l"], r["c"], r["v"]])
    return len(rows)


def _deslip(entry_price: float, side: str) -> float:
    slip = config.paper.slippage / 100
    if side == "long":
        return entry_price / (1 + slip)
    return entry_price / (1 - slip)


async def run_export(window: str, symbols: str, strategy: str | None,
                     exec_tf: str = "5", offline: bool = True) -> Path:
    days = parse_window_days(window)
    max_symbols = parse_symbols_arg(symbols)
    strat_name, cfg = resolve_strategy(strategy)
    # Kapanis-bazli cikis: LEAN ile birebir metodoloji (bar high/low yerine close).
    cfg["_closeBased"] = True
    # Cikis bir sonraki bar acilisinda dolar (LEAN/canli gibi gercekci fill gecikmesi).
    cfg["_nextBarExit"] = True
    # Giris de sinyal sonrasi ilk bar acilisinda dolar (LEAN market-fill ile birebir).
    cfg["_nextBarEntry"] = True
    # Ayni sembol kapandiktan sonra 1 bar gecmeden yeniden girilmez (LEAN settlement gibi).
    cfg["_reentryGapBars"] = 1

    end_ms = int(anchor_end_ms())
    start_ms = end_ms - days * 86_400_000

    if offline:
        be.ensure_kline_range = _async_noop
        be.ensure_funding_range = _async_noop

    initial_balance = config.paper.initial_balance or 10000
    taker = config.paper.taker_fee
    slippage = config.paper.slippage
    lookahead_days = 7

    params = {
        "strategyConfig": cfg,
        "initialBalance": initial_balance,
        "startMs": start_ms,
        "endMs": end_ms,
        "execTf": exec_tf,
        "maxLookaheadDays": lookahead_days,
        "taker": taker,
        "slippage": slippage,
        "minInterval": "1",
        "maxSignals": 50000,
        "maxSymbols": max_symbols,
    }

    result = await be.run_backtest(params)
    trades = result["trades"]
    metrics = result["metrics"]

    run_id = f"{strat_name}_{days}d_{exec_tf}tf_{end_ms}"
    out = EXPORT_ROOT / run_id
    (out / "data").mkdir(parents=True, exist_ok=True)

    signals = [
        {
            "entryMs": int(t["entryMs"]),
            "symbol": t["symbol"],
            "side": t["side"],
            "refPrice": _deslip(t["entryPrice"], t["side"]),
            "tpPrice": t.get("tpPrice"),
            "slPrice": t.get("slPrice"),
            "qty": t.get("qty"),
            "score": t["score"],
        }
        for t in trades
    ]
    (out / "signals.json").write_text(json.dumps(signals, indent=2))

    exec_cfg = {
        "tpPercent": cfg.get("tpPercent"),
        "slPercent": cfg.get("slPercent"),
        "leverage": cfg.get("leverage", 1),
        "positionSizePct": cfg.get("positionSizePct", 2),
        "maxPositions": cfg.get("maxPositions", 1),
        "trailingStop": bool(cfg.get("trailingStop")),
        "trailingPercent": cfg.get("trailingPercent"),
        "useAtr": "tpAtrMult" in cfg or "slAtrMult" in cfg,
        "tpAtrMult": cfg.get("tpAtrMult"),
        "slAtrMult": cfg.get("slAtrMult"),
        "atrTimeframe": cfg.get("atrTimeframe"),
        "takerFeePct": taker,
        "makerFeePct": config.paper.maker_fee,
        "slippagePct": slippage,
        "execTf": exec_tf,
        "initialBalance": initial_balance,
        "startMs": start_ms,
        "endMs": end_ms,
        "startIso": format_db_time_ms(start_ms),
        "endIso": format_db_time_ms(end_ms),
        "accountCurrency": "USDT",
        "fundingModeled": False,
        "closeBased": True,
    }
    (out / "config.json").write_text(json.dumps(exec_cfg, indent=2))

    (out / "my_metrics.json").write_text(json.dumps({
        "strategy": strat_name,
        "window": window,
        "symbols": symbols,
        "metrics": metrics,
        "trades": trades,
        "coverage": result["coverage"],
    }, indent=2))

    traded_symbols = sorted({t["symbol"] for t in trades})
    tf_ms = interval_ms(exec_tf)
    fetch_start = start_ms - 220 * tf_ms
    fetch_end = end_ms + lookahead_days * 86_400_000
    bar_counts = {}
    for sym in traded_symbols:
        n = export_klines(sym, exec_tf, fetch_start, fetch_end, out / "data" / f"{sym}.csv")
        bar_counts[sym] = n

    (out / "manifest.json").write_text(json.dumps({
        "runId": run_id,
        "strategy": strat_name,
        "window": window,
        "symbolsArg": symbols,
        "execTf": exec_tf,
        "startMs": start_ms,
        "endMs": end_ms,
        "offline": offline,
        "signalCount": len(signals),
        "tradedSymbols": traded_symbols,
        "barCounts": bar_counts,
        "myMetricsSummary": {
            "trades": metrics["trades"],
            "totalPnl": metrics["totalPnl"],
            "totalPnlPct": metrics["totalPnlPct"],
            "winRate": metrics["winRate"],
            "profitFactor": metrics["profitFactor"],
            "sharpe": metrics["sharpe"],
            "maxDrawdown": metrics["maxDrawdown"],
            "calmar": metrics["calmar"],
        },
    }, indent=2))

    return out


def main():
    ap = argparse.ArgumentParser(description="LEAN oracle export")
    ap.add_argument("--window", default="90d")
    ap.add_argument("--symbols", default="TOP10")
    ap.add_argument("--strategy", default=None)
    ap.add_argument("--exec-tf", default="5")
    ap.add_argument("--online", action="store_true", help="cache yetmezse Bybit'ten cek (ana DB'ye yazar)")
    args = ap.parse_args()
    out = asyncio.run(run_export(args.window, args.symbols, args.strategy, args.exec_tf, offline=not args.online))
    print(f"Export tamam: {out}")


if __name__ == "__main__":
    main()
