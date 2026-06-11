import { useEffect, useState, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAccountStore } from '../../store/account-store';
import { usePositionStore } from '../../store/position-store';
import { useCustomizationStore } from '../../store/customization-store';
import { wsClient } from '../../lib/ws';
import { debounce } from '../../lib/debounce';
import { closePosition } from '../../lib/trading-actions';
import { formatUsd, formatPercent, formatPrice } from '../../lib/formatters';
import { aggregatePositionPnlPercent, positionMargin, positionMarkValue, positionPnlPercent, slDistancePct, slDistanceTone } from '../../lib/position-math';
import { X, Columns3 } from 'lucide-react';

type FilterScope = 'all' | 'long' | 'short' | 'winners' | 'losers';

interface ColumnDef {
  key: string;
  label: string;
  align: 'left' | 'right';
  alwaysVisible?: boolean;
}

const ALL_COLUMNS: ColumnDef[] = [
  { key: 'symbol', label: 'Symbol', align: 'left', alwaysVisible: true },
  { key: 'side', label: 'Side', align: 'left' },
  { key: 'leverage', label: 'Leverage', align: 'right' },
  { key: 'margin', label: 'Margin', align: 'right' },
  { key: 'value', label: 'Value', align: 'right' },
  { key: 'entry', label: 'Entry', align: 'right' },
  { key: 'mark', label: 'Mark', align: 'right' },
  { key: 'liqPrice', label: 'Liq.Price', align: 'right' },
  { key: 'pnlUsd', label: 'PnL USD', align: 'right' },
  { key: 'pnlPct', label: 'PnL %', align: 'right' },
  { key: 'risk', label: 'Risk', align: 'left' },
  { key: 'slDist', label: 'SL Dist %', align: 'right' },
  { key: 'age', label: 'Age', align: 'right' },
];

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

function calcLiqPrice(entry: number, leverage: number, side: string): number {
  if (leverage <= 0) return 0;
  if (side === 'long') return entry - (entry / leverage);
  return entry + (entry / leverage);
}

function riskProgress(p: { entry_price: number; mark_price: number | null; sl_price: number | null; tp_price: number | null; side: string }): { pct: number; color: string; label: string } {
  const mark = p.mark_price ?? p.entry_price;
  if (!p.sl_price || !p.tp_price) return { pct: 50, color: 'bg-ink-400', label: 'no SL/TP' };
  const totalRange = Math.abs(p.tp_price - p.sl_price);
  if (totalRange === 0) return { pct: 50, color: 'bg-ink-400', label: '-' };
  const fromSl = p.side === 'long' ? mark - p.sl_price : p.sl_price - mark;
  const raw = (fromSl / totalRange) * 100;
  const clamped = Math.max(0, Math.min(100, raw));
  const color = clamped < 25 ? 'bg-down' : clamped > 65 ? 'bg-up' : 'bg-warn';
  const label = `${clamped.toFixed(0)}% to TP`;
  return { pct: clamped, color, label };
}

function shouldBlink(p: { mark_price: number | null; sl_price: number | null; entry_price: number; side: string }): boolean {
  const mark = p.mark_price ?? p.entry_price;
  if (!p.sl_price) return false;
  const dist = Math.abs(mark - p.sl_price);
  const range = Math.abs(p.entry_price - p.sl_price);
  if (range === 0) return false;
  return dist / range < 0.2;
}

const SCOPES: { key: FilterScope; label: string }[] = [
  { key: 'all', label: 'ALL' },
  { key: 'long', label: 'LONG' },
  { key: 'short', label: 'SHORT' },
  { key: 'winners', label: 'WIN' },
  { key: 'losers', label: 'LOSE' },
];

