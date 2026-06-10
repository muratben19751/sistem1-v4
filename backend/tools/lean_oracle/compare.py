"""COMPARE: LEAN istatistikleri vs kendi metriklerim -> parite raporu (markdown + json).

Her metrik icin: benimki | LEAN | mutlak/oransal fark | sinif | hukum.
Siniflar:
  mechanical  -> ayni seyi olcer; fark fee/slippage/cikis-zamanlamasi kaynaklidir.
                 <%1 beklenir (PASS), <%5 MINOR, >%5 INVESTIGATE (olasi bug).
  definitional-> tanim farkli (orn. Sharpe yillıklama, ProfitFactor vs Profit-Loss Ratio,
                 $ vs % birim). Sapma BEKLENIR; "modelleme farki" olarak not edilir.
"""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

EPS = 1e-9
TOL_PASS = 1.0   # %
TOL_MINOR = 5.0  # %
KIND_LABEL = {"mechanical": "Mekanik", "modeling": "Modelleme", "definitional": "Tanimsal"}


def parse_stat(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "").replace("$", "").replace("%", "")
    if s in ("", "N/A", "NaN"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def rel_pct(mine: float, lean: float) -> float:
    denom = max(abs(mine), abs(lean), EPS)
    return abs(mine - lean) / denom * 100.0


def _verdict(kind: str, mine, lean) -> tuple[float | None, str]:
    if mine is None or lean is None:
        return None, "N/A"
    rp = rel_pct(mine, lean)
    if kind in ("definitional", "modeling"):
        return rp, "NOTE"
    if rp <= TOL_PASS:
        return rp, "PASS"
    if rp <= TOL_MINOR:
        return rp, "MINOR"
    return rp, "INVESTIGATE"


def build_rows(my_metrics: dict, lean_stats: dict, initial_balance: float) -> list[dict]:
    m = my_metrics
    lean_net_pct = parse_stat(lean_stats.get("Net Profit"))
    lean_net_usd = (initial_balance * lean_net_pct / 100.0) if lean_net_pct is not None else None
    lean_car = parse_stat(lean_stats.get("Compounding Annual Return"))
    lean_dd = parse_stat(lean_stats.get("Drawdown"))
    lean_calmar = (lean_car / lean_dd) if (lean_car is not None and lean_dd not in (None, 0)) else None

    specs = [
        ("Total Trades", m.get("trades"), parse_stat(lean_stats.get("Total Trades")), "mechanical",
         "Kapanan islem sayisi. Ayni giris setinden ayni cikis sayisi beklenir."),
        ("Net Profit %", m.get("totalPnlPct"), lean_net_pct, "modeling",
         "Toplam getiri %. Win-rate esit oldugu halde fark varsa: motor-arasi dolum "
         "zamanlamasi (LEAN giris/cikis bar kapanisinda, benimkinde slippage uygulanir) "
         "ve birkac islemin gating-zamanlamasiyla acilmamasi."),
        ("Net Profit USDT", m.get("totalPnl"), lean_net_usd, "modeling",
         "Toplam P&L (LEAN: baslangic*NetProfit%). Bkz. Net Profit % notu."),
        ("Win Rate %", m.get("winRate"), parse_stat(lean_stats.get("Win Rate")), "mechanical",
         "Kazanan islem orani. ESLESMESI cikis/TP-SL kararlarinin sadik oldugunu gosterir."),
        ("Max Drawdown %", m.get("maxDrawdown"), lean_dd, "modeling",
         "Benim DD'm GERCEKLESEN equity'den (kapanislar), LEAN ise MARK-TO-MARKET "
         "(acik pozisyonun gerceklesmemis dususu dahil) olcer -> LEAN sistematik daha yuksek."),
        ("Sharpe", m.get("sharpe"), parse_stat(lean_stats.get("Sharpe Ratio")), "definitional",
         "Benimki islem-bazli*sqrt(252); LEAN gunluk getiri yillıklamasi. Tanim farkli."),
        ("Profit Factor", m.get("profitFactor"), parse_stat(lean_stats.get("Profit-Loss Ratio")), "definitional",
         "Benim PF=brutKar/brutZarar; LEAN 'Profit-Loss Ratio'=ortKazanc/ortKayip. Tanim farkli."),
        ("Calmar", m.get("calmar"), lean_calmar, "definitional",
         "LEAN dogrudan vermez; CAR/DD'den turetildi. Tanim farkli."),
    ]
    rows = []
    for label, mine, lean, kind, note in specs:
        mine_f = parse_stat(mine)
        rp, verd = _verdict(kind, mine_f, lean)
        rows.append({
            "metric": label, "mine": mine_f, "lean": lean,
            "relPct": rp, "kind": kind, "verdict": verd, "note": note,
        })
    return rows


def _fmt(v) -> str:
    if v is None:
        return "N/A"
    if isinstance(v, float):
        return f"{v:.4f}".rstrip("0").rstrip(".")
    return str(v)


def render_markdown(meta: dict, rows: list[dict]) -> str:
    lines = [
        f"# LEAN Oracle Parite Raporu — {meta['strategy']}",
        "",
        f"- Pencere: **{meta['window']}** ({meta.get('startIso', '?')} -> {meta.get('endIso', '?')})",
        f"- Semboller: {meta.get('symbols')} | execTf: {meta.get('execTf')}",
        f"- LEAN kaynagi: **{meta['leanSource']}**"
        + ("  _(STUB — gercek LEAN degil; boru hatti dogrulamasi)_" if meta["leanSource"] == "stub" else ""),
        f"- Baslangic sermayesi: {meta.get('initialBalance')} USDT",
        f"- Funding: iki tarafta da modellenmiyor (tutarli).",
        "",
        "| Metrik | Benimki | LEAN | Rel % | Sinif | Hukum |",
        "|---|---:|---:|---:|---|---|",
    ]
    for r in rows:
        rel = f"{r['relPct']:.2f}%" if r["relPct"] is not None else "—"
        lines.append(f"| {r['metric']} | {_fmt(r['mine'])} | {_fmt(r['lean'])} | {rel} | {r['kind']} | {r['verdict']} |")

    mech = [r for r in rows if r["kind"] == "mechanical" and r["verdict"] != "N/A"]
    invest = [r for r in mech if r["verdict"] == "INVESTIGATE"]
    lines += ["", "## Yorum", ""]
    if invest:
        lines.append("**Incelenmesi gereken MEKANIK sapmalar (olasi bug):**")
        for r in invest:
            lines.append(f"- **{r['metric']}**: benimki {_fmt(r['mine'])} vs LEAN {_fmt(r['lean'])} "
                         f"(%{r['relPct']:.1f}). {r['note']}")
    else:
        lines.append("Mekanik metriklerin hepsi tolerans icinde. Icra/cikis matematigi LEAN ile uyumlu.")
    lines += ["", "**Beklenen modelleme/tanim farklari (bug degil):**"]
    for r in rows:
        if r["kind"] in ("modeling", "definitional"):
            lines.append(f"- {r['metric']} ({KIND_LABEL.get(r['kind'], r['kind'])}): {r['note']}")
    lines.append("")
    return "\n".join(lines)


def overall_verdict(rows: list[dict]) -> dict:
    """Strateji geneli LEAN uyumu. Win-rate (cikis/TP-SL sadakati) birincil sinyal."""
    by = {r["metric"]: r for r in rows}
    wr = by.get("Win Rate %", {}).get("relPct")
    tt = by.get("Total Trades", {}).get("relPct")
    if wr is None:
        verdict = "none"
    elif wr <= 2.0:
        verdict = "pass"
    elif wr <= 5.0:
        verdict = "warn"
    else:
        verdict = "fail"
    if verdict == "pass" and tt is not None and tt > 15.0:
        verdict = "warn"  # cikis kararlari tutuyor ama islem sayisi cok sapmis
    return {"verdict": verdict, "winRateRel": wr, "tradeRel": tt}


def _update_parity_index(export_dir: Path, meta: dict, rows: list[dict], source: str) -> None:
    index_path = export_dir.parent / "parity_index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        index = {}
    ov = overall_verdict(rows)
    index[meta["strategy"]] = {
        **ov,
        "source": source,
        "runId": export_dir.name,
        "window": meta.get("window"),
        "checkedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")


def run_compare(export_dir: Path, lean_stats: dict, lean_source: str) -> Path:
    my = json.loads((export_dir / "my_metrics.json").read_text())
    cfg = json.loads((export_dir / "config.json").read_text())
    rows = build_rows(my["metrics"], lean_stats, cfg.get("initialBalance", 10000))
    meta = {
        "strategy": my["strategy"], "window": my["window"], "symbols": my.get("symbols"),
        "execTf": cfg.get("execTf"), "startIso": cfg.get("startIso"), "endIso": cfg.get("endIso"),
        "initialBalance": cfg.get("initialBalance"), "leanSource": lean_source,
    }
    (export_dir / "parity_report.json").write_text(json.dumps({"meta": meta, "rows": rows}, indent=2), encoding="utf-8")
    md = render_markdown(meta, rows)
    (export_dir / "parity_report.md").write_text(md, encoding="utf-8")
    _update_parity_index(export_dir, meta, rows, lean_source)
    return export_dir / "parity_report.md"


def load_lean_statistics(path: Path) -> dict:
    """LEAN backtest sonuc JSON'undan istatistik sozlugunu cikar.

    lean CLI tam sonuc dosyasinda ust seviye 'statistics' (string->string) bulunur.
    Stub dosyalari dogrudan istatistik sozlugu olabilir.
    """
    data = json.loads(path.read_text())
    stats = None
    if isinstance(data, dict) and isinstance(data.get("statistics"), dict):
        stats = dict(data["statistics"])
    elif isinstance(data, dict) and isinstance(data.get("Statistics"), dict):
        stats = dict(data["Statistics"])
    else:
        return data
    # Kapali islem sayisini totalPerformance.tradeStatistics'ten cek (LEAN "Total Orders"
    # emir sayisidir, islem degil).
    tp = data.get("totalPerformance") or data.get("TotalPerformance") or {}
    ts = (tp.get("tradeStatistics") or tp.get("TradeStatistics") or {}) if isinstance(tp, dict) else {}
    n = ts.get("totalNumberOfTrades") or ts.get("TotalNumberOfTrades")
    if n is not None:
        stats["Total Trades"] = n
    return stats


def main():
    ap = argparse.ArgumentParser(description="LEAN oracle compare")
    ap.add_argument("--export-dir", required=True)
    ap.add_argument("--lean-stats", required=True, help="LEAN sonuc/istatistik JSON yolu")
    ap.add_argument("--source", default="lean", choices=["lean", "stub"])
    args = ap.parse_args()
    stats = load_lean_statistics(Path(args.lean_stats))
    out = run_compare(Path(args.export_dir), stats, args.source)
    print(f"Rapor: {out}")


if __name__ == "__main__":
    main()
