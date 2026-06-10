import { useEffect, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAccountStore } from '../store/account-store';
import { useTradingStore } from '../store/trading-store';
import { usePositionStore } from '../store/position-store';
import { formatUsd, formatPercent, formatPrice, formatDuration } from '../lib/formatters';
import { positionPnlPercent, slDistancePct, slDistanceTone } from '../lib/position-math';
import { wsClient } from '../lib/ws';
import { api } from '../lib/api';
import { ArrowUpRight, ArrowDownRight, ChevronLeft, ChevronRight, X } from 'lucide-react';
import { winRateBreakdown, categorizeTrade, CATEGORY_LABELS } from '../lib/trade-categorize';

type FilterTab = 'all' | 'closed' | 'win' | 'lose';

const RULE_LABELS: Record<string, string> = {
  rule_01_extreme_rsi: 'Extreme RSI',
  rule_02_h1_trend: 'H1 Trend',
  rule_03_5m_rsi: '5m RSI',
  rule_04_stochrsi_extreme: 'StochRSI',
  rule_05_volume: 'Volume Spike',
  rule_06_tf_divergence: 'TF Divergence',
  rule_07_multi_tf: 'Multi-TF',
  rule_08_all_rsi_extreme: 'All RSI Extreme',
  rule_09_pump_dump: 'Pump/Dump',
  rule_10_funding_rate: 'Funding Rate',
  rule_11_open_interest: 'Open Interest',
  rule_12_anti_chase: 'Anti-Chase',
  rule_13_conviction: 'Conviction',
  rule_14_rsi_divergence: 'RSI Div+NW+WT',
};

function formatSignal(t: { entry_reason: string | null; active_rules: string | null; side: string }): string {
  const rules = t.active_rules?.split(',').map((s) => s.split(':')[0]).filter(Boolean) || [];
  const topRule = rules[0] ? (RULE_LABELS[rules[0]] || rules[0]) : '';
  const dir = t.side === 'long' ? 'UP' : 'DOWN';
  if (t.entry_reason === 'manual' || t.entry_reason === 'manual_suggested' || t.entry_reason === 'manual_order') {
    return topRule ? `MANUAL / ${topRule} ${dir}` : `MANUAL ${dir}`;
  }
  if (rules.some((r) => r.includes('rsi_divergence'))) return `SNIPER / RSI DIV ${dir}`;
  if (rules.some((r) => r.includes('h1_trend'))) return `SCANNER / H1 TREND ${dir}`;
  if (rules.some((r) => r.includes('multi_tf'))) return `SCANNER / MULTI-TF ${dir}`;
  if (rules.some((r) => r.includes('extreme_rsi'))) return `SCANNER / RSI EXTREME ${dir}`;
  if (rules.some((r) => r.includes('pump_dump'))) return `SCANNER / PUMP-DUMP ${dir}`;
  if (rules.some((r) => r.includes('volume'))) return `SCANNER / VOLUME ${dir}`;
  if (topRule) return `SCANNER / ${topRule} ${dir}`;
  return `SCANNER ${dir}`;
}

function formatCloseReason(reason: string | null): { text: string; color: string } {
  if (!reason) return { text: '-', color: 'text-ink-500' };
  const r = reason.toLowerCase();
  if (r.includes('trail')) return { text: 'TRAIL', color: 'text-up' };
  if (r.includes('take_profit') || r.includes('tp')) return { text: 'TP', color: 'text-up' };
  if (r.includes('stop_loss') || r.includes('sl')) return { text: 'SL', color: 'text-down' };
  if (r.includes('liq')) return { text: 'LIQ', color: 'text-down' };
  if (r.includes('kill') || r.includes('manual')) return { text: 'MANUAL', color: 'text-warn' };
  if (r.includes('circuit')) return { text: 'CIRCUIT', color: 'text-down' };
  if (r.includes('exchange')) return { text: 'EXCH', color: 'text-ink-400' };
  return { text: reason.toUpperCase().slice(0, 8), color: 'text-ink-400' };
}

function timeOnly(dateStr: string | null): string {
  if (!dateStr) return '-';
  const utc = dateStr.endsWith('Z') ? dateStr : dateStr + 'Z';
  return new Date(utc).toLocaleTimeString('en-GB', { timeZone: 'Europe/Istanbul', hour: '2-digit', minute: '2-digit' });
}

