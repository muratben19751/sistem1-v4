"""STUB LEAN istatistikleri: Docker/bulut yokken export->compare boru hattini uctan uca
dogrulamak icin kullanilir. Kendi metriklerimden LEAN-sekilli bir istatistik sozlugu
uretir; gercek LEAN motoru DEGILDIR (rapor bunu acikca isaretler).

Modelleme farklarini taklit eder: ekstra fee icin getiriyi hafif kisar, DD'yi bar-ici
icin hafif buyutur, Sharpe/Profit-Loss Ratio'yu tanim farki gosterecek sekilde uretir.
"""
import json
from pathlib import Path


def generate(export_dir: Path) -> Path:
    my = json.loads((export_dir / "my_metrics.json").read_text())
    cfg = json.loads((export_dir / "config.json").read_text())
    m = my["metrics"]
    init = cfg.get("initialBalance", 10000)
    days = max(1, (cfg["endMs"] - cfg["startMs"]) / 86_400_000)

    net_pct = (m.get("totalPnlPct") or 0.0) * 0.997  # ~%0.3 ekstra fee/slippage
    car = net_pct * (365.0 / days)
    avg_win = abs(m.get("avgWin") or 0.0)
    avg_loss = abs(m.get("avgLoss") or 0.0)
    pl_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0

    stats = {
        "Total Trades": str(int(m.get("trades") or 0)),
        "Win Rate": f"{m.get('winRate') or 0:.0f}%",
        "Loss Rate": f"{100 - (m.get('winRate') or 0):.0f}%",
        "Net Profit": f"{net_pct:.3f}%",
        "Compounding Annual Return": f"{car:.3f}%",
        "Drawdown": f"{(m.get('maxDrawdown') or 0) * 1.02:.3f}%",
        "Sharpe Ratio": f"{(m.get('sharpe') or 0) * 0.6:.3f}",
        "Profit-Loss Ratio": f"{pl_ratio:.2f}",
        "Average Win": f"{(m.get('avgWin') or 0) / init * 100:.3f}%",
        "Average Loss": f"{(m.get('avgLoss') or 0) / init * 100:.3f}%",
        "Total Fees": f"${abs(net_pct) * init * 0.01:.2f}",
    }
    out = export_dir / "lean_stub_statistics.json"
    out.write_text(json.dumps({"statistics": stats, "_stub": True}, indent=2))
    return out
