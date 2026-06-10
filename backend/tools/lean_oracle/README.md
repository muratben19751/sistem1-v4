# LEAN Oracle — run_backtest icra dogrulamasi

Kendi `run_backtest()` motorumun **icra matematigini** (giris -> TP/SL/cikis, fee,
slippage, kaldirac, portfoy yurumesi, drawdown, equity) QuantConnect **LEAN**'in
kanitlanmis motoruyla BAGIMSIZ olarak kiyaslar ve bir **parite raporu** uretir.

## Tasarim kisidi (onemli)
27 kural / sinyal skorlama LEAN'de **yeniden yazilmaz**. Kendi backtest'imin urettigi
giris kararlari (entryMs, sembol, yon, referans fiyat) + icra config'i (TP/SL/kaldirac/
pozisyon/fee/slippage) LEAN'e beslenir. LEAN yalnizca **icrayi** simule eder. Boylece
dogrulanan sey sinyal uretimi degil, en cok gizli bug barindiran **mekanik icra**dir.

## Akis
```
export  -> run_backtest() kostur, giris sinyallerini + metrikleri + mumlari yaz
LEAN    -> sinyalleri replay et, cikis/fee/portfoy'u LEAN motoruna birak
compare -> LEAN istatistikleri vs kendi metriklerim -> parite raporu (md + json)
```

## Tek komut
```bash
cd backend
# Docker yokken (boru hatti dogrulamasi, stub LEAN istatistigi):
python -m lean_oracle.run --window 90d --symbols TOP10

# Gercek LEAN (lean CLI + Docker GEREKIR):
pip install -r tools/lean_oracle/requirements.txt
python -m lean_oracle.run --window 90d --symbols TOP10 --mode lean
```
> `python -m lean_oracle.run` calistirmak icin `tools/` PYTHONPATH'te olmali, veya
> `cd backend/tools && python -m lean_oracle.run ...`. Modul `import app`'i kendi
> bootstrap'iyla cozer.

Parametreler:
- `--window 90d` test penceresi (Nd). Pencere sonu = en yeni alarm zamani.
- `--symbols TOP10` sembol evreni (maxSymbols=N) veya `ALL`.
- `--strategy AD` optimizer_results'tan strateji adi (yoksa en iyi calmar otomatik).
- `--exec-tf 5` icra zaman dilimi (mum kaynagi).
- `--mode stub|lean` (varsayilan stub).
- `--online` cache yetmezse Bybit'ten cek (aksi halde yalnizca cache okunur).

## Ciktilar (`tools/lean_oracle/oracle_export/<runId>/`)
- `signals.json` LEAN'in replay edecegi girisler
- `config.json` icra parametreleri (fee/slippage/kaldirac/TP-SL)
- `data/<SYMBOL>.csv` execTf mumlari (LEAN custom data)
- `my_metrics.json` kendi metriklerim + trades
- `parity_report.md` / `parity_report.json` parite raporu

## Rapor siniflari
- **mechanical**: ayni seyi olcer (trades, NetProfit, WinRate). <%1 PASS, <%5 MINOR,
  **>%5 INVESTIGATE = olasi bug**.
- **modeling**: kucuk metodoloji farki (orn. DD bar-ici vs kapanis-bazli).
- **definitional**: tanim farkli (Sharpe yillıklama, ProfitFactor vs Profit-Loss Ratio,
  $ vs % birim) — sapma BEKLENIR, bug degil.

## Modelleme notlari
- **Funding/OI** iki tarafta da modellenmez -> tutarli.
- Giris fiyati referans (pre-slippage) verilir; slippage LEAN tarafinda uygulanir
  (cift-slippage onlenir).
- LEAN icra opsiyonel olarak maxPositions/sembol-tek/sermaye gating'i tekrar uygular.

## Docker notu
LEAN lokal backtest, algoritmayi bir **Docker** konteynerinde kosar. Docker Desktop
kurulu ve calisir olmali. Kurulu degilse `--mode stub` boru hattini Docker'siz dogrular;
gercek motor karsilastirmasi icin Docker (veya QC bulut: `lean cloud backtest`) gerekir.

## Izolasyon
Ana DB salt-okunur (kline_cache / alerts / optimizer_results). Canli trading yoluna,
portlara, v3'e dokunmaz. Bagimliliklar yalnizca bu klasorde.
