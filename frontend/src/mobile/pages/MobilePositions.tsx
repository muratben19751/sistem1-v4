import { useEffect } from 'react';
import { useAccountStore } from '../../store/account-store';
import { usePositionStore } from '../../store/position-store';
import { wsClient } from '../../lib/ws';
import { aggregatePositionPnlPercent } from '../../lib/position-math';
import { formatUsd, formatPercent } from '../../lib/formatters';
import PositionCard from '../components/PositionCard';

export default function MobilePositions() {
  const activeAccountId = useAccountStore((s) => s.activeAccountId);
  const { positions, fetchPositions, removePosition } = usePositionStore();

  useEffect(() => {
    fetchPositions(activeAccountId);
    const unsubs = [
      wsClient.on('position:opened', () => fetchPositions(activeAccountId)),
      wsClient.on('order:filled', () => fetchPositions(activeAccountId)),
      wsClient.on('position:closed', (data) => {
        if (data.partial) {
          fetchPositions(activeAccountId);
          return;
        }
        removePosition(data.symbol, data.side, data.accountId);
      }),
    ];
    return () => unsubs.forEach((fn) => fn());
  }, [activeAccountId, fetchPositions, removePosition]);

  const totalPnl = positions.reduce((s, p) => s + (p.unrealized_pnl || 0), 0);
  const totalPct = aggregatePositionPnlPercent(positions);
  const longCount = positions.filter((p) => p.side === 'long').length;
  const shortCount = positions.filter((p) => p.side === 'short').length;

  return (
    <div className="p-3 space-y-2">
      <div className="flex items-center justify-between rounded-md border border-white/5 bg-ink-850 px-3 py-2.5">
        <div className="text-xs text-ink-400">
          {positions.length} açık
          <span className="text-up ml-2">{longCount}L</span>
          <span className="text-ink-500 mx-0.5">/</span>
          <span className="text-down">{shortCount}S</span>
        </div>
        <div className="text-right">
          <div className={`text-base font-semibold num ${totalPnl >= 0 ? 'text-up' : 'text-down'}`}>
            {totalPnl >= 0 ? '+' : ''}{formatUsd(totalPnl)}
          </div>
          <div className={`text-[11px] num ${totalPct >= 0 ? 'text-up' : 'text-down'}`}>{formatPercent(totalPct)}</div>
        </div>
      </div>

      {positions.length === 0 ? (
        <p className="text-center text-ink-500 text-sm py-12">Açık pozisyon yok</p>
      ) : (
        positions.map((p) => <PositionCard key={p.id} p={p} />)
      )}
    </div>
  );
}
