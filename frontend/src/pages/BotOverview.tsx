import { useEffect, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAccountStore } from '../store/account-store';
import { useUiStore, type BotStatus } from '../store/ui-store';
import { api } from '../lib/api';
import { formatUsd, formatPercent } from '../lib/formatters';
import { Columns3, X, Play, Square, ChevronUp, ChevronDown, Filter, Trash2, Loader2 } from 'lucide-react';

interface ColumnDef {
  key: string;
  label: string;
  align: 'left' | 'right';
  alwaysVisible?: boolean;
  sortable?: boolean;
}

const ALL_COLUMNS: ColumnDef[] = [
  { key: 'status', label: 'Status', align: 'left', alwaysVisible: true, sortable: true },
  { key: 'name', label: 'Name', align: 'left', alwaysVisible: true, sortable: true },
  { key: 'engine', label: 'Engine', align: 'left', sortable: true },
  { key: 'balance', label: 'Equity', align: 'right', sortable: true },
  { key: 'initial_balance', label: 'Initial Bal', align: 'right', sortable: true },
  { key: 'total_pnl', label: 'Total PnL', align: 'right', sortable: true },
  { key: 'pnl_pct', label: 'PnL %', align: 'right', sortable: true },
  { key: 'total_trades', label: 'Trades', align: 'right', sortable: true },
  { key: 'win_rate', label: 'Win Rate', align: 'right', sortable: true },
  { key: 'wr_scalp', label: 'WR Scalp', align: 'right', sortable: true },
  { key: 'wr_swing', label: 'WR Swing', align: 'right', sortable: true },
  { key: 'wr_manual', label: 'WR Manuel', align: 'right', sortable: true },
  { key: 'winning', label: 'Wins', align: 'right', sortable: true },
  { key: 'losing', label: 'Losses', align: 'right', sortable: true },
  { key: 'signal_source', label: 'Source', align: 'left', sortable: true },
  { key: 'leverage', label: 'Leverage', align: 'right', sortable: true },
  { key: 'max_positions', label: 'Max Pos', align: 'right', sortable: true },
  { key: 'tp_percent', label: 'TP Price %', align: 'right', sortable: true },
  { key: 'sl_percent', label: 'SL Price %', align: 'right', sortable: true },
  { key: 'position_size', label: 'Pos Size %', align: 'right', sortable: true },
  { key: 'scan_interval', label: 'Scan Int', align: 'right', sortable: true },
  { key: 'scans', label: 'Scans', align: 'right', sortable: true },
  { key: 'signals', label: 'Signals', align: 'right', sortable: true },
  { key: 'orders', label: 'Orders', align: 'right', sortable: true },
  { key: 'last_scan', label: 'Last Scan', align: 'right', sortable: false },
  { key: 'started_at', label: 'Started', align: 'right', sortable: false },
  { key: 'max_drawdown', label: 'Max DD %', align: 'right', sortable: true },
  { key: 'long_score', label: 'Long Min', align: 'right', sortable: true },
  { key: 'short_score', label: 'Short Min', align: 'right', sortable: true },
  { key: 'actions', label: '', align: 'right', alwaysVisible: true, sortable: false },
];

const STORAGE_KEY = 'botOverviewColumns';

type SortDir = 'asc' | 'desc';
type StatusFilter = 'all' | 'running' | 'stopped';
type EngineFilter = 'all' | 'paper' | 'bybit';

function loadSavedColumns(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch {}
  return ALL_COLUMNS.filter((c) => !['initial_balance', 'winning', 'losing', 'max_drawdown', 'long_score', 'short_score', 'scan_interval', 'started_at'].includes(c.key)).map((c) => c.key);
}

