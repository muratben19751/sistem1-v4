import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import TradingViewChart from '../components/charts/TradingViewChart';
import { useAccountStore } from '../store/account-store';
import { useTradingStore } from '../store/trading-store';
import { usePositionStore } from '../store/position-store';
import { api } from '../lib/api';
import { formatUsd, formatPercent } from '../lib/formatters';
import { Search } from 'lucide-react';

type Preset = 'scalp' | 'swing';

const PRESETS: Record<Preset, { label: string; panels: Array<{ label: string; interval: string; chartType: 'heikinashi' | 'bar' }> }> = {
  scalp: {
    label: 'Scalp',
    panels: [
      { label: '1m', interval: '1', chartType: 'bar' },
      { label: '5m', interval: '5', chartType: 'heikinashi' },
      { label: '1H', interval: '60', chartType: 'bar' },
    ],
  },
  swing: {
    label: 'Swing',
    panels: [
      { label: '1H', interval: '60', chartType: 'bar' },
      { label: '4H', interval: '240', chartType: 'bar' },
      { label: '1D', interval: 'D', chartType: 'bar' },
    ],
  },
};

interface TickerInfo {
  symbol: string; lastPrice: string; price24hPcnt: string;
  highPrice24h: string; lowPrice24h: string; volume24h: string; fundingRate: string;
}

const normalizeSymbol = (raw: string | null): string => {
  if (!raw) return 'BTCUSDT';
  const c = raw.trim().toUpperCase();
  return c.endsWith('USDT') ? c : c + 'USDT';
};