export default function PositionsTable() {
  const navigate = useNavigate();
  const { activeAccountId, accounts } = useAccountStore();
  const account = accounts.find((a) => a.id === activeAccountId);
  const isAll = activeAccountId === null;
  const { positions, fetchPositions, updatePosition, removePosition } = usePositionStore();
  const { preferences, updatePreference, fetchPreferences } = useCustomizationStore();
  const [closing, setClosing] = useState<string | null>(null);
  const [filterText, setFilterText] = useState('');
  const [activeFilter, setActiveFilter] = useState<FilterScope>('all');
  const [botFilter, setBotFilter] = useState<number | 'all'>('all');
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [showColPicker, setShowColPicker] = useState(false);
  const pickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => { fetchPreferences(); }, [fetchPreferences]);

  useEffect(() => {
    fetchPositions(activeAccountId);
    // Toplu olay patlamalarinda olay basina degil, patlama basina tek fetch.
    const refresh = debounce(() => fetchPositions(activeAccountId), 200);
    const unsub1 = wsClient.on('position:updated', (data) => {
      updatePosition(
        data.symbol,
        { size: data.size, mark_price: data.markPrice, unrealized_pnl: data.unrealizedPnl },
        data.side,
        data.accountId,
      );
    });
    const unsub2 = wsClient.on('position:closed', (data) => {
      if (data.partial) {
        refresh();
        return;
      }
      removePosition(data.symbol, data.side, data.accountId);
    });
    const unsub3 = wsClient.on('position:opened', refresh);
    const unsub4 = wsClient.on('order:filled', refresh);
    return () => { unsub1(); unsub2(); unsub3(); unsub4(); refresh.cancel(); };
  }, [activeAccountId, fetchPositions, updatePosition, removePosition]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setShowColPicker(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const visibleKeys = useMemo(() => {
    const raw = preferences.positionColumns;
    if (!raw) return ['symbol', 'side', 'leverage', 'value', 'entry', 'mark', 'pnlUsd', 'pnlPct', 'risk', 'slDist', 'age'];
    return raw.split(',').filter(Boolean);
  }, [preferences.positionColumns]);

  const visibleColumns = useMemo(() => {
    let cols = ALL_COLUMNS.filter((c) => c.key !== 'account' && visibleKeys.includes(c.key));
    return cols;
  }, [visibleKeys]);

  const toggleColumn = (key: string) => {
    const col = ALL_COLUMNS.find((c) => c.key === key);
    if (col?.alwaysVisible) return;
    let next: string[];
    if (visibleKeys.includes(key)) {
      next = visibleKeys.filter((k) => k !== key);
    } else {
      const order = ALL_COLUMNS.map((c) => c.key);
      next = [...visibleKeys, key].sort((a, b) => order.indexOf(a) - order.indexOf(b));
    }
    updatePreference('positionColumns', next.join(','));
  };

  const filtered = useMemo(() => {
    let list = positions;
    if (botFilter !== 'all') list = list.filter((p) => p.account_id === botFilter);
    if (filterText) {
      const q = filterText.toUpperCase();
      list = list.filter((p) => p.symbol.includes(q));
    }
    switch (activeFilter) {
      case 'long': list = list.filter((p) => p.side === 'long'); break;
      case 'short': list = list.filter((p) => p.side === 'short'); break;
      case 'winners': list = list.filter((p) => (p.unrealized_pnl || 0) > 0); break;
      case 'losers': list = list.filter((p) => (p.unrealized_pnl || 0) < 0); break;
    }
    return list;
  }, [positions, filterText, activeFilter, botFilter]);

  // Acik pozisyonlarda bulunan botlar (ALL modunda bota gore filtre icin).
  const botOptions = useMemo(() => {
    const ids = [...new Set(positions.map((p) => p.account_id))];
    return ids.map((id) => accounts.find((a) => a.id === id)).filter(Boolean) as typeof accounts;
  }, [positions, accounts]);

  const sortVal = (p: any, key: string): number | string => {
    switch (key) {
      case 'account': { const a = accounts.find((x) => x.id === p.account_id); return (a?.name || `#${p.account_id}`).toLowerCase(); }
      case 'symbol': return p.symbol;
      case 'side': return p.side;
      case 'leverage': return p.leverage;
      case 'margin': return positionMargin(p);
      case 'value': return positionMarkValue(p);
      case 'entry': return p.entry_price;
      case 'mark': return p.mark_price ?? 0;
      case 'liqPrice': return calcLiqPrice(p.entry_price, p.leverage, p.side);
      case 'pnlUsd': return p.unrealized_pnl ?? 0;
      case 'pnlPct': return positionPnlPercent(p);
      case 'risk': return riskProgress(p).pct;
      case 'slDist': return slDistancePct(p) ?? Number.NEGATIVE_INFINITY;
      case 'age': { const iso = p.opened_at.includes('T') ? p.opened_at : p.opened_at.replace(' ', 'T'); return new Date(iso.endsWith('Z') ? iso : iso + 'Z').getTime(); }
      default: return 0;
    }
  };

  const sorted = useMemo(() => {
    if (!sortKey) return filtered;
    const dir = sortDir === 'asc' ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const va = sortVal(a, sortKey); const vb = sortVal(b, sortKey);
      if (typeof va === 'string' || typeof vb === 'string') return String(va).localeCompare(String(vb)) * dir;
      return ((va as number) - (vb as number)) * dir;
    });
  }, [filtered, sortKey, sortDir, accounts]);

  const onSort = (key: string) => {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else { setSortKey(key); setSortDir('desc'); }
  };
  const arrow = (key: string) => (sortKey === key ? (sortDir === 'asc' ? ' ↑' : ' ↓') : '');

  const longCount = positions.filter((p) => p.side === 'long').length;
  const shortCount = positions.filter((p) => p.side === 'short').length;
  const totalPnl = filtered.reduce((s, p) => s + (p.unrealized_pnl || 0), 0);
  const totalPnlPct = aggregatePositionPnlPercent(filtered);

  const handleClose = async (symbol: string, side: string, accountId: number) => {
    setClosing(symbol);
    try {
      await closePosition({ accountId, symbol, side });
      removePosition(symbol, side, accountId);
    } catch {}
    setClosing(null);
  };

  const pnlColIdx = visibleColumns.findIndex((c) => c.key === 'pnlUsd');
  const pnlPctColIdx = visibleColumns.findIndex((c) => c.key === 'pnlPct');
  // Footer ilk hucresi: # + Account + pnl'den onceki kolonlar (ilk gorunur pnl kolonuna kadar)
  const firstPnlColIdx = pnlColIdx >= 0 ? pnlColIdx : pnlPctColIdx;
  const colSpanBeforePnl = firstPnlColIdx >= 0 ? firstPnlColIdx + 2 : visibleColumns.length + 2;

  return (
    <div className="border border-white/5 rounded-sm overflow-hidden">
      <div className="h-9 bg-ink-850 border-b border-white/5 flex items-center justify-between px-3">
        <div className="flex items-center gap-4">
          <span className="text-[9px] tracking-[0.3em] uppercase text-ink-400">[ OPEN POSITIONS ]</span>
          <span className="text-[11px] text-ink-200">
            {positions.length} active
            <span className="text-ink-500 mx-1">&middot;</span>
            <span className="text-up">{longCount}L</span>
            <span className="text-ink-500 mx-0.5">/</span>
            <span className="text-down">{shortCount}S</span>
          </span>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            placeholder="filter..."
            className="h-6 w-28 bg-ink-800 border border-white/5 rounded-sm px-2 text-[11px] text-ink-100 placeholder:text-ink-500 outline-none focus:border-white/10"
          />
          {botOptions.length > 1 && (
            <select
              value={String(botFilter)}
              onChange={(e) => setBotFilter(e.target.value === 'all' ? 'all' : Number(e.target.value))}
              title="Bota gore filtrele"
              className="h-6 max-w-[150px] bg-ink-800 border border-white/5 rounded-sm px-1 text-[10px] text-ink-100 outline-none focus:border-white/10"
            >
              <option value="all">Tum botlar</option>
              {botOptions.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          )}
          <div className="flex items-center gap-0.5">
            {SCOPES.map((s) => (
              <button
                key={s.key}
                onClick={() => setActiveFilter(s.key)}
                className={`px-2 py-0.5 rounded-sm text-[9px] tracking-[0.15em] uppercase transition-colors ${
                  activeFilter === s.key
                    ? 'bg-ink-700 text-ink-100'
                    : 'text-ink-500 hover:text-ink-300'
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
          <div className="relative" ref={pickerRef}>
            <button
              onClick={() => setShowColPicker(!showColPicker)}
              className={`p-1 rounded-sm transition-colors ${showColPicker ? 'bg-ink-700 text-ink-100' : 'text-ink-500 hover:text-ink-300'}`}
              title="Columns"
            >
              <Columns3 size={14} />
            </button>
            {showColPicker && (
              <div className="absolute right-0 top-full mt-1 z-50 bg-ink-800 border border-white/10 rounded-sm shadow-xl py-1 w-40 max-h-[200px] overflow-y-auto">
                {ALL_COLUMNS.map((col) => (
                  <label
                    key={col.key}
                    className={`flex items-center gap-2 px-3 py-1 text-[10px] cursor-pointer hover:bg-white/5 ${
                      col.alwaysVisible ? 'opacity-50 cursor-not-allowed' : ''
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={visibleKeys.includes(col.key)}
                      disabled={col.alwaysVisible}
                      onChange={() => toggleColumn(col.key)}
                      className="w-3 h-3 accent-info"
                    />
                    <span className="text-ink-200">{col.label}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-white/5">
              <th className="text-left px-2 py-1.5 text-[9px] tracking-[0.2em] uppercase text-ink-400 w-[44px]">#</th>
              <th
                onClick={() => onSort('account')}
                className={`text-left px-2 py-1.5 text-[9px] tracking-[0.2em] uppercase cursor-pointer select-none hover:text-ink-200 ${sortKey === 'account' ? 'text-ink-100' : 'text-ink-400'}`}
              >
                Account{arrow('account')}
              </th>
              {visibleColumns.map((col) => (
                <th
                  key={col.key}
                  onClick={() => onSort(col.key)}
                  className={`${col.align === 'right' ? 'text-right' : 'text-left'} px-2 py-1.5 text-[9px] tracking-[0.2em] uppercase cursor-pointer select-none hover:text-ink-200 ${sortKey === col.key ? 'text-ink-100' : 'text-ink-400'}`}
                >
                  {col.label}{arrow(col.key)}
                </th>
              ))}
              <th className="px-2 py-1.5 text-[9px] tracking-[0.2em] uppercase text-ink-400 w-[40px]"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={visibleColumns.length + 3} className="text-center text-ink-500 py-8 text-[11px]">
                  {positions.length === 0 ? 'No open positions' : 'No positions match filter'}
                </td>
              </tr>
            ) : (
              sorted.map((p, i) => {
                const pnlPct = positionPnlPercent(p);
                const pnl = p.unrealized_pnl || 0;
                const isLosing = pnl < 0;
                const risk = riskProgress(p);
                const blinking = shouldBlink(p);
                const sideColor = p.side === 'long' ? 'bg-up' : 'bg-down';
                const value = positionMarkValue(p);
                const liqPrice = calcLiqPrice(p.entry_price, p.leverage, p.side);

                return (
                  <tr
                    key={p.id}
                    className={`row border-b border-white/5 ${isLosing ? 'bg-down/[0.04]' : ''}`}
                  >
                    <td className="px-2 py-2 text-[11px] text-ink-400 num">{i + 1}</td>
                    {(() => {
                      const acc = accounts.find((a) => a.id === p.account_id);
                      return (
                        <td className="px-2 py-2 text-[10px] text-ink-300">
                          <span className="inline-flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: acc?.color || '#888' }} />
                            {acc?.name || `#${p.account_id}`}
                          </span>
                        </td>
                      );
                    })()}
                    {visibleColumns.map((col) => {
                      switch (col.key) {
                        case 'symbol':
                          return (
                            <td key={col.key} className="px-2 py-2">
                              <div className="flex items-center gap-2">
                                <span className={`inline-block w-[1px] h-[12px] ${sideColor} rounded-full`} />
                                <button
                                  onClick={() => navigate(`/charts?symbol=${p.symbol}`)}
                                  title={`${p.symbol} grafigini ac`}
                                  className="text-[11px] font-semibold text-ink-50 hover:text-info hover:underline transition-colors cursor-pointer">
                                  {p.symbol}
                                </button>
                                <span className="text-[9px] text-ink-500">{(isAll ? accounts.find((a) => a.id === p.account_id) : account)?.engine === 'bybit' ? 'BYBIT' : 'PAPER'}</span>
                              </div>
                            </td>
                          );
                        case 'side':
                          return (
                            <td key={col.key} className="px-2 py-2">
                              <span className={`text-[11px] font-medium ${p.side === 'long' ? 'text-up' : 'text-down'}`}>
                                {p.side.toUpperCase()}
                              </span>
                            </td>
                          );
                        case 'leverage':
                          return (
                            <td key={col.key} className="px-2 py-2 text-right text-[11px] text-ink-200 num">
                              {p.leverage}x
                            </td>
                          );
                        case 'margin':
                          return (
                            <td key={col.key} className="px-2 py-2 text-right text-[11px] text-ink-200 num">
                              {formatUsd(positionMargin(p))}
                            </td>
                          );
                        case 'value':
                          return (
                            <td key={col.key} className="px-2 py-2 text-right text-[11px] text-ink-200 num">
                              {formatUsd(value)}
                            </td>
                          );
                        case 'entry':
                          return (
                            <td key={col.key} className="px-2 py-2 text-right text-[11px] text-ink-200 num">
                              {formatPrice(p.entry_price)}
                            </td>
                          );
                        case 'mark':
                          return (
                            <td key={col.key} className={`px-2 py-2 text-right text-[11px] num ${blinking ? 'blink text-down' : 'text-ink-200'}`}>
                              {p.mark_price ? formatPrice(p.mark_price) : '-'}
                            </td>
                          );
                        case 'liqPrice':
                          return (
                            <td key={col.key} className="px-2 py-2 text-right text-[11px] text-down/70 num">
                              {liqPrice > 0 ? formatPrice(liqPrice) : '-'}
                            </td>
                          );
                        case 'pnlUsd':
                          return (
                            <td key={col.key} className={`px-2 py-2 text-right text-[11px] font-medium num ${pnl >= 0 ? 'text-up' : 'text-down'}`}>
                              {pnl >= 0 ? '+' : ''}{formatUsd(pnl)}
                            </td>
                          );
                        case 'pnlPct':
                          return (
                            <td key={col.key} className={`px-2 py-2 text-right text-[11px] num ${pnlPct >= 0 ? 'text-up' : 'text-down'}`}>
                              {formatPercent(pnlPct)}
                            </td>
                          );
                        case 'risk':
                          return (
                            <td key={col.key} className="px-2 py-2">
                              <div className="w-[96px]">
                                <div className="h-[4px] w-full bg-ink-700 rounded-sm overflow-hidden">
                                  <div
                                    className={`h-full ${risk.color} rounded-sm transition-all`}
                                    style={{ width: `${risk.pct}%` }}
                                  />
                                </div>
                                <div className="text-[9px] text-ink-500 mt-0.5">{risk.label}</div>
                              </div>
                            </td>
                          );
                        case 'slDist': {
                          const dist = slDistancePct(p);
                          if (dist === null) {
                            return (
                              <td key={col.key} className="px-2 py-2 text-right text-[11px] text-ink-500 num">--</td>
                            );
                          }
                          const sign = dist > 0 ? '-' : '+';
                          return (
                            <td key={col.key} className={`px-2 py-2 text-right text-[11px] num ${slDistanceTone(dist)}`}>
                              {sign}{Math.abs(dist).toFixed(2)}%
                            </td>
                          );
                        }
                        case 'age':
                          return (
                            <td key={col.key} className="px-2 py-2 text-right text-[11px] text-ink-400 num whitespace-nowrap">
                              {formatAge(p.opened_at)}
                            </td>
                          );
                        default:
                          return <td key={col.key} />;
                      }
                    })}
                    <td className="px-2 py-2 text-center">
                      <button
                        onClick={() => handleClose(p.symbol, p.side, p.account_id)}
                        disabled={closing === p.symbol}
                        className="text-ink-500 hover:text-down disabled:opacity-30 transition-colors p-0.5"
                        title="Close position"
                      >
                        <X size={13} />
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
          {filtered.length > 0 && (
            <tfoot>
              <tr className="bg-ink-850">
                <td colSpan={colSpanBeforePnl} className="px-2 py-2 text-[9px] tracking-[0.2em] uppercase text-ink-400">
                  TOTAL &middot; {filtered.length} OF {positions.length} SHOWN
                </td>
                {pnlColIdx >= 0 && (
                  <td className={`px-2 py-2 text-right text-[11px] font-medium num ${totalPnl >= 0 ? 'text-up' : 'text-down'}`}>
                    {totalPnl >= 0 ? '+' : ''}{formatUsd(totalPnl)}
                  </td>
                )}
                {pnlPctColIdx >= 0 && (
                  <td className={`px-2 py-2 text-right text-[11px] num ${totalPnlPct >= 0 ? 'text-up' : 'text-down'}`}>
                    {formatPercent(totalPnlPct)}
                  </td>
                )}
                {/* Kalan kolonlar + kapatma butonu kolonu: toplam hucre sayisi header ile birebir esit */}
                <td colSpan={visibleColumns.length - (pnlPctColIdx >= 0 ? pnlPctColIdx + 1 : pnlColIdx >= 0 ? pnlColIdx + 1 : visibleColumns.length) + 1} />
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}
