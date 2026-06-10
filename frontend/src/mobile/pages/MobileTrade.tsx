import { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useAccountStore } from '../../store/account-store';
import { useTradingStore } from '../../store/trading-store';
import { wsClient } from '../../lib/ws';
import { formatUsd, formatPercent, formatDate } from '../../lib/formatters';
import OrderSheet from '../components/OrderSheet';
import TradeDetailSheet, { type MobileTrade as MTrade } from '../components/TradeDetailSheet';

export default function MobileTrade() {
  const activeAccountId = useAccountStore((s) => s.activeAccountId);
  const { trades, loading, fetchTrades } = useTradingStore();
  const [showOrder, setShowOrder] = useState(false);
  const [selected, setSelected] = useState<MTrade | null>(null);

  useEffect(() => {
    fetchTrades(activeAccountId, 200);
    const unsubs = [
      wsClient.on('position:closed', () => fetchTrades(activeAccountId, 200)),
      wsClient.on('order:filled', () => fetchTrades(activeAccountId, 200)),
    ];
    return () => unsubs.forEach((fn) => fn());
  }, [activeAccountId, fetchTrades]);

  const closed = (trades as MTrade[]).filter((t) => t.status === 'closed');

  return (
    <div className="p-3 space-y-3">
      <div className="rounded-md border border-white/5 bg-ink-850">
        <button
          onClick={() => setShowOrder((v) => !v)}
          className="w-full flex items-center justify-between px-3 min-h-[48px] text-sm text-ink-100"
        >
          <span>Manuel Emir Aç</span>
          {showOrder ? <ChevronDown size={18} className="text-ink-400" /> : <ChevronRight size={18} className="text-ink-400" />}
        </button>
        {showOrder && (
          <div className="border-t border-white/5 p-3">
            <OrderSheet />
          </div>
        )}
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] tracking-[0.2em] uppercase text-ink-500">Kapanan İşlemler</span>
          {closed.length > 0 && <span className="text-[11px] text-ink-400 num">{closed.length}</span>}
        </div>

        {loading && closed.length === 0 ? (
          <p className="text-center text-ink-500 text-sm py-8">Yükleniyor...</p>
        ) : closed.length === 0 ? (
          <p className="text-center text-ink-500 text-sm py-8">Kapanan işlem yok</p>
        ) : (
          <div className="space-y-1.5">
            {closed.map((t) => {
              const pnl = t.pnl || 0;
              const up = pnl >= 0;
              return (
                <button
                  key={t.id}
                  onClick={() => setSelected(t)}
                  className="w-full flex items-center justify-between rounded-md border border-white/5 bg-ink-850 px-3 py-2.5 text-left active:bg-ink-800"
                >
                  <div className="min-w-0">
                    <div className="text-sm text-ink-100 flex items-center gap-2">
                      <span className="font-medium truncate">{t.symbol}</span>
                      <span className={`text-xs ${t.side === 'long' ? 'text-up' : 'text-down'}`}>{t.side.toUpperCase()}</span>
                    </div>
                    <div className="text-[10px] text-ink-500">{formatDate(t.closed_at)}</div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <div className="text-right">
                      <div className={`text-sm font-medium num ${up ? 'text-up' : 'text-down'}`}>
                        {up ? '+' : ''}{formatUsd(pnl)}
                      </div>
                      <div className={`text-[11px] num ${up ? 'text-up' : 'text-down'}`}>{formatPercent(t.pnl_percent)}</div>
                    </div>
                    <ChevronRight size={16} className="text-ink-600" />
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {selected && <TradeDetailSheet trade={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
