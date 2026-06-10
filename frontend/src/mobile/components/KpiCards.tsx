import { useAccountStore } from '../../store/account-store';
import { usePositionStore } from '../../store/position-store';
import { useTradingStore } from '../../store/trading-store';
import { formatUsd, formatPercent } from '../../lib/formatters';

function equityOf(a: { account_equity?: number; wallet_balance?: number; balance?: number }): number {
  return a.account_equity ?? a.wallet_balance ?? a.balance ?? 0;
}

function Card({ label, value, tone }: { label: string; value: string; tone?: 'up' | 'down' | 'neutral' }) {
  const color = tone === 'up' ? 'text-up' : tone === 'down' ? 'text-down' : 'text-ink-50';
  return (
    <div className="rounded-md border border-white/5 bg-ink-850 px-3 py-2.5">
      <div className="text-[10px] tracking-[0.15em] uppercase text-ink-500">{label}</div>
      <div className={`mt-0.5 text-lg font-semibold num leading-tight ${color}`}>{value}</div>
    </div>
  );
}

export default function KpiCards() {
  const { accounts, activeAccountId } = useAccountStore();
  const positions = usePositionStore((s) => s.positions);
  const metrics24h = useTradingStore((s) => s.metrics24h);

  const isAll = activeAccountId === null;
  const scope = isAll ? accounts : accounts.filter((a) => a.id === activeAccountId);

  const equity = scope.reduce((s, a) => s + equityOf(a), 0);
  const realizedPnl = scope.reduce((s, a) => s + (a.total_pnl || 0), 0);
  const unrealizedPnl = positions.reduce((s, p) => s + (p.unrealized_pnl || 0), 0);
  const totalTrades = scope.reduce((s, a) => s + (a.total_trades || 0), 0);
  const winning = scope.reduce((s, a) => s + (a.winning_trades || 0), 0);
  const winRate = totalTrades > 0 ? (winning / totalTrades) * 100 : 0;

  const netExposure = positions.reduce((s, p) => {
    const notional = p.size * (p.mark_price || p.entry_price);
    return s + (p.side === 'long' ? notional : -notional);
  }, 0);

  const dayChange = unrealizedPnl + metrics24h.realizedPnl;

  const tone = (n: number) => (n > 0 ? 'up' : n < 0 ? 'down' : 'neutral');

  return (
    <div className="grid grid-cols-2 gap-2">
      <Card label="Açık K/Z" value={`${unrealizedPnl >= 0 ? '+' : ''}${formatUsd(unrealizedPnl)}`} tone={tone(unrealizedPnl)} />
      <Card label="Toplam K/Z" value={`${realizedPnl >= 0 ? '+' : ''}${formatUsd(realizedPnl)}`} tone={tone(realizedPnl)} />
      <Card label="Bugün (≈)" value={`${dayChange >= 0 ? '+' : ''}${formatUsd(dayChange)}`} tone={tone(dayChange)} />
      <Card label="Win Rate" value={`${winRate.toFixed(1)}%`} tone={winRate >= 50 ? 'up' : 'neutral'} />
      <Card label="Net Pozisyon" value={formatUsd(netExposure)} tone={tone(netExposure)} />
      <Card label="Ücret (24s)" value={formatUsd(metrics24h.fees)} tone="neutral" />
    </div>
  );
}