function formatTime(iso: string | null): string {
  if (!iso) return '--';
  const d = new Date(iso.includes('T') ? iso : iso.replace(' ', 'T') + 'Z');
  return d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function getSortValue(acc: any, key: string, status: BotStatus | undefined): number | string {
  const isRunning = status?.status === 'running';
  switch (key) {
    case 'status': return isRunning ? 1 : 0;
    case 'name': return acc.name.toLowerCase();
    case 'engine': return acc.engine;
    case 'balance': return acc.account_equity ?? acc.wallet_balance ?? acc.balance ?? 0;
    case 'initial_balance': return acc.initial_balance ?? 0;
    case 'total_pnl': return acc.total_pnl ?? 0;
    case 'pnl_pct': {
      const pnl = acc.total_pnl ?? 0;
      const init = acc.initial_balance || 1;
      return (pnl / init) * 100;
    }
    case 'total_trades': return acc.total_trades ?? 0;
    case 'win_rate': {
      const total = acc.total_trades ?? 0;
      const wins = acc.winning_trades ?? 0;
      return total === 0 ? -1 : (wins / total) * 100;
    }
    case 'wr_scalp': return (acc.n_scalp ?? 0) === 0 ? -1 : (acc.wr_scalp ?? 0);
    case 'wr_swing': return (acc.n_swing ?? 0) === 0 ? -1 : (acc.wr_swing ?? 0);
    case 'wr_manual': return (acc.n_manual ?? 0) === 0 ? -1 : (acc.wr_manual ?? 0);
    case 'winning': return acc.winning_trades ?? 0;
    case 'losing': return acc.losing_trades ?? 0;
    case 'signal_source': return acc.signal_source || 'scanner';
    case 'leverage': return acc.bot_leverage ?? acc.leverage ?? 0;
    case 'max_positions': return acc.max_positions ?? 0;
    case 'tp_percent': return acc.tp_percent ?? 0;
    case 'sl_percent': return acc.sl_percent ?? 0;
    case 'position_size': return acc.position_size_pct ?? 2;
    case 'scan_interval': return acc.scan_interval ?? 0;
    case 'scans': return status?.totalScans ?? 0;
    case 'signals': return status?.totalSignals ?? 0;
    case 'orders': return status?.totalOrders ?? 0;
    case 'max_drawdown': return acc.max_drawdown ?? 0;
    case 'long_score': return acc.long_min_score ?? 0;
    case 'short_score': return acc.short_min_score ?? 0;
    default: return 0;
  }
}

export default function BotOverview() {
  const navigate = useNavigate();
  const { accounts, fetchAccounts, setActiveAccount } = useAccountStore();
  const botStatuses = useUiStore((s) => s.botStatuses);
  const setBotStatus = useUiStore((s) => s.setBotStatus);
  const [visibleKeys, setVisibleKeys] = useState<string[]>(loadSavedColumns);
  const [showPicker, setShowPicker] = useState(false);
  const [toggling, setToggling] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [sortKey, setSortKey] = useState<string | null>('balance');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [engineFilter, setEngineFilter] = useState<EngineFilter>('all');
  const [sourceFilter, setSourceFilter] = useState<string>('all');
  const [searchText, setSearchText] = useState('');

  useEffect(() => {
    accounts.forEach((acc) => {
      api.get<BotStatus>(`/bot/status?accountId=${acc.id}`).then((s) => setBotStatus(acc.id, s)).catch(() => {});
    });
  }, [accounts, setBotStatus]);

  useEffect(() => {
    const interval = setInterval(() => {
      accounts.forEach((acc) => {
        api.get<BotStatus>(`/bot/status?accountId=${acc.id}`).then((s) => setBotStatus(acc.id, s)).catch(() => {});
      });
    }, 5000);
    return () => clearInterval(interval);
  }, [accounts, setBotStatus]);

  const columns = useMemo(() => ALL_COLUMNS.filter((c) => visibleKeys.includes(c.key)), [visibleKeys]);

  const sources = useMemo(() => {
    const set = new Set(accounts.map((a) => a.signal_source || 'scanner'));
    return Array.from(set).sort();
  }, [accounts]);

  const filteredAndSorted = useMemo(() => {
    let list = [...accounts];

    if (statusFilter !== 'all') {
      list = list.filter((acc) => {
        const isRunning = botStatuses[acc.id]?.status === 'running';
        return statusFilter === 'running' ? isRunning : !isRunning;
      });
    }

    if (engineFilter !== 'all') {
      list = list.filter((acc) => acc.engine === engineFilter);
    }

    if (sourceFilter !== 'all') {
      list = list.filter((acc) => (acc.signal_source || 'scanner') === sourceFilter);
    }

    if (searchText.trim()) {
      const q = searchText.trim().toLowerCase();
      list = list.filter((acc) => acc.name.toLowerCase().includes(q));
    }

    if (sortKey) {
      list.sort((a, b) => {
        const va = getSortValue(a, sortKey, botStatuses[a.id]);
        const vb = getSortValue(b, sortKey, botStatuses[b.id]);
        let cmp = 0;
        if (typeof va === 'string' && typeof vb === 'string') cmp = va.localeCompare(vb);
        else cmp = (va as number) - (vb as number);
        return sortDir === 'asc' ? cmp : -cmp;
      });
    }

    return list;
  }, [accounts, botStatuses, statusFilter, engineFilter, sourceFilter, searchText, sortKey, sortDir]);

  const handleSort = (key: string) => {
    const col = ALL_COLUMNS.find((c) => c.key === key);
    if (!col?.sortable) return;
    if (sortKey === key) {
      if (sortDir === 'asc') setSortDir('desc');
      else { setSortKey(null); setSortDir('asc'); }
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  const toggleCol = (key: string) => {
    const col = ALL_COLUMNS.find((c) => c.key === key);
    if (col?.alwaysVisible) return;
    const next = visibleKeys.includes(key) ? visibleKeys.filter((k) => k !== key) : [...visibleKeys, key];
    setVisibleKeys(next);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  };

  const deleteBot = async (acc: typeof accounts[0]) => {
    if (acc.is_default) {
      alert(`"${acc.name}" varsayılan hesap, silinemiyor.`);
      return;
    }
    if (acc.type === 'real' || acc.engine === 'bybit') {
      alert(`"${acc.name}" gerçek/Bybit hesap, dashboard'dan silinemez.`);
      return;
    }
    if (!confirm(`"${acc.name}" hesabını silmek istiyor musun? Bu hesabın tüm trade geçmişi, pozisyonları ve config'i kalıcı olarak silinecek.`)) return;
    setDeleting(acc.id);
    try {
      await api.delete(`/accounts/${acc.id}`);
      await fetchAccounts();
    } catch (err: any) {
      alert(`Silme başarısız: ${err?.message || err}`);
    }
    setDeleting(null);
  };

  const toggleBot = async (accountId: number, isRunning: boolean) => {
    setToggling(accountId);
    try {
      const endpoint = isRunning ? '/bot/stop' : '/bot/start';
      const result = await api.post<BotStatus>(endpoint, { accountId });
      setBotStatus(accountId, result);
      fetchAccounts();
    } catch {}
    setToggling(null);
  };

  const hasActiveFilters = statusFilter !== 'all' || engineFilter !== 'all' || sourceFilter !== 'all' || searchText.trim() !== '';

  const renderCell = (acc: typeof accounts[0], col: ColumnDef) => {
    const status = botStatuses[acc.id];
    const isRunning = status?.status === 'running';
    switch (col.key) {
      case 'status':
        return (
          <div className="flex items-center gap-1.5">
            <button
              onClick={(e) => { e.stopPropagation(); toggleBot(acc.id, isRunning); }}
              disabled={toggling === acc.id}
              className={`w-5 h-5 flex items-center justify-center rounded transition-colors disabled:opacity-50 ${isRunning ? 'bg-up/15 text-up hover:bg-up/25' : 'bg-down/15 text-down hover:bg-down/25'}`}
            >
              {isRunning ? <Square size={8} /> : <Play size={8} className="ml-0.5" />}
            </button>
            <span className={`w-1.5 h-1.5 rounded-full ${isRunning ? 'bg-up pulse-dot' : 'bg-down'}`} />
            <span className={`text-[10px] font-medium ${isRunning ? 'text-up' : 'text-down'}`}>
              {isRunning ? 'ON' : 'OFF'}
            </span>
          </div>
        );
      case 'name':
        return <span className="text-ink-100 font-medium">{acc.name}</span>;
      case 'engine':
        return <span className={`text-[9px] px-1.5 py-0.5 rounded ${acc.engine === 'bybit' ? 'bg-warn/15 text-warn' : 'bg-ink-700 text-ink-300'}`}>{acc.engine}</span>;
      case 'balance': {
        const bal = acc.account_equity ?? acc.wallet_balance ?? acc.balance ?? 0;
        return <span className={bal >= 10000 ? 'text-up' : 'text-down'}>{formatUsd(bal)}</span>;
      }
      case 'initial_balance':
        return formatUsd(acc.initial_balance);
      case 'total_pnl': {
        const pnl = acc.total_pnl ?? 0;
        return <span className={pnl >= 0 ? 'text-up' : 'text-down'}>{formatUsd(pnl)}</span>;
      }
      case 'pnl_pct': {
        const pnl = acc.total_pnl ?? 0;
        const init = acc.initial_balance || 1;
        const pct = (pnl / init) * 100;
        return <span className={pct >= 0 ? 'text-up' : 'text-down'}>{formatPercent(pct)}</span>;
      }
      case 'total_trades':
        return acc.total_trades ?? 0;
      case 'win_rate': {
        const total = acc.total_trades ?? 0;
        const wins = acc.winning_trades ?? 0;
        if (total === 0) return '--';
        const wr = (wins / total) * 100;
        return <span className={wr >= 50 ? 'text-up' : 'text-down'}>{wr.toFixed(1)}%</span>;
      }
      case 'wr_scalp': {
        const n = acc.n_scalp ?? 0;
        if (n === 0) return <span className="text-ink-500">--</span>;
        const wr = acc.wr_scalp ?? 0;
        return <span className={wr >= 50 ? 'text-up' : 'text-down'}>{wr.toFixed(1)}%<span className="text-ink-500 text-[9px] ml-1">({n})</span></span>;
      }
      case 'wr_swing': {
        const n = acc.n_swing ?? 0;
        if (n === 0) return <span className="text-ink-500">--</span>;
        const wr = acc.wr_swing ?? 0;
        return <span className={wr >= 50 ? 'text-up' : 'text-down'}>{wr.toFixed(1)}%<span className="text-ink-500 text-[9px] ml-1">({n})</span></span>;
      }
      case 'wr_manual': {
        const n = acc.n_manual ?? 0;
        if (n === 0) return <span className="text-ink-500">--</span>;
        const wr = acc.wr_manual ?? 0;
        return <span className={wr >= 50 ? 'text-up' : 'text-down'}>{wr.toFixed(1)}%<span className="text-ink-500 text-[9px] ml-1">({n})</span></span>;
      }
      case 'winning':
        return <span className="text-up">{acc.winning_trades ?? 0}</span>;
      case 'losing':
        return <span className="text-down">{acc.losing_trades ?? 0}</span>;
      case 'signal_source':
        return <span className="text-[9px] px-1.5 py-0.5 rounded bg-ink-700 text-ink-300">{acc.signal_source || 'scanner'}</span>;
      case 'leverage':
        return `${acc.bot_leverage ?? acc.leverage}x`;
      case 'max_positions':
        return acc.max_positions;
      case 'tp_percent':
        return `${acc.tp_percent}%`;
      case 'sl_percent':
        return `${acc.sl_percent}%`;
      case 'position_size':
        return `${acc.position_size_pct ?? 2}%`;
      case 'scan_interval':
        return `${acc.scan_interval}s`;
      case 'scans':
        return status?.totalScans ?? '--';
      case 'signals':
        return status?.totalSignals ?? '--';
      case 'orders':
        return status?.totalOrders ?? '--';
      case 'last_scan':
        return formatTime(status?.lastScan ?? null);
      case 'started_at':
        return formatTime(status?.startedAt ?? null);
      case 'max_drawdown':
        return acc.max_drawdown_enabled ? `${acc.max_drawdown}%` : 'OFF';
      case 'long_score':
        return acc.long_min_score;
      case 'short_score':
        return acc.short_min_score;
      case 'actions':
        return (
          <button
            onClick={(e) => { e.stopPropagation(); deleteBot(acc); }}
            disabled={deleting === acc.id || !!acc.is_default || acc.type === 'real' || acc.engine === 'bybit'}
            title={acc.is_default ? 'Varsayılan hesap silinemiyor' : (acc.type === 'real' || acc.engine === 'bybit') ? 'Gerçek/Bybit hesap dashboarddan silinemez' : 'Hesabı sil'}
            className="inline-flex items-center justify-center w-6 h-6 rounded text-ink-500 hover:text-down hover:bg-down/10 disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-ink-500 transition-colors"
          >
            {deleting === acc.id ? <Loader2 size={11} className="animate-spin" /> : <Trash2 size={11} />}
          </button>
        );
      default:
        return '--';
    }
  };

  return (
    <div className="flex-1 flex flex-col p-4 gap-3">
      <div className="flex items-center justify-between">
        <h1 className="text-sm font-medium text-ink-100">Bot Overview</h1>
        <div className="relative">
          <button onClick={() => setShowPicker(!showPicker)} className="p-1.5 rounded hover:bg-white/5 text-ink-400 hover:text-ink-200 transition-colors" title="Columns">
            <Columns3 size={16} />
          </button>
          {showPicker && (
            <div className="absolute right-0 top-8 z-50 bg-ink-800 border border-white/10 rounded shadow-xl p-3 w-56 max-h-80 overflow-y-auto">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-medium text-ink-300 uppercase tracking-wider">Columns</span>
                <button onClick={() => setShowPicker(false)} className="text-ink-400 hover:text-ink-200"><X size={12} /></button>
              </div>
              {ALL_COLUMNS.map((col) => (
                <label key={col.key} className={`flex items-center gap-2 py-0.5 text-[11px] ${col.alwaysVisible ? 'text-ink-500' : 'text-ink-200 cursor-pointer hover:text-ink-100'}`}>
                  <input
                    type="checkbox"
                    checked={visibleKeys.includes(col.key)}
                    disabled={col.alwaysVisible}
                    onChange={() => toggleCol(col.key)}
                    className="accent-up w-3 h-3"
                  />
                  {col.label}
                </label>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <Filter size={13} className={`text-ink-500 flex-shrink-0 ${hasActiveFilters ? 'text-up' : ''}`} />

        <input
          type="text"
          placeholder="Search..."
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          className="bg-ink-800 border border-white/5 rounded px-2 py-1 text-[11px] text-ink-100 w-32 placeholder:text-ink-500 focus:border-white/15 focus:outline-none"
        />

        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
          className="bg-ink-800 border border-white/5 rounded px-2 py-1 text-[11px] text-ink-200 focus:outline-none cursor-pointer"
        >
          <option value="all">All Status</option>
          <option value="running">Running</option>
          <option value="stopped">Stopped</option>
        </select>

        <select
          value={engineFilter}
          onChange={(e) => setEngineFilter(e.target.value as EngineFilter)}
          className="bg-ink-800 border border-white/5 rounded px-2 py-1 text-[11px] text-ink-200 focus:outline-none cursor-pointer"
        >
          <option value="all">All Engine</option>
          <option value="paper">Paper</option>
          <option value="bybit">Bybit</option>
        </select>

        <select
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value)}
          className="bg-ink-800 border border-white/5 rounded px-2 py-1 text-[11px] text-ink-200 focus:outline-none cursor-pointer"
        >
          <option value="all">All Source</option>
          {sources.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>

        {hasActiveFilters && (
          <button
            onClick={() => { setStatusFilter('all'); setEngineFilter('all'); setSourceFilter('all'); setSearchText(''); }}
            className="text-[10px] text-ink-400 hover:text-ink-200 px-1.5 py-0.5 rounded hover:bg-white/5"
          >
            Clear
          </button>
        )}

        <span className="text-[10px] text-ink-500 ml-auto">{filteredAndSorted.length}/{accounts.length}</span>
      </div>

      <div className="flex-1 overflow-auto rounded border border-white/5">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b border-white/5 bg-ink-850 sticky top-0">
              {columns.map((col) => (
                <th
                  key={col.key}
                  onClick={() => col.sortable && handleSort(col.key)}
                  className={`px-2.5 py-2 font-medium text-ink-400 text-[9px] uppercase tracking-wider whitespace-nowrap text-${col.align} ${col.sortable ? 'cursor-pointer hover:text-ink-200 select-none' : ''}`}
                >
                  <span className="inline-flex items-center gap-0.5">
                    {col.label}
                    {col.sortable && sortKey === col.key && (
                      sortDir === 'asc' ? <ChevronUp size={10} className="text-up" /> : <ChevronDown size={10} className="text-up" />
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filteredAndSorted.map((acc) => {
              const isRunning = botStatuses[acc.id]?.status === 'running';
              return (
                <tr
                  key={acc.id}
                  onClick={() => { setActiveAccount(acc.id); navigate('/bot'); }}
                  className={`border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors cursor-pointer ${isRunning ? 'bg-up/[0.02]' : ''}`}
                >
                  {columns.map((col) => (
                    <td key={col.key} className={`px-2.5 py-1.5 whitespace-nowrap text-${col.align} num`}>
                      {renderCell(acc, col)}
                    </td>
                  ))}
                </tr>
              );
            })}
            {filteredAndSorted.length === 0 && (
              <tr><td colSpan={columns.length} className="text-center py-8 text-ink-500">{accounts.length === 0 ? 'No accounts' : 'No match'}</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
