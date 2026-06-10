import asyncio
import json
import math
import time
from datetime import datetime, timezone
from functools import cmp_to_key

from ..db.database import get_db
from ..core.config import config
from ..core.logger import create_logger
from ..core.time import format_db_time_ms
from ..services.alert_signals import get_source_types
from ..services.kline_cache import ensure_kline_range, get_forward_klines, get_cached_klines, interval_ms
from ..services.funding_cache import ensure_funding_range
from ..agents.historical_strategy import analyze_symbol_historical, required_timeframes, floor_interval
from ..lib.indicators import calc_atr

log = create_logger("backtest-engine")

TF_MS: dict[str, int] = {"1": 60_000, "5": 300_000, "15": 900_000, "60": 3_600_000, "240": 14_400_000, "D": 86_400_000}


def _round2(x: float) -> float:
    # Faithful to JS Math.round(x * 100) / 100 (round-half-up toward +inf).
    return math.floor(x * 100 + 0.5) / 100


def _now_ms() -> int:
    return int(time.time() * 1000)


def to_ms(iso: str) -> float:
    s = iso if "T" in iso else iso.replace(" ", "T", 1)
    with_z = s if s.endswith("Z") else s + "Z"
    try:
        dt = datetime.fromisoformat(with_z.replace("Z", "+00:00"))
        return int(round(dt.timestamp() * 1000))
    except Exception:  # noqa: BLE001
        return float("nan")


def to_db_time(ms: float) -> str:
    return format_db_time_ms(ms)


