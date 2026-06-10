"""LEAN algoritmasi: kendi backtest'imin URETTIGI girisleri replay eder; cikis/fee/
portfoy'u LEAN motoruna birakir. Sinyal uretimi (27 kural) burada YOKTUR.

Sadakat icin:
- TP/SL seviyeleri motorumun kullandigi MUTLAK fiyatlardir (signals.json) -> LEAN'de
  ATR/yuzde yeniden hesaplanmaz.
- Cikis KAPANIS-bazli: her barin kapanisi TP/SL'i gecince kapanista cikilir (motorumla
  ayni metodoloji).
- Komisyon: taker yuzdesi custom-data security'sine fee modeli olarak uygulanir.

Mumlar kendi SQLite cache'imden export edilen CSV'lerden (custom PythonData) gelir.
"""
import json
import os
from datetime import datetime, timezone

from AlgorithmImports import *


class OracleBar(PythonData):
    def GetSource(self, config, date, isLive):
        path = os.path.join(os.path.dirname(__file__), "oracle_input", "data", f"{config.Symbol.Value}.csv")
        return SubscriptionDataSource(path, SubscriptionTransportMedium.LocalFile)

    def Reader(self, config, line, date, isLive):
        if not line or not line[0].isdigit():
            return None
        p = line.split(",")
        bar = OracleBar()
        bar.Symbol = config.Symbol
        bar.Time = datetime.fromtimestamp(int(p[0]) / 1000.0, tz=timezone.utc).replace(tzinfo=None)
        bar.Value = float(p[4])
        bar["open"] = float(p[1])
        bar["high"] = float(p[2])
        bar["low"] = float(p[3])
        bar["close"] = float(p[4])
        bar["volume"] = float(p[5])
        return bar


class PercentFeeModel(FeeModel):
    """Her dolumda notional * pct komisyon (motorumun taker'iyla eslesir)."""

    def __init__(self, pct):
        super().__init__()
        self.pct = pct

    def GetOrderFee(self, parameters):
        security = parameters.Security
        order = parameters.Order
        fee = abs(order.AbsoluteQuantity) * float(security.Price) * self.pct
        return OrderFee(CashAmount(fee, "USDT"))


def _load(name):
    with open(os.path.join(os.path.dirname(__file__), "oracle_input", name)) as f:
        return json.load(f)


class OracleExecution(QCAlgorithm):
    def Initialize(self):
        self.cfg = _load("config.json")
        signals = _load("signals.json")

        start = datetime.fromtimestamp(self.cfg["startMs"] / 1000.0, tz=timezone.utc)
        end = datetime.fromtimestamp(self.cfg["endMs"] / 1000.0, tz=timezone.utc)
        self.SetStartDate(start.year, start.month, start.day)
        self.SetEndDate(end.year, end.month, end.day)
        self.SetAccountCurrency(self.cfg.get("accountCurrency", "USDT"))
        self.SetCash(self.cfg.get("initialBalance", 10000))

        self.max_positions = int(self.cfg.get("maxPositions", 1))
        self.size_pct = float(self.cfg.get("positionSizePct", 2)) / 100.0
        self.leverage = float(self.cfg.get("leverage", 1) or 1)
        taker = float(self.cfg.get("takerFeePct", 0.055)) / 100.0

        self.symbols = {}
        self.pending = {}
        self.pos = {}  # symbol -> {"side","tp","sl"}
        for s in signals:
            sym = s["symbol"]
            if sym not in self.symbols:
                sec = self.AddData(OracleBar, sym, Resolution.Minute)
                sec.SetLeverage(self.leverage)
                sec.SetFeeModel(PercentFeeModel(taker))
                self.symbols[sym] = sec.Symbol
            self.pending.setdefault(sym, []).append({
                "entryMs": int(s["entryMs"]), "side": s["side"],
                "tp": s.get("tpPrice"), "sl": s.get("slPrice"), "qty": s.get("qty"),
            })
        for sym in self.pending:
            self.pending[sym].sort(key=lambda x: x["entryMs"])

    def _open_count(self):
        return sum(1 for q in self.symbols.values() if self.Portfolio[q].Invested)

    def OnData(self, data):
        now_ms = int(self.Time.replace(tzinfo=timezone.utc).timestamp() * 1000)
        for sym, qsym in self.symbols.items():
            if not data.ContainsKey(qsym) or data[qsym] is None:
                continue
            price = float(data[qsym].Value)
            if price <= 0:
                continue

            # 1) Kapanis-bazli cikis: acik pozisyon TP/SL'i kapanista gectiyse kapat.
            meta = self.pos.get(sym)
            if meta and self.Portfolio[qsym].Invested:
                tp, sl = meta["tp"], meta["sl"]
                exit_now = False
                if meta["side"] == "long":
                    if (sl is not None and price <= sl) or (tp is not None and price >= tp):
                        exit_now = True
                else:
                    if (sl is not None and price >= sl) or (tp is not None and price <= tp):
                        exit_now = True
                if exit_now:
                    self.Liquidate(qsym)
                    self.pos.pop(sym, None)
                    continue

            # 2) Vakti gelen girisleri ac (gating: maxPositions + sembol-tek + sermaye).
            queue = self.pending.get(sym)
            if not queue:
                continue
            nxt = queue[0]
            if now_ms < nxt["entryMs"]:
                continue
            queue.pop(0)
            if self.Portfolio[qsym].Invested or self._open_count() >= self.max_positions:
                continue
            # Boyut motorumun kullandigi qty'dir (LEAN'de yeniden hesaplanmaz).
            qty = nxt.get("qty")
            if qty is None:
                qty = (self.Portfolio.TotalPortfolioValue * self.size_pct * self.leverage) / price
            qty = abs(qty)
            if nxt["side"] == "short":
                qty = -qty
            if abs(qty) <= 0:
                continue
            self.MarketOrder(qsym, qty)
            self.pos[sym] = {"side": nxt["side"], "tp": nxt["tp"], "sl": nxt["sl"]}
