import { useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import { formatUsd } from '../lib/formatters';

interface ReportRow {
  strategy: string;
  status: 'closed' | 'stopped';
  accountId: number;
  trades: number | null;
  wins: number;
  losses: number;
  pnl: number | null;
  fee: number | null;
  winRate: number | null;
  firstTrade: string | null;
  lastTrade: string | null;
  endedAt: string | null;
  btCalmar: number | null;
  btWinRate: number | null;
  btPnl: number | null;
  btTrades: number | null;
  oosCalmar: number | null;
  oosWinRate: number | null;
}

const COLS: { label: string; key: keyof ReportRow | null; align?: 'right' }[] = [
  { label: 'Strateji', key: 'strategy' },
  { label: 'Durum', key: 'status' },
  { label: 'Dönem', key: 'lastTrade' },
  { label: 'İşlem', key: 'trades', align: 'right' },
  { label: 'WR (gerçek)', key: 'winRate', align: 'right' },
  { label: 'PnL (gerçek)', key: 'pnl', align: 'right' },
  { label: 'Fee', key: 'fee', align: 'right' },
  { label: 'BT WR', key: 'btWinRate', align: 'right' },
  { label: 'BT Calmar', key: 'btCalmar', align: 'right' },
  { label: 'OOS Calmar', key: 'oosCalmar', align: 'right' },
];

function dt(iso: string | null): string {
  if (!iso) return '--';
  const d = new Date(iso.includes('T') ? iso : iso.replace(' ', 'T') + 'Z');
  return d.toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit' });
}

function cl(n: number) {
  return n >= 0 ? 'text-up' : 'text-down';
}

export default function StrategyReport() {
  const [rows, setRows] = useState<ReportRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [sortKey, setSortKey] = useState<keyof ReportRow>('lastTrade');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'closed' | 'stopped'>('all');

  useEffect(() => {
    api.get<ReportRow[]>('/strategy-report')
      .then((r) => { setRows(r); setError(''); })
      .catch((e) => setError(e?.message || 'Rapor alınamadı'))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    let list = [...rows];
    if (statusFilter !== 'all') list = list.filter((r) => r.status === statusFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter((r) => r.strategy.toLowerCase().includes(q));
    }
    list.sort((a, b) => {
      const va = a[sortKey];
      const vb = b[sortKey];
      let cmp = 0;
      if (va == null && vb == null) cmp = 0;
      else if (va == null) cmp = -1;
      else if (vb == null) cmp = 1;
      else if (typeof va === 'string' && typeof vb === 'string') cmp = va.localeCompare(vb);
      else cmp = (va as number) - (vb as number);
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return list;
  }, [rows, statusFilter, search, sortKey, sortDir]);

  const toggleSort = (key: keyof ReportRow) => {
    if (sortKey === key) setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    else { setSortKey(key); setSortDir('desc'); }
  };

  const totalPnl = filtered.reduce((s, r) => s + (r.pnl ?? 0), 0);
  const totalTrades = filtered.reduce((s, r) => s + (r.trades ?? 0), 0);

  return (
    <div className="flex-1 flex flex-col p-4 gap-3">
      <div className="flex items-center justify-between">
        <h1 className="text-sm font-medium text-ink-100">Strateji Raporu</h1>
        <span className="text-[10px] text-ink-500 num">
          {filtered.length} strateji · {totalTrades} işlem · toplam <span className={cl(totalPnl)}>{formatUsd(totalPnl)}</span>
        </span>
      </div>

      <p className="text-[10px] text-ink-500">
        Denenmiş ve kapanmış stratejiler: hesap yeniden kullanılırken arşivlenenler (KAPANDI) + durdurulup beklemede olanlar (DURDURULDU).
        BT/OOS kolonları aynı stratejinin backtest beklentisi — gerçekle kıyaslamak için.
      </p>

      <div className="flex items-center gap-2">
        <input
          type="text"
          placeholder="Strateji ara..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="bg-ink-800 border border-white/5 rounded px-2 py-1 text-[11px] text-ink-100 w-44 placeholder:text-ink-500 focus:border-white/15 focus:outline-none"
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
          className="bg-ink-800 border border-white/5 rounded px-2 py-1 text-[11px] text-ink-200 focus:outline-none cursor-pointer"
        >
          <option value="all">Tümü</option>
          <option value="closed">Kapandı</option>
          <option value="stopped">Durduruldu</option>
        </select>
      </div>

      <div className="flex-1 overflow-auto rounded border border-white/5">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b border-white/5 bg-ink-850 sticky top-0">
              {COLS.map((c) => (
                <th
                  key={c.label}
                  onClick={c.key ? () => toggleSort(c.key!) : undefined}
                  className={`px-2.5 py-2 font-medium text-ink-400 text-[9px] uppercase tracking-wider whitespace-nowrap ${c.align === 'right' ? 'text-right' : 'text-left'} ${c.key ? 'cursor-pointer hover:text-ink-200 select-none' : ''}`}
                >
                  {c.label}{c.key && sortKey === c.key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={COLS.length} className="text-center py-8 text-ink-500">Yükleniyor...</td></tr>
            ) : error ? (
              <tr><td colSpan={COLS.length} className="text-center py-8 text-down">{error}</td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={COLS.length} className="text-center py-8 text-ink-500">Kayıt yok — bir strateji durdurulduğunda veya hesabı yeniden kullanıldığında burada listelenir.</td></tr>
            ) : filtered.map((r, i) => (
              <tr key={`${r.strategy}-${r.accountId}-${r.status}-${i}`} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                <td className="px-2.5 py-1.5 text-ink-100 max-w-[240px]"><span className="truncate block" title={`hesap #${r.accountId}`}>{r.strategy}</span></td>
                <td className="px-2.5 py-1.5">
                  {r.status === 'stopped'
                    ? <span className="text-[8px] font-bold tracking-[0.12em] text-warn border border-warn/40 bg-warn/10 rounded px-1 py-px">DURDURULDU</span>
                    : <span className="text-[8px] font-bold tracking-[0.12em] text-ink-400 border border-white/20 bg-white/5 rounded px-1 py-px">KAPANDI</span>}
                </td>
                <td className="px-2.5 py-1.5 num text-ink-400 whitespace-nowrap" title={`ilk işlem ${r.firstTrade ?? '--'} · son işlem ${r.lastTrade ?? '--'}${r.endedAt ? ` · arşiv ${r.endedAt}` : ''}`}>
                  {dt(r.firstTrade)} → {dt(r.lastTrade)}
                </td>
                <td className="px-2.5 py-1.5 num text-right text-ink-100" title={r.trades != null ? `${r.wins}W / ${r.losses}L` : 'işlem geçmişi sonraki stratejiyle birleşti (arşivleme öncesi dönem)'}>
                  {r.trades != null ? r.trades : <span className="text-ink-700">--</span>}
                </td>
                <td className="px-2.5 py-1.5 num text-right">
                  {r.winRate != null ? <span className={r.winRate >= 50 ? 'text-up' : 'text-down'}>{r.winRate.toFixed(1)}%</span> : '--'}
                </td>
                <td className={`px-2.5 py-1.5 num text-right ${r.pnl != null ? cl(r.pnl) : 'text-ink-700'}`}>{r.pnl != null ? formatUsd(r.pnl) : '--'}</td>
                <td className="px-2.5 py-1.5 num text-right text-ink-500">{r.fee != null ? formatUsd(r.fee) : '--'}</td>
                <td className="px-2.5 py-1.5 num text-right text-ink-300">{r.btWinRate != null ? `${r.btWinRate.toFixed(0)}%` : '--'}</td>
                <td className="px-2.5 py-1.5 num text-right text-ink-300">{r.btCalmar != null ? r.btCalmar.toFixed(2) : '--'}</td>
                <td className="px-2.5 py-1.5 num text-right">
                  {r.oosCalmar != null
                    ? <span className={r.oosCalmar >= 1 ? 'text-up' : r.oosCalmar >= 0 ? 'text-warn' : 'text-down'}>{r.oosCalmar.toFixed(2)}</span>
                    : <span className="text-ink-700">--</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