def parse_json(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return {}


def _nn(v, d):
    return v if v is not None else d


# Sinyalin UTC zamani, config'in gun/saat penceresine uyuyor mu?
# hourStart/hourEnd None ise saat filtresi yok; allowedDays bos/None ise gun filtresi yok.
def within_time_window(ms: float, cfg: dict) -> bool:
    has_hour = cfg.get("hourStart") is not None and cfg.get("hourEnd") is not None
    allowed = cfg.get("allowedDays")
    has_days = isinstance(allowed, list) and len(allowed) > 0
    if not has_hour and not has_days:
        return True
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    if has_days and ((dt.weekday() + 1) % 7) not in allowed:  # getUTCDay: 0=Sunday..6=Saturday
        return False
    if has_hour:
        h = dt.hour
        s = cfg["hourStart"]
        e = cfg["hourEnd"]
        ok = (h >= s and h < e) if s <= e else (h >= s or h < e)  # sarmalama (orn. 22->4)
        if not ok:
            return False
    return True


async def run_backtest(params: dict) -> dict:
    db = get_db()
    cfg = params["strategyConfig"]
    initial_balance = params["initialBalance"] if params.get("initialBalance") is not None else (config.paper.initial_balance or 10000)
    exec_tf = params["execTf"] if params.get("execTf") is not None else "5"
    lookahead_ms = (params["maxLookaheadDays"] if params.get("maxLookaheadDays") is not None else 14) * 86_400_000
    taker = (params["taker"] if params.get("taker") is not None else config.paper.taker_fee) / 100
    slip = (params["slippage"] if params.get("slippage") is not None else config.paper.slippage) / 100
    lev = cfg["leverage"] if cfg["leverage"] > 0 else 1
    min_interval = params["minInterval"] if params.get("minInterval") is not None else "1"

    source_types = get_source_types(cfg["signalSource"])
    if len(source_types) == 0:
        return empty_result(initial_balance, params["startMs"])

    placeholders = ",".join("?" for _ in source_types)
    # Kaynak basina butce: her kaynak BAGIMSIZ olarak tum pencereye yayilarak ornenklenir.
    per_source_budget = params["maxSignals"] if params.get("maxSignals") is not None else 50_000
    sql = (
        f"SELECT symbol, direction, source_type, signal_type, raw_message, rsi_data, srsi_data, price, boost_value, stars, funding_rate, created_at\n"
        f"     FROM (\n"
        f"       SELECT symbol, direction, source_type, signal_type, raw_message, rsi_data, srsi_data, price, boost_value, stars, funding_rate, created_at,\n"
        f"         ROW_NUMBER() OVER (PARTITION BY source_type ORDER BY created_at ASC) AS rn,\n"
        f"         COUNT(*)    OVER (PARTITION BY source_type) AS cnt\n"
        f"       FROM alerts\n"
        f"       WHERE source_type IN ({placeholders}) AND created_at >= ? AND created_at <= ?\n"
        f"     )\n"
        f"     WHERE (rn - 1) % max(1, CAST((cnt + ? - 1) / ? AS INTEGER)) = 0\n"
        f"     ORDER BY created_at ASC"
    )
    rows = list(db.execute(
        sql,
        (*source_types, to_db_time(params["startMs"]), to_db_time(params["endMs"]), per_source_budget, per_source_budget),
    ).fetchall())

    # Bound symbol universe. Kaynak-duyarli: once primarySources sembolleri, sonra frekans.
    max_symbols = params["maxSymbols"] if params.get("maxSymbols") is not None else 60
    sym_count: dict[str, int] = {}
    for r in rows:
        sym_count[r["symbol"]] = sym_count.get(r["symbol"], 0) + 1
    if len(sym_count) > max_symbols:
        primary = set(params.get("primarySources") or [])
        primary_count: dict[str, int] = {}
        if len(primary):
            for r in rows:
                if r["source_type"] in primary:
                    primary_count[r["symbol"]] = primary_count.get(r["symbol"], 0) + 1

        def _cmp(a, b):
            pa = primary_count.get(a, 0)
            pb = primary_count.get(b, 0)
            if pa > 0 and pb == 0:
                return -1  # primary kaynakta gorulen sembol once
            if pb > 0 and pa == 0:
                return 1
            if pa != pb:
                return pb - pa  # primary frekansa gore
            return sym_count.get(b, 0) - sym_count.get(a, 0)  # sonra toplam frekans

        ranked = sorted(sym_count.keys(), key=cmp_to_key(_cmp))
        top_syms = set(ranked[:max_symbols])
        rows = [r for r in rows if r["symbol"] in top_syms]

    # Pre-load kline cache: per symbol, indicator TFs (back-buffer) + exec TF (forward window).
    tfs = required_timeframes(cfg.get("enabledRules"))
    symbols = list(dict.fromkeys(r["symbol"] for r in rows))
    use_atr_tpsl = (cfg.get("tpAtrMult") or 0) > 0 or (cfg.get("slAtrMult") or 0) > 0
    atr_tf = cfg["atrTimeframe"] if cfg.get("atrTimeframe") is not None else "15"
    preload_tfs = list(dict.fromkeys(
        floor_interval(tf, min_interval) for tf in (list(tfs) + [exec_tf] + ([atr_tf] if use_atr_tpsl else []))
    ))
    on_progress = params.get("onProgress")
    for si in range(len(symbols)):
        sym = symbols[si]
        if on_progress and si % 5 == 0:
            on_progress({"phase": "preload", "done": si, "total": len(symbols)})
        for tf in preload_tfs:
            tf_ms = TF_MS.get(tf, 300_000)
            back_buffer = 220 * tf_ms
            fwd = lookahead_ms if tf == exec_tf else 0
            # Cap forward fetch at "now": future klines don't exist.
            fetch_end = min(params["endMs"] + fwd, _now_ms())
            try:
                await ensure_kline_range(sym, tf, params["startMs"] - back_buffer, fetch_end)
            except Exception as err:  # noqa: BLE001
                log.warn(f"preload {sym} {tf}: {err}")
        # Bybit funding gecmisi (FR kurallari icin); ~10 gun geriye buffer.
        try:
            await ensure_funding_range(sym, params["startMs"] - 10 * 86_400_000, min(params["endMs"], _now_ms()))
        except Exception as err:  # noqa: BLE001
            log.warn(f"funding preload {sym}: {err}")

    weight_map = dict(cfg["ruleWeights"]) if cfg.get("ruleWeights") else None

    # Build candidate trades (entry decided at signal; exit precomputed from forward klines).
    candidates: list[dict] = []
    evaluated = 0
    skipped_no_data = 0
    tf_cov_sum = 0.0
    tf_cov_count = 0

    def price_pct(pct):
        return pct / lev / 100

    for i in range(len(rows)):
        r = rows[i]
        as_of = to_ms(r["created_at"])
        if not math.isfinite(as_of):
            continue
        signal = {
            "symbol": r["symbol"], "direction": r["direction"], "sourceType": r["source_type"],
            "signalType": _nn(r["signal_type"], ""), "rawMessage": _nn(r["raw_message"], ""),
            "rsiData": parse_json(r["rsi_data"]), "srsiData": parse_json(r["srsi_data"]),
            "price": _nn(r["price"], 0), "boostValue": _nn(r["boost_value"], 0), "stars": _nn(r["stars"], 0),
            "fundingRate": _nn(r["funding_rate"], 0), "createdMs": as_of,
        }

        # Zaman faktoru filtresi: sinyalin gercek UTC zamani pencere/gun disindaysa atla.
        if not within_time_window(as_of, cfg):
            continue

        res = analyze_symbol_historical(signal, cfg.get("enabledRules"), as_of, weight_map, min_interval)
        evaluated += 1
        if res["tfNeeded"] > 0:
            tf_cov_sum += res["tfWithData"] / res["tfNeeded"]
            tf_cov_count += 1

        score = res["totalScore"]
        side = "long" if score >= cfg["longMinScore"] else "short" if score <= cfg["shortMinScore"] else None
        if not side:
            continue
        if not res["refPrice"] or res["refPrice"] <= 0:
            skipped_no_data += 1
            continue

        # _nextBarEntry: giris sinyal barinda degil, sinyal sonrasi ILK exec-tf barinin
        # ACILISINDA dolar (canli/LEAN gibi). Sinyal-barinda-fill iyimserligini giderir.
        ref_price = res["refPrice"]
        entry_ms = as_of
        if cfg.get("_nextBarEntry"):
            tf_ms = interval_ms(exec_tf)
            fwd = get_forward_klines(r["symbol"], exec_tf, as_of, as_of + 3 * tf_ms)
            nb = next((b for b in fwd if b.time * 1000 > as_of), None)
            if nb is None:
                skipped_no_data += 1
                continue
            ref_price = nb.open
            entry_ms = nb.time * 1000
        entry_price = ref_price * (1 + slip) if side == "long" else ref_price * (1 - slip)
        # ATR tabanli TP/SL: ATR mutlak fiyat mesafesi -> tpPrice = entry +/- mult*ATR.
        atr_abs = None
        if use_atr_tpsl:
            ak = get_cached_klines(r["symbol"], atr_tf, as_of, 60)
            atr_abs = calc_atr(ak, 14) if len(ak) > 15 else None
        if use_atr_tpsl and atr_abs and atr_abs > 0:
            tp_dist = (cfg.get("tpAtrMult") or 0) * atr_abs
            sl_dist = (cfg.get("slAtrMult") or 0) * atr_abs
            tp_price = ((entry_price + tp_dist) if side == "long" else (entry_price - tp_dist)) if tp_dist > 0 else None
            sl_price = ((entry_price - sl_dist) if side == "long" else (entry_price + sl_dist)) if sl_dist > 0 else None
        else:
            tp_price = ((entry_price * (1 + price_pct(cfg["tpPercent"])) if side == "long" else entry_price * (1 - price_pct(cfg["tpPercent"]))) if cfg["tpPercent"] else None)
            sl_price = ((entry_price * (1 - price_pct(cfg["slPercent"])) if side == "long" else entry_price * (1 + price_pct(cfg["slPercent"]))) if cfg["slPercent"] else None)

        # _nextBarEntry: fill giris barinin ACILISINDA -> o barin high/low'u da TP/SL icin
        # gecerli (LEAN bunu kontrol eder). get_forward_klines strict (open_time > ?) oldugundan
        # giris barini dahil etmek icin pencereyi 1ms geri al; aksi halde giris barindaki
        # SL/TP gorulmez (bayragin giderdigi iyimserlik geri sizar).
        exit_from_ms = (entry_ms - 1) if cfg.get("_nextBarEntry") else entry_ms
        exit_ = simulate_exit(r["symbol"], side, exit_from_ms, entry_price, tp_price, sl_price, exec_tf, lookahead_ms, slip, cfg)
        if not exit_:
            skipped_no_data += 1
            continue
        candidates.append({
            "symbol": r["symbol"], "side": side, "entryMs": entry_ms, "entryPrice": entry_price,
            "tpPrice": tp_price, "slPrice": sl_price, "score": res["totalScore"],
            "exitMs": exit_["exitMs"], "exitPrice": exit_["exitPrice"], "exitReason": exit_["reason"],
        })

        if i % 200 == 0:
            await asyncio.sleep(0)
            if on_progress:
                on_progress({"phase": "simulate", "done": i, "total": len(rows)})

    # Portfolio walk: respect maxPositions + capital, chronological, compounding.
    candidates.sort(key=lambda c: c["entryMs"])
    balance = initial_balance
    cum_pnl = 0.0
    peak = initial_balance
    max_dd = 0.0
    open_: list[dict] = []
    trades: list[dict] = []
    last_close_ms: dict[str, int] = {}  # sembol -> son kapanis ms (re-entry settlement gap icin)
    equity_curve: list[dict] = [{"time": math.floor(params["startMs"] / 1000), "value": initial_balance}]

    def close_one(p):
        nonlocal balance, cum_pnl, peak, max_dd
        gross = (p["exitPrice"] - p["entryPrice"]) * p["qty"] if p["side"] == "long" else (p["entryPrice"] - p["exitPrice"]) * p["qty"]
        exit_fee = p["qty"] * p["exitPrice"] * taker
        net_pnl = gross - p["entryFee"] - exit_fee
        balance += p["margin"] + gross - exit_fee  # entry deducted (margin+entryFee) at open
        cum_pnl += net_pnl
        peak = max(peak, initial_balance + cum_pnl)
        dd = ((peak - (initial_balance + cum_pnl)) / peak) * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
        trades.append({
            "symbol": p["symbol"], "side": p["side"], "entryMs": p["entryMs"], "exitMs": p["exitMs"],
            "entryPrice": p["entryPrice"], "exitPrice": p["exitPrice"], "pnl": net_pnl,
            "pnlPercent": (net_pnl / p["margin"]) * 100 if p["margin"] > 0 else 0,
            "exitReason": p["exitReason"], "score": p["score"],
            "tpPrice": p.get("tpPrice"), "slPrice": p.get("slPrice"), "qty": p.get("qty"),
        })
        equity_curve.append({"time": math.floor(p["exitMs"] / 1000), "value": _round2(initial_balance + cum_pnl)})
        last_close_ms[p["symbol"]] = p["exitMs"]

    def close_due(upto_ms):
        due = sorted([p for p in open_ if p["exitMs"] <= upto_ms], key=lambda p: p["exitMs"])
        for p in due:
            close_one(p)
        due_ids = {id(p) for p in due}
        open_[:] = [q for q in open_ if id(q) not in due_ids]

    entered = 0
    # _reentryGapBars: ayni sembol kapandiktan sonra N bar gecmeden yeniden girilmez
    # (LEAN/canli settlement gecikmesi -> ayni-sembol re-entry iyimserligini giderir).
    reentry_gap_ms = int((cfg.get("_reentryGapBars") or 0) * interval_ms(exec_tf))
    for c in candidates:
        close_due(c["entryMs"])
        if len(open_) >= cfg["maxPositions"]:
            continue
        if any(p["symbol"] == c["symbol"] for p in open_):
            continue
        if reentry_gap_ms > 0:
            lc = last_close_ms.get(c["symbol"])
            if lc is not None and c["entryMs"] - lc < reentry_gap_ms:
                continue
        margin = balance * (cfg["positionSizePct"] / 100)
        if margin <= 0:
            continue
        qty = (margin * lev) / c["entryPrice"]
        entry_fee = qty * c["entryPrice"] * taker
        if balance < margin + entry_fee:  # giris fee'si de nakitten dusulur -> bakiye negatife dusmesin
            continue
        balance -= margin + entry_fee
        open_.append({
            "symbol": c["symbol"], "side": c["side"], "entryPrice": c["entryPrice"], "qty": qty,
            "margin": margin, "entryFee": entry_fee, "exitMs": c["exitMs"], "exitPrice": c["exitPrice"],
            "exitReason": c["exitReason"], "score": c["score"], "entryMs": c["entryMs"],
            "tpPrice": c.get("tpPrice"), "slPrice": c.get("slPrice"),
        })
        entered += 1
    # close remaining
    open_.sort(key=lambda p: p["exitMs"])
    for p in list(open_):
        close_one(p)

    metrics = compute_metrics(trades, initial_balance, max_dd)
    return {
        "metrics": metrics,
        "equityCurve": equity_curve,
        "trades": trades,
        "coverage": {
            "totalSignals": len(rows), "evaluated": evaluated, "entered": entered,
            "skippedNoData": skipped_no_data, "symbols": len(symbols),
            "avgTfCoverage": math.floor((tf_cov_sum / tf_cov_count) * 100 + 0.5) if tf_cov_count > 0 else 0,
        },
    }


def simulate_exit(symbol, side, entry_ms, entry_price, tp_price, sl_price, exec_tf, lookahead_ms, slip, cfg):
    bars = get_forward_klines(symbol, exec_tf, entry_ms, entry_ms + lookahead_ms)
    if len(bars) == 0:
        return None
    sl = sl_price
    highest = entry_price
    lowest = entry_price
    trail_pct = cfg["trailingPercent"] / 100 if (cfg.get("trailingStop") and cfg.get("trailingPercent")) else 0
    # close_based: TP/SL bar high/low yerine bar KAPANISINA gore yakalanir (LEAN oracle paritesi).
    close_based = bool(cfg.get("_closeBased"))
    # next_bar: hit BARI yerine cikis BIR SONRAKI BARIN ACILISINDA dolar (LEAN/canli gibi
    # gercekci fill gecikmesi -> "ayni barda kapanista cikma" iyimserligini giderir).
    next_bar = bool(cfg.get("_nextBarExit"))

    def _exit(idx, level_px, reason):
        if next_bar and idx + 1 < len(bars):
            nb = bars[idx + 1]
            px = nb.open
            t = nb.time
        else:
            px = level_px
            t = bars[idx].time
        fill = px * (1 - slip) if side == "long" else px * (1 + slip)
        return {"exitMs": t * 1000, "exitPrice": fill, "reason": reason}

    for i, bar in enumerate(bars):
        if trail_pct > 0:
            if side == "long":
                ref_h = bar.close if close_based else bar.high
                highest = max(highest, ref_h)
                ns = highest * (1 - trail_pct)
                if sl is None or ns > sl:
                    sl = ns
            else:
                ref_l = bar.close if close_based else bar.low
                lowest = min(lowest, ref_l)
                ns = lowest * (1 + trail_pct)
                if sl is None or ns < sl:
                    sl = ns
        # Conservative: SL checked before TP on same-bar ambiguity.
        if side == "long":
            hit_sl = sl is not None and ((bar.close <= sl) if close_based else (bar.low <= sl))
            hit_tp = tp_price is not None and ((bar.close >= tp_price) if close_based else (bar.high >= tp_price))
            if hit_sl:
                return _exit(i, bar.close if close_based else sl, "sl_hit")
            if hit_tp:
                return _exit(i, bar.close if close_based else tp_price, "tp_hit")
        else:
            hit_sl = sl is not None and ((bar.close >= sl) if close_based else (bar.high >= sl))
            hit_tp = tp_price is not None and ((bar.close <= tp_price) if close_based else (bar.low <= tp_price))
            if hit_sl:
                return _exit(i, bar.close if close_based else sl, "sl_hit")
            if hit_tp:
                return _exit(i, bar.close if close_based else tp_price, "tp_hit")
    last = bars[-1]
    exit_price = last.close * (1 - slip) if side == "long" else last.close * (1 + slip)
    return {"exitMs": last.time * 1000, "exitPrice": exit_price, "reason": "window_end"}


def compute_metrics(trades, initial_balance, max_drawdown):
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in trades)
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    pnls = [t["pnl"] for t in trades]
    mean = (sum(pnls) / n) if n > 0 else 0
    variance = (sum((b - mean) ** 2 for b in pnls) / n) if n > 1 else 0
    std = math.sqrt(variance)
    total_pnl_pct = (total_pnl / initial_balance) * 100
    r = _round2
    return {
        "trades": n, "wins": len(wins), "losses": len(losses),
        "totalPnl": r(total_pnl), "totalPnlPct": r(total_pnl_pct),
        "winRate": r((len(wins) / n) * 100) if n > 0 else 0,
        "avgPnl": r(total_pnl / n) if n > 0 else 0,
        "avgWin": r(gross_profit / len(wins)) if len(wins) > 0 else 0,
        "avgLoss": r(gross_loss / len(losses)) if len(losses) > 0 else 0,
        "profitFactor": r(gross_profit / gross_loss) if gross_loss > 0 else (99 if gross_profit > 0 else 0),
        "sharpe": r((mean / std) * math.sqrt(252)) if std > 0 else 0,
        "maxDrawdown": r(max_drawdown),
        "calmar": r(total_pnl_pct / max_drawdown) if max_drawdown > 0 else (99 if total_pnl_pct > 0 else 0),
        "expectancy": r(total_pnl / n) if n > 0 else 0,
    }


def empty_result(initial_balance, start_ms):
    return {
        "metrics": {
            "trades": 0, "wins": 0, "losses": 0, "totalPnl": 0, "totalPnlPct": 0, "winRate": 0,
            "avgPnl": 0, "avgWin": 0, "avgLoss": 0, "profitFactor": 0, "sharpe": 0,
            "maxDrawdown": 0, "calmar": 0, "expectancy": 0,
        },
        "equityCurve": [{"time": math.floor(start_ms / 1000), "value": initial_balance}],
        "trades": [],
        "coverage": {"totalSignals": 0, "evaluated": 0, "entered": 0, "skippedNoData": 0, "symbols": 0, "avgTfCoverage": 0},
    }
