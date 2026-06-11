import { useEffect } from 'react';
import KpiStrip from '../components/dashboard/KpiStrip';
import PositionsTable from '../components/dashboard/PositionsTable';
import AlertFeed from '../components/dashboard/AlertFeed';
import { useAccountStore } from '../store/account-store';
import { useTradingStore } from '../store/trading-store';
import { usePositionStore } from '../store/position-store';
import { wsClient } from '../lib/ws';
import { debounce } from '../lib/debounce';
import { winRateBreakdown } from '../lib/trade-categorize';

export default function Dashboard() {
  const { accounts, activeAccountId, fetchAccounts } = useAccountStore();
  const { trades, metrics24h, fetchTrades, fetchMetrics24h } = useTradingStore();
  const { positions, fetchPositions } = usePositionStore();
  const account = accounts.find((a) => a.id === activeAccountId);

  const isAll = activeAccountId === null;

  useEffect(() => {
    fetchTrades(activeAccountId);
    fetchMetrics24h(activeAccountId);
  }, [activeAccountId, fetchTrades, fetchMetrics24h]);

  useEffect(() => {
    // Debounce: toplu acilis/kapanislarda (N pozisyon ayni saniyede) her WS olayi
    // basina 4 fetch yerine patlama basina tek refresh.
    const refreshOpened = debounce(() => {
      fetchPositions(activeAccountId);
      fetchAccounts();
    }, 200);
    const refreshClosed = debounce(() => {
      fetchPositions(activeAccountId);
      fetchAccounts();
      fetchTrades(activeAccountId);
      fetchMetrics24h(activeAccountId);
    }, 200);
    const unsub1 = wsClient.on('position:opened', refreshOpened);
    const unsub2 = wsClient.on('position:closed', refreshClosed);
    return () => { unsub1(); unsub2(); refreshOpened.cancel(); refreshClosed.cancel(); };
  }, [activeAccountId, fetchPositions, fetchAccounts, fetchTrades, fetchMetrics24h]);

  if (!isAll && !account) {
    return (
      <div className="flex-1 flex items-center justify-center text-ink-400 text-[11px]">
        Loading...
      </div>
    );
  }

  const sumAccounts = isAll ? accounts : (account ? [account] : []);
  const totalEquity = sumAccounts.reduce((s, a) => s + (a.account_equity ?? a.wallet_balance ?? a.balance ?? 0), 0);
  const totalInitialBal = sumAccounts.reduce((s, a) => s + (a.initial_balance || 0), 0);
  const totalTradeCount = sumAccounts.reduce((s, a) => s + (a.total_trades || 0), 0);
  const totalWinCount = sumAccounts.reduce((s, a) => s + (a.winning_trades || 0), 0);
  const totalPnlAll = sumAccounts.reduce((s, a) => s + (a.total_pnl || 0), 0);

  const winRate = totalTradeCount > 0 ? (totalWinCount / totalTradeCount) * 100 : 0;
  const totalUnrealizedPnl = positions.reduce((s, p) => s + (p.unrealized_pnl || 0), 0);
  const totalRealizedPnl = totalPnlAll;
  const longCount = positions.filter((p) => p.side === 'long').length;
  const shortCount = positions.filter((p) => p.side === 'short').length;
  const longPct = positions.length > 0 ? (longCount / positions.length) * 100 : 50;
  const shortPct = positions.length > 0 ? (shortCount / positions.length) * 100 : 50;

  const closedTrades = trades.filter((t) => t.status === 'closed');

  const netExposure = positions.reduce((s, p) => {
    const notional = p.size * (p.mark_price || p.entry_price);
    return s + (p.side === 'long' ? notional : -notional);
  }, 0);
  const grossExposure = positions.reduce((s, p) => s + p.size * (p.mark_price || p.entry_price), 0);

  const slPct = account?.sl_percent || 3;
  const avgR = closedTrades.length > 0
    ? closedTrades.reduce((s, t) => s + ((t.pnl_percent || 0) / slPct), 0) / closedTrades.length
    : 0;

  const totalPeak = sumAccounts.reduce(
    (s, a) => s + Math.max(a.peak_equity ?? 0, a.initial_balance ?? 0, a.account_equity ?? a.wallet_balance ?? a.balance ?? 0),
    0,
  );
  const observedDd = totalPeak > 0 ? Math.max(0, ((totalPeak - totalEquity) / totalPeak) * 100) : 0;
  const wrBreakdown = winRateBreakdown(trades);

  const kpiData = {
    netLiq: totalEquity,
    todayChange: totalUnrealizedPnl + metrics24h.realizedPnl,
    unrealPnl: totalUnrealizedPnl,
    realPnl: totalRealizedPnl,
    netExposure,
    grossExposure,
    longPct,
    shortPct,
    sharpe: 0,
    maxDd: observedDd,
    winRate,
    totalTrades: totalTradeCount,
    avgR,
    fees24h: metrics24h.fees,
    rebates: 0,
    wrBreakdown,
  };

  return (
    <div className="flex flex-1 min-h-0">
      <div className="flex-1 min-w-0 flex flex-col">
        <KpiStrip data={kpiData} />
        <div className="flex-1 overflow-auto">
          <PositionsTable />
        </div>
      </div>
      <div className="w-[188px] shrink-0">
        <AlertFeed />
      </div>
    </div>
  );
}