export default function Charts() {
  const [searchParams] = useSearchParams();
  const { activeAccountId } = useAccountStore();
  const { trades, fetchTrades } = useTradingStore();
  const { positions, fetchPositions } = usePositionStore();
  const [symbol, setSymbol] = useState(() => normalizeSymbol(searchParams.get('symbol')));
  const [input, setInput] = useState(symbol);
  const [ticker, setTicker] = useState<TickerInfo | null>(null);
  const [loadedCount, setLoadedCount] = useState(0);
  const [preset, setPreset] = useState<Preset>('scalp');

  const panels = PRESETS[preset].panels;

  useEffect(() => {
    const q = searchParams.get('symbol');
    if (!q) return;
    const norm = normalizeSymbol(q);
    setSymbol(norm);
    setInput(norm);
  }, [searchParams]);

  useEffect(() => {
    fetchTrades(activeAccountId, 100);
    fetchPositions(activeAccountId);
  }, [activeAccountId, fetchTrades, fetchPositions]);

  const symbolPositions = positions.filter((p) => p.symbol === symbol);
  const chartPositionsKey = symbolPositions
    .map((p) => `${p.side}:${p.entry_price}:${p.tp_price ?? ''}:${p.sl_price ?? ''}`)
    .join('|');
  const chartPositions = useMemo(() => symbolPositions.map((p) => ({
    symbol: p.symbol,
    side: p.side as 'long' | 'short',
    entry_price: p.entry_price,
    tp_price: p.tp_price,
    sl_price: p.sl_price,
  })), [chartPositionsKey]);

  useEffect(() => {
    api.get<TickerInfo>(`/scanner/ticker/${symbol}`).then(setTicker).catch(() => setTicker(null));
  }, [symbol]);

  useEffect(() => {
    if (loadedCount < panels.length) {
      const timer = setTimeout(() => setLoadedCount((c) => c + 1), 100);
      return () => clearTimeout(timer);
    }
  }, [loadedCount, panels.length]);

  useEffect(() => { setLoadedCount(1); }, [symbol, preset]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const clean = input.trim().toUpperCase();
    if (clean) setSymbol(clean.endsWith('USDT') ? clean : clean + 'USDT');
  };

  const symbolTrades = trades.filter((t) => t.symbol === symbol);
  const pricePcnt = ticker ? parseFloat(ticker.price24hPcnt) * 100 : 0;

  return (
    <div className="flex flex-col h-[calc(100vh-48px)]">
      <div className="h-9 bg-ink-850 flex items-center gap-4 px-3 shrink-0 border-b border-white/5">
        <form onSubmit={handleSubmit} className="flex items-center gap-2">
          <div className="relative">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400" />
            <input type="text" value={input} onChange={(e) => setInput(e.target.value.toUpperCase())}
              placeholder="BTCUSDT"
              className="bg-ink-800 text-ink-100 text-[11px] pl-7 pr-2 py-1 border border-white/5 focus:outline-none focus:border-white/10 w-32" />
          </div>
          <button type="submit" className="bg-up/15 border border-up/30 text-up text-[11px] px-3 py-1 hover:bg-up/25 transition-colors">Go</button>
        </form>

        <div className="flex items-center gap-px">
          {(Object.keys(PRESETS) as Preset[]).map((key) => (
            <button key={key} onClick={() => setPreset(key)}
              className={`px-3 py-1 text-[9px] tracking-[0.25em] uppercase font-medium transition-colors ${
                preset === key
                  ? 'bg-ink-700 text-ink-50 border border-white/10'
                  : 'text-ink-300 hover:text-ink-100 border border-transparent'
              }`}>
              {PRESETS[key].label}
            </button>
          ))}
        </div>

        {ticker && (
          <div className="flex items-center gap-4 ml-auto">
            <span className="text-ink-50 text-[11px] font-medium">{symbol.replace('USDT', '')}<span className="text-ink-400">/USDT</span></span>
            <span className="text-ink-50 text-[11px] num">${parseFloat(ticker.lastPrice).toLocaleString()}</span>
            <span className={`text-[11px] num ${pricePcnt >= 0 ? 'text-up' : 'text-down'}`}>{formatPercent(pricePcnt)}</span>
            <span className="text-[9px] tracking-[0.25em] text-ink-400">H <span className="text-ink-200 num">${parseFloat(ticker.highPrice24h).toLocaleString()}</span></span>
            <span className="text-[9px] tracking-[0.25em] text-ink-400">L <span className="text-ink-200 num">${parseFloat(ticker.lowPrice24h).toLocaleString()}</span></span>
            <span className="text-[9px] tracking-[0.25em] text-ink-400">FR <span className={`num ${parseFloat(ticker.fundingRate) > 0 ? 'text-up' : 'text-down'}`}>{(parseFloat(ticker.fundingRate) * 100).toFixed(4)}%</span></span>
          </div>
        )}
      </div>

      <div className="flex-1 grid grid-cols-3 gap-px bg-ink-800 min-h-0">
        {panels.map((tf, idx) => (
          <div key={`${preset}-${tf.interval}`} className="relative bg-ink-900 overflow-hidden min-h-0">
            <div className="absolute top-1 left-1 z-20 bg-ink-900/90 px-2 py-0.5 pointer-events-none flex items-center gap-1.5">
              <span className="text-up text-[9px] tracking-[0.25em] font-medium">{tf.label}</span>
              <span className="text-ink-400 text-[9px] tracking-[0.25em]">{tf.chartType === 'heikinashi' ? 'HA' : 'BAR'}</span>
            </div>
            {idx < loadedCount ? (
              <TradingViewChart symbol={symbol} interval={tf.interval} chartType={tf.chartType} positions={chartPositions} />
            ) : (
              <div className="flex items-center justify-center h-full text-ink-400 text-[9px] tracking-[0.25em] animate-pulse">
                LOADING
              </div>
            )}
          </div>
        ))}
      </div>

      {symbolTrades.length > 0 && (
        <div className="shrink-0 border-t border-white/5">
          <div className="px-3 py-1.5 border-b border-white/5">
            <span className="text-[9px] tracking-[0.25em] text-ink-400 uppercase">{symbol} Trade History</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-white/5">
                  <th className="text-left px-3 py-1.5 text-[9px] tracking-[0.25em] text-ink-400 font-normal uppercase">Side</th>
                  <th className="text-right px-3 py-1.5 text-[9px] tracking-[0.25em] text-ink-400 font-normal uppercase">Entry</th>
                  <th className="text-right px-3 py-1.5 text-[9px] tracking-[0.25em] text-ink-400 font-normal uppercase">Exit</th>
                  <th className="text-right px-3 py-1.5 text-[9px] tracking-[0.25em] text-ink-400 font-normal uppercase">PnL</th>
                  <th className="text-left px-3 py-1.5 text-[9px] tracking-[0.25em] text-ink-400 font-normal uppercase">Status</th>
                </tr>
              </thead>
              <tbody>
                {symbolTrades.slice(0, 10).map((t) => (
                  <tr key={t.id} className="border-b border-white/5">
                    <td className="px-3 py-1.5">
                      <span className={`text-[11px] ${t.side === 'long' ? 'text-up' : 'text-down'}`}>{t.side.toUpperCase()}</span>
                    </td>
                    <td className="px-3 py-1.5 text-right text-[11px] text-ink-200 num">{t.entry_price.toFixed(4)}</td>
                    <td className="px-3 py-1.5 text-right text-[11px] text-ink-200 num">{t.exit_price?.toFixed(4) ?? '-'}</td>
                    <td className={`px-3 py-1.5 text-right text-[11px] num ${(t.pnl || 0) >= 0 ? 'text-up' : 'text-down'}`}>
                      {t.pnl != null ? formatUsd(t.pnl) : '-'}
                    </td>
                    <td className="px-3 py-1.5 text-[11px] text-ink-400">{t.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