function dateKey(dateStr: string | null): string {
  if (!dateStr) return 'unknown';
  const utc = dateStr.endsWith('Z') ? dateStr : dateStr + 'Z';
  return new Date(utc).toLocaleDateString('en-GB', { timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit' });
}

function formatDateLabel(dateStr: string | null): string {
  if (!dateStr) return '--';
  const utc = dateStr.endsWith('Z') ? dateStr : dateStr + 'Z';
  const d = new Date(utc);
  const today = new Date();
  const todayKey = today.toLocaleDateString('en-GB', { timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit' });
  const yesterday = new Date(today.getTime() - 86400000);
  const yesterdayKey = yesterday.toLocaleDateString('en-GB', { timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit' });
  const key = dateKey(dateStr);
  const label = d.toLocaleDateString('en-GB', { timeZone: 'Europe/Istanbul', weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' });
  if (key === todayKey) return `Today - ${label}`;
  if (key === yesterdayKey) return `Yesterday - ${label}`;
  return label;
}

function formatAge(openedAt: string): string {
  const iso = openedAt.includes('T') ? openedAt : openedAt.replace(' ', 'T');
  const utc = iso.endsWith('Z') ? iso : iso + 'Z';
  const ms = Date.now() - new Date(utc).getTime();
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

function riskProgress(p: { entry_price: number; mark_price: number | null; sl_price: number | null; tp_price: number | null; side: string }): { pct: number; color: string } {
  const mark = p.mark_price ?? p.entry_price;
  if (!p.sl_price || !p.tp_price) return { pct: 50, color: 'bg-ink-400' };
  const totalRange = Math.abs(p.tp_price - p.sl_price);
  if (totalRange === 0) return { pct: 50, color: 'bg-ink-400' };
  const fromSl = p.side === 'long' ? mark - p.sl_price : p.sl_price - mark;
  const raw = (fromSl / totalRange) * 100;
  const clamped = Math.max(0, Math.min(100, raw));
  const color = clamped < 25 ? 'bg-down' : clamped > 65 ? 'bg-up' : 'bg-warn';
  return { pct: clamped, color };
}

export default function Journal() {
  const navigate = useNavigate();
  const { activeAccountId, accounts, fetchAccounts } = useAccountStore();
  const { trades, loading, fetchTrades } = useTradingStore();
  const { positions, fetchPositions, updatePosition, removePosition } = usePositionStore();
  const isAll = activeAccountId === null;
  const activeAccount = accounts.find((a) => a.id === activeAccountId);
  const [filter, setFilter] = useState<FilterTab>('all');
  const [page, setPage] = useState(0);
  const [closing, setClosing] = useState<string | null>(null);
  const perPage = 25;

  useEffect(() => {
    fetchTrades(activeAccountId, 500, true);
    fetchPositions(activeAccountId);
  }, [activeAccountId, fetchTrades, fetchPositions]);

  useEffect(() => {
    const unsub1 = wsClient.on('position:opened', () => { fetchPositions(activeAccountId); fetchTrades(activeAccountId, 500, true); });
    const unsub2 = wsClient.on('position:closed', () => { fetchPositions(activeAccountId); fetchTrades(activeAccountId, 500, true); fetchAccounts(); });
    const unsub3 = wsClient.on('position:updated', (data) => {
      updatePosition(
        data.symbol,
        { size: data.size, mark_price: data.markPrice, unrealized_pnl: data.unrealizedPnl },
        data.side,
        data.accountId,
      );
    });
    const unsub4 = wsClient.on('order:filled', () => { fetchPositions(activeAccountId); fetchTrades(activeAccountId, 500, true); });
    return () => { unsub1(); unsub2(); unsub3(); unsub4(); };
  }, [activeAccountId, fetchTrades, fetchPositions, fetchAccounts, updatePosition]);

  useEffect(() => { setPage(0); }, [filter]);

  const closedTrades = trades.filter((t) => t.status === 'closed');
  const filtered = closedTrades.filter((t) => {
    if (filter === 'win') return (t.pnl || 0) > 0;
    if (filter === 'lose') return (t.pnl || 0) <= 0;
    return true;
  });

  const totalPages = Math.max(1, Math.ceil(filtered.length / perPage));
  const paged = filtered.slice(page * perPage, (page + 1) * perPage);

  const currentBalance = useMemo(() => {
    if (isAll) return accounts.reduce((s, a) => s + (a.account_equity ?? a.wallet_balance ?? a.balance ?? 0), 0);
    return activeAccount?.account_equity ?? activeAccount?.wallet_balance ?? activeAccount?.balance ?? 0;
  }, [isAll, accounts, activeAccount]);

  const dailyPnlMap = useMemo(() => {
    const map = new Map<string, number>();
    for (const t of closedTrades) {
      const dk = dateKey(t.opened_at);
      map.set(dk, (map.get(dk) || 0) + (t.pnl || 0));
    }
    return map;
  }, [closedTrades]);

  const dailyBalanceMap = useMemo(() => {
    const dates = Array.from(dailyPnlMap.keys()).sort((a, b) => {
      const [da, ma, ya] = a.split('/').map(Number);
      const [db, mb, yb] = b.split('/').map(Number);
      return (ya * 10000 + ma * 100 + da) - (yb * 10000 + mb * 100 + db);
    });
    const map = new Map<string, number>();
    let pnlAfter = closedTrades.reduce((s, t) => s + (t.pnl || 0), 0);
    for (const dk of dates) {
      const dayPnl = dailyPnlMap.get(dk) || 0;
      map.set(dk, currentBalance - pnlAfter + dayPnl);
      pnlAfter -= dayPnl;
    }
    return map;
  }, [dailyPnlMap, currentBalance, closedTrades]);

  const grouped = useMemo(() => {
    const groups: { date: string; label: string; trades: typeof paged; pnl: number; unrealized: number; wins: number; losses: number; fees: number; balance: number }[] = [];
    let currentKey = '';
    for (const t of paged) {
      const dk = dateKey(t.opened_at);
      if (dk !== currentKey) {
        currentKey = dk;
        groups.push({ date: dk, label: formatDateLabel(t.opened_at), trades: [], pnl: 0, unrealized: 0, wins: 0, losses: 0, fees: 0, balance: dailyBalanceMap.get(dk) || 0 });
      }
      const g = groups[groups.length - 1];
      g.trades.push(t);
      g.pnl += t.pnl || 0;
      g.fees += t.fee || 0;
      if ((t.pnl || 0) > 0) g.wins++;
      else g.losses++;
    }
    for (const g of groups) {
      for (const p of positions) {
        if (dateKey(p.opened_at) === g.date) {
          g.unrealized += p.unrealized_pnl || 0;
        }
      }
    }
    return groups;
  }, [paged, positions, dailyBalanceMap]);

  const totalPnl = closedTrades.reduce((s, t) => s + (t.pnl || 0), 0);
  const wins = closedTrades.filter((t) => (t.pnl || 0) > 0).length;
  const losses = closedTrades.filter((t) => (t.pnl || 0) <= 0).length;
  const totalFees = closedTrades.reduce((s, t) => s + (t.fee || 0), 0);

  const wrBreak = useMemo(() => winRateBreakdown(closedTrades), [closedTrades]);

  const totalUnrealizedPnl = positions.reduce((s, p) => s + (p.unrealized_pnl || 0), 0);
  const longCount = positions.filter((p) => p.side === 'long').length;
  const shortCount = positions.filter((p) => p.side === 'short').length;

  const handleClose = async (symbol: string, side: string, accountId: number) => {
    setClosing(symbol);
    try {
      await api.post('/trading/close', { accountId, symbol, side, reason: 'manual' });
      removePosition(symbol, side, accountId);
      fetchAccounts();
    } catch {}
    setClosing(null);
  };

  const tabs: { key: FilterTab; label: string; count: number }[] = [
    { key: 'all', label: 'ALL', count: closedTrades.length },
    { key: 'win', label: 'WIN', count: wins },
    { key: 'lose', label: 'LOSE', count: losses },
  ];

  const colCount = isAll ? 18 : 17;

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-auto">
      {/* --- KPI STRIP --- */}
      <div className="grid grid-cols-6">
        <SumCard label="EQUITY" value={formatUsd(currentBalance)} color="text-ink-50" />
        <SumCard label="OPEN" value={`${positions.length}`} sub={`${longCount}L / ${shortCount}S`} />
        <SumCard label="UNREALIZED" value={formatUsd(totalUnrealizedPnl)} color={totalUnrealizedPnl >= 0 ? 'text-up' : 'text-down'} />
        <SumCard label="REALIZED" value={formatUsd(totalPnl)} color={totalPnl >= 0 ? 'text-up' : 'text-down'} />
        <SumCard
          label="WIN RATE"
          value={closedTrades.length > 0 ? `${((wins / closedTrades.length) * 100).toFixed(1)}%` : '--'}
          sub={
            <div className="text-[9px] mt-0.5 flex gap-2 leading-tight font-mono">
              <span className="text-info">S {wrBreak.scalp.winRate.toFixed(0)}%<span className="text-ink-500">/{wrBreak.scalp.total}</span></span>
              <span className="text-purple-400">W {wrBreak.swing.winRate.toFixed(0)}%<span className="text-ink-500">/{wrBreak.swing.total}</span></span>
              <span className="text-amber-400">M {wrBreak.manual.winRate.toFixed(0)}%<span className="text-ink-500">/{wrBreak.manual.total}</span></span>
            </div>
          }
        />
        <SumCard label="FEES" value={formatUsd(totalFees)} last />
      </div>

      {/* --- OPEN POSITIONS --- */}
      <div className="border-t border-white/5">
        <div className="flex items-center justify-between px-4 h-8 bg-ink-850 border-b border-white/5">
          <div className="flex items-center gap-3">
            <span className="text-[9px] tracking-[0.3em] text-ink-400">[ OPEN POSITIONS ]</span>
            <span className="text-[10px] text-ink-300 num">
              {positions.length} active
              {positions.length > 0 && (
                <>
                  <span className="text-ink-500 mx-1">&middot;</span>
                  <span className="text-up">{longCount}L</span>
                  <span className="text-ink-500 mx-0.5">/</span>
                  <span className="text-down">{shortCount}S</span>
                </>
              )}
            </span>
          </div>
          {positions.length > 0 && (
            <span className={`text-[10px] font-medium num ${totalUnrealizedPnl >= 0 ? 'text-up' : 'text-down'}`}>
              {totalUnrealizedPnl >= 0 ? '+' : ''}{formatUsd(totalUnrealizedPnl)}
            </span>
          )}
        </div>

        {positions.length === 0 ? (
          <div className="px-4 py-4 text-ink-500 text-[11px] text-center border-b border-white/5">No open positions</div>
        ) : (
          <div className="border-b border-white/5">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-ink-400 text-[9px] tracking-widest text-left bg-ink-850">
                  {isAll && <th className="px-3 py-1.5 font-medium">ACCOUNT</th>}
                  <th className="px-3 py-1.5 font-medium">SYMBOL</th>
                  <th className="px-3 py-1.5 font-medium">SIDE</th>
                  <th className="px-3 py-1.5 font-medium text-right">LEV</th>
                  <th className="px-3 py-1.5 font-medium text-right">ENTRY</th>
                  <th className="px-3 py-1.5 font-medium text-right">MARK</th>
                  <th className="px-3 py-1.5 font-medium text-right">PNL $</th>
                  <th className="px-3 py-1.5 font-medium text-right">PNL %</th>
                  <th className="px-3 py-1.5 font-medium w-[90px]">RISK</th>
                  <th className="px-3 py-1.5 font-medium text-right">TP</th>
                  <th className="px-3 py-1.5 font-medium text-right">SL</th>
                  <th className="px-3 py-1.5 font-medium text-right">AGE</th>
                  <th className="px-3 py-1.5 font-medium w-8"></th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => {
                  const pnl = p.unrealized_pnl || 0;
                  const pct = positionPnlPercent(p);
                  const risk = riskProgress(p);
                  return (
                    <tr key={p.id} className={`border-b border-white/5 hover:bg-white/[0.02] transition-colors ${pnl < 0 ? 'bg-down/[0.03]' : ''}`}>
                      {isAll && (() => {
                        const acc = accounts.find((a) => a.id === p.account_id);
                        return (
                          <td className="px-3 py-1.5 text-[10px] text-ink-300">
                            <span className="inline-flex items-center gap-1.5">
                              <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: acc?.color || '#888' }} />
                              {acc?.name || `#${p.account_id}`}
                            </span>
                          </td>
                        );
                      })()}
                      <td className="px-3 py-1.5 text-ink-50 font-semibold">{p.symbol.replace('USDT', '')}</td>
                      <td className="px-3 py-1.5">
                        <span className={`inline-flex items-center gap-0.5 font-medium ${p.side === 'long' ? 'text-up' : 'text-down'}`}>
                          {p.side === 'long' ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
                          {p.side.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-right text-ink-300 num">{p.leverage}x</td>
                      <td className="px-3 py-1.5 text-right text-ink-200 num">{formatPrice(p.entry_price)}</td>
                      <td className="px-3 py-1.5 text-right text-ink-200 num">{p.mark_price ? formatPrice(p.mark_price) : '--'}</td>
                      <td className={`px-3 py-1.5 text-right font-medium num ${pnl >= 0 ? 'text-up' : 'text-down'}`}>
                        {pnl >= 0 ? '+' : ''}{formatUsd(pnl)}
                      </td>
                      <td className={`px-3 py-1.5 text-right num ${pct >= 0 ? 'text-up' : 'text-down'}`}>
                        {formatPercent(pct)}
                      </td>
                      <td className="px-3 py-1.5">
                        <div className="w-[70px]">
                          <div className="h-[3px] w-full bg-ink-700 rounded-sm overflow-hidden">
                            <div className={`h-full ${risk.color} rounded-sm transition-all`} style={{ width: `${risk.pct}%` }} />
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-1.5 text-right text-[10px] text-up num">{p.tp_price ? formatPrice(p.tp_price) : '--'}</td>
                      <td className="px-3 py-1.5 text-right text-[10px] text-down num">
                        {p.sl_price ? formatPrice(p.sl_price) : '--'}
                        {(() => {
                          const dist = slDistancePct(p);
                          if (dist === null) return null;
                          const sign = dist > 0 ? '-' : '+';
                          return (
                            <div className={`text-[9px] ${slDistanceTone(dist)} mt-0.5`}>
                              {sign}{Math.abs(dist).toFixed(2)}%
                            </div>
                          );
                        })()}
                      </td>
                      <td className="px-3 py-1.5 text-right text-ink-400 num">{formatAge(p.opened_at)}</td>
                      <td className="px-3 py-1.5 text-center">
                        <button onClick={() => handleClose(p.symbol, p.side, p.account_id)}
                          disabled={closing === p.symbol}
                          className="text-ink-500 hover:text-down disabled:opacity-30 transition-colors p-0.5"
                          title="Close position">
                          <X size={12} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* --- TRADE HISTORY --- */}
      <div className="flex items-center gap-1 px-4 h-8 border-b border-white/5 bg-ink-850">
        <span className="text-[9px] tracking-[0.3em] text-ink-400 mr-3">[ TRADE HISTORY ]</span>
        {tabs.map((tab) => (
          <button key={tab.key} onClick={() => setFilter(tab.key)}
            className={`px-2.5 py-1 text-[10px] tracking-wider transition-colors ${
              filter === tab.key
                ? 'text-ink-50 bg-white/[0.06] border border-white/10'
                : 'text-ink-400 hover:text-ink-200 border border-transparent'
            }`}>
            {tab.label} <span className="text-ink-500 num ml-0.5">{tab.count}</span>
          </button>
        ))}
        <div className="ml-auto flex items-center gap-1.5 text-[10px] text-ink-400">
          <button onClick={() => setPage(Math.max(0, page - 1))} disabled={page === 0}
            className="p-0.5 hover:text-ink-200 disabled:opacity-30"><ChevronLeft size={14} /></button>
          <span className="num">{page + 1}/{totalPages}</span>
          <button onClick={() => setPage(Math.min(totalPages - 1, page + 1))} disabled={page >= totalPages - 1}
            className="p-0.5 hover:text-ink-200 disabled:opacity-30"><ChevronRight size={14} /></button>
        </div>
      </div>

      {loading ? (
        <p className="text-ink-500 text-[11px] px-4 py-6 text-center">Loading...</p>
      ) : paged.length === 0 ? (
        <p className="text-ink-500 text-[11px] px-4 py-6 text-center">No trades</p>
      ) : (
        <div className="flex-1 overflow-auto">
          <table className="w-full text-[11px]">
            <thead className="sticky top-0 bg-ink-850 z-10">
              <tr className="text-ink-400 text-[9px] tracking-widest text-left">
                {isAll && <th className="px-3 py-2 font-medium">ACCOUNT</th>}
                <th className="px-3 py-2 font-medium">SYMBOL</th>
                <th className="px-3 py-2 font-medium">SIDE</th>
                <th className="px-3 py-2 font-medium">TYPE</th>
                <th className="px-3 py-2 font-medium">BOT</th>
                <th className="px-3 py-2 font-medium">SIGNAL</th>
                <th className="px-3 py-2 font-medium text-right">SCORE</th>
                <th className="px-3 py-2 font-medium text-right">LEV</th>
                <th className="px-3 py-2 font-medium text-right">NOTIONAL</th>
                <th className="px-3 py-2 font-medium text-right">ENTRY</th>
                <th className="px-3 py-2 font-medium text-right">EXIT</th>
                <th className="px-3 py-2 font-medium text-right">Bybit FR</th>
                <th className="px-3 py-2 font-medium text-right">PNL $</th>
                <th className="px-3 py-2 font-medium text-right">PNL %</th>
                <th className="px-3 py-2 font-medium">OPENED</th>
                <th className="px-3 py-2 font-medium">CLOSED</th>
                <th className="px-3 py-2 font-medium">DURATION</th>
                <th className="px-3 py-2 font-medium">CLOSE</th>
              </tr>
            </thead>
            <tbody>
              {grouped.map((g) => (
                <>
                  <tr key={`date-${g.date}`} className="bg-ink-800/60">
                    <td colSpan={colCount} className="px-3 py-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] text-ink-200 font-medium tracking-wide">{g.label}</span>
                        <div className="flex items-center gap-3 text-[9px] num">
                          <span className="text-ink-400">{g.trades.length} trades</span>
                          <span className="text-ink-400">
                            <span className="text-up">{g.wins}W</span>
                            <span className="text-ink-500 mx-0.5">/</span>
                            <span className="text-down">{g.losses}L</span>
                          </span>
                          <span className="text-ink-500">R:</span>
                          <span className={`font-medium ${g.pnl >= 0 ? 'text-up' : 'text-down'}`}>
                            {g.pnl >= 0 ? '+' : ''}{formatUsd(g.pnl)}
                          </span>
                          {g.unrealized !== 0 && (
                            <>
                              <span className="text-ink-500">U:</span>
                              <span className={`font-medium ${g.unrealized >= 0 ? 'text-up' : 'text-down'}`}>
                                {g.unrealized >= 0 ? '+' : ''}{formatUsd(g.unrealized)}
                              </span>
                            </>
                          )}
                          <span className="text-ink-500">T:</span>
                          <span className={`font-semibold ${(g.pnl + g.unrealized) >= 0 ? 'text-up' : 'text-down'}`}>
                            {(g.pnl + g.unrealized) >= 0 ? '+' : ''}{formatUsd(g.pnl + g.unrealized)}
                          </span>
                          <span className="text-ink-500">Fee: {formatUsd(g.fees)}</span>
                          <span className="text-ink-600">|</span>
                          <span className="text-ink-200 font-semibold">{formatUsd(g.balance)}</span>
                        </div>
                      </div>
                    </td>
                  </tr>
                  {g.trades.map((t) => {
                    const pnl = t.pnl || 0;
                    const pnlColor = pnl > 0 ? 'text-up' : pnl < 0 ? 'text-down' : 'text-ink-400';
                    const isManual = t.entry_reason === 'manual' || t.entry_reason === 'manual_suggested' || t.entry_reason === 'manual_order';
                    const signal = formatSignal(t);
                    const closeInfo = formatCloseReason(t.exit_reason);
                    return (
                      <tr key={t.id}
                        onClick={() => navigate(`/trade/${t.id}`)}
                        className="border-b border-white/5 hover:bg-white/[0.02] cursor-pointer transition-colors">
                        {isAll && (() => {
                          const acc = accounts.find((a) => a.id === t.account_id);
                          return (
                            <td className="px-3 py-2 text-[10px] text-ink-300">
                              <span className="inline-flex items-center gap-1.5">
                                <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: acc?.color || '#888' }} />
                                {acc?.name || `#${t.account_id}`}
                              </span>
                            </td>
                          );
                        })()}
                        <td className="px-3 py-2 text-ink-100 font-medium">{t.symbol.replace('USDT', '')}</td>
                        <td className="px-3 py-2">
                          <span className={`inline-flex items-center gap-0.5 font-medium ${t.side === 'long' ? 'text-up' : 'text-down'}`}>
                            {t.side === 'long' ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
                            {t.side.toUpperCase()}
                          </span>
                        </td>
                        <td className="px-3 py-2">
                          <span className={`px-1.5 py-0.5 text-[9px] font-medium border ${
                            isManual
                              ? 'bg-warn/10 text-warn border-warn/30'
                              : 'bg-info/10 text-info border-info/30'
                          }`}>{isManual ? 'MANUAL' : 'AUTO'}</span>
                        </td>
                        <td className="px-3 py-2">
                          {(() => {
                            const cat = categorizeTrade(t);
                            const cls = cat === 'scalp'
                              ? 'bg-info/10 text-info border-info/30'
                              : cat === 'swing'
                                ? 'bg-purple-400/10 text-purple-400 border-purple-400/30'
                                : 'bg-amber-400/10 text-amber-400 border-amber-400/30';
                            return <span className={`px-1.5 py-0.5 text-[9px] font-medium border ${cls}`}>{CATEGORY_LABELS[cat]}</span>;
                          })()}
                        </td>
                        <td className="px-3 py-2 text-ink-300 text-[10px] max-w-[200px] truncate" title={signal}>
                          {signal}
                        </td>
                        <td className="px-3 py-2 text-right num">
                          <span className={`font-medium ${(t.signal_score || 0) > 0 ? 'text-up' : (t.signal_score || 0) < 0 ? 'text-down' : 'text-ink-500'}`}>
                            {t.signal_score?.toFixed(1) ?? '-'}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-right text-ink-300 num">{t.leverage}x</td>
                        <td className="px-3 py-2 text-right text-ink-200 num">{formatUsd(t.entry_price * t.size)}</td>
                        <td className="px-3 py-2 text-right text-ink-200 num">{formatPrice(t.entry_price)}</td>
                        <td className="px-3 py-2 text-right text-ink-200 num">{t.exit_price ? formatPrice(t.exit_price) : '-'}</td>
                        <td className="px-3 py-2 text-right text-ink-300 num">{t.entry_fr != null ? `${(t.entry_fr * 100).toFixed(3)}%` : '-'}</td>
                        <td className={`px-3 py-2 text-right font-medium num ${pnlColor}`}>
                          {pnl >= 0 ? '+' : ''}{formatUsd(pnl)}
                        </td>
                        <td className={`px-3 py-2 text-right num ${pnlColor}`}>
                          {formatPercent(t.pnl_percent)}
                        </td>
                        <td className="px-3 py-2 text-ink-300 num">{timeOnly(t.opened_at)}</td>
                        <td className="px-3 py-2 text-ink-300 num">{t.closed_at ? timeOnly(t.closed_at) : '-'}</td>
                        <td className="px-3 py-2 text-ink-400 num">{formatDuration(t.duration_seconds)}</td>
                        <td className="px-3 py-2">
                          <span className={`font-medium ${closeInfo.color}`}>{closeInfo.text}</span>
                        </td>
                      </tr>
                    );
                  })}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function SumCard({ label, value, sub, color, last }: { label: string; value: string; sub?: React.ReactNode; color?: string; last?: boolean }) {
  return (
    <div className={`px-4 py-3 bg-ink-900 ${last ? '' : 'border-r border-white/5'}`}>
      <p className="text-[9px] text-ink-400 tracking-[0.25em] mb-1">{label}</p>
      <p className={`text-[18px] font-semibold num ${color || 'text-ink-50'}`}>{value}</p>
      {sub && (typeof sub === 'string' ? <p className="text-[9px] text-ink-500 mt-0.5">{sub}</p> : sub)}
    </div>
  );
}
