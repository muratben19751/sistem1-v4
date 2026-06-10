import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import { useAccountStore } from '../../store/account-store';
import { usePositionStore } from '../../store/position-store';
import { useTradingStore } from '../../store/trading-store';
import { useUiStore } from '../../store/ui-store';
import { wsClient } from '../../lib/ws';
import KpiCards from '../components/KpiCards';
import PositionCard from '../components/PositionCard';

export default function MobileOverview() {
  const activeAccountId = useAccountStore((s) => s.activeAccountId);
  const accounts = useAccountStore((s) => s.accounts);
  const { positions, fetchPositions } = usePositionStore();
  const { fetchTrades, fetchMetrics24h } = useTradingStore();
  const botStatuses = useUiStore((s) => s.botStatuses);

  useEffect(() => {
    fetchPositions(activeAccountId);
    fetchTrades(activeAccountId);
    fetchMetrics24h(activeAccountId);
    const unsubs = [
      wsClient.on('position:opened', () => fetchPositions(activeAccountId)),
      wsClient.on('position:closed', () => {
        fetchPositions(activeAccountId);
        fetchTrades(activeAccountId);
        fetchMetrics24h(activeAccountId);
      }),
      wsClient.on('order:filled', () => fetchPositions(activeAccountId)),
    ];
    return () => unsubs.forEach((fn) => fn());
  }, [activeAccountId, fetchPositions, fetchTrades, fetchMetrics24h]);

  const runningBots = accounts.filter((a) => botStatuses[a.id]?.status === 'running').length;

  const sorted = [...positions].sort((a, b) => Math.abs(b.unrealized_pnl || 0) - Math.abs(a.unrealized_pnl || 0));
  const top = sorted.slice(0, 4);

  return (
    <div className="p-3 space-y-3">
      <KpiCards />

      <Link to="/m/bots" className="flex items-center justify-between rounded-md border border-white/5 bg-ink-850 px-3 py-3 active:bg-ink-800">
        <div className="text-sm text-ink-200">
          Botlar
          <span className="ml-2 text-ink-400 text-xs">{runningBots}/{accounts.length} çalışıyor</span>
        </div>
        <ChevronRight size={16} className="text-ink-500" />
      </Link>

      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] tracking-[0.2em] uppercase text-ink-500">Açık Pozisyonlar</span>
          {positions.length > top.length && (
            <Link to="/m/positions" className="text-[11px] text-info">tümü ({positions.length})</Link>
          )}
        </div>
        {positions.length === 0 ? (
          <p className="text-center text-ink-500 text-sm py-8">Açık pozisyon yok</p>
        ) : (
          <div className="space-y-2">
            {top.map((p) => <PositionCard key={p.id} p={p} />)}
          </div>
        )}
      </div>
    </div>
  );
}
