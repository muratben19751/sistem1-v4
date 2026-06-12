import { useEffect, useState, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAccountStore } from '../store/account-store';
import { useUiStore } from '../store/ui-store';
import { useTradingStore } from '../store/trading-store';
import { api } from '../lib/api';
import { applyStaticAuthHeader } from '../lib/auth-token';
import { wsClient } from '../lib/ws';
import { Play, Square, RefreshCw, ArrowUpRight, ArrowDownRight, X, Download } from 'lucide-react';
import EquityCurve from '../components/charts/EquityCurve';
import PnLBarChart from '../components/charts/PnLBarChart';
import HeatMap from '../components/charts/HeatMap';
import PnLCalendar from '../components/charts/PnLCalendar';
import WinRateDonut from '../components/charts/WinRateDonut';
import { formatUsd, formatPrice, formatPercent, formatDuration, parseServerDateMs } from '../lib/formatters';

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const HOUR_LABELS = ['00-03', '04-07', '08-11', '12-15', '16-19', '20-23'];

// Backend UTC zaman damgasi -> Europe/Istanbul (UTC+3, sabit) gun/saat kovasi (Journal ile ayni yaklasim)
function istDayHour(raw: string): { day: number; hb: number } {
  const d = new Date(parseServerDateMs(raw) + 3 * 3_600_000);
  return { day: (d.getUTCDay() + 6) % 7, hb: Math.floor(d.getUTCHours() / 4) };
}

export default function Bot() {
  const navigate = useNavigate();
  const { activeAccountId, accounts } = useAccountStore();
  const { setBotStatus, setBotLogs, botStatuses, botLogs: allLogs } = useUiStore();
  const { trades, fetchTrades } = useTradingStore();
  const [loading, setLoading] = useState(false);
  const [equityData, setEquityData] = useState<any[]>([]);
  const [logsCount, setLogsCount] = useState<{ total: number; oldest: string | null; newest: string | null } | null>(null);
  const [logsLimit, setLogsLimit] = useState(100);
  const [exporting, setExporting] = useState(false);
  const [selectedCell, setSelectedCell] = useState<{ row: number; col: number } | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [selectedDateTrades, setSelectedDateTrades] = useState<any[]>([]);
  const account = accounts.find((a) => a.id === activeAccountId);

  const aid = activeAccountId || 0;
  const botStatus = botStatuses[aid];
  const botLogs = allLogs[aid];

  const fetchStatus = useCallback(async () => {
    if (!activeAccountId) return;
    try {
      const status = await api.get<any>(`/bot/status?accountId=${activeAccountId}`);
      setBotStatus(activeAccountId, status);
    } catch {}
  }, [activeAccountId, setBotStatus]);

  const fetchLogs = useCallback(async () => {
    if (!activeAccountId) return;
    try {
      const logs = await api.get<any[]>(`/bot/logs?accountId=${activeAccountId}&limit=${logsLimit}`);
      setBotLogs(activeAccountId, logs);
      const cnt = await api.get<{ total: number; oldest: string | null; newest: string | null }>(`/bot/logs/count?accountId=${activeAccountId}`);
      setLogsCount(cnt);
    } catch {}
  }, [activeAccountId, setBotLogs, logsLimit]);

  const exportLogsCsv = async () => {
    if (!activeAccountId) return;
    setExporting(true);
    try {
      const headers = new Headers();
      applyStaticAuthHeader(headers);
      const res = await fetch(`/api/bot/logs/export?accountId=${activeAccountId}`, {
        credentials: 'same-origin',
        headers,
      });
      if (!res.ok) throw new Error(`Export failed: ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `bot-logs-acc${activeAccountId}-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error(e);
    }
    setExporting(false);
  };

  useEffect(() => {
    fetchStatus();
    fetchLogs();
    // bot:log aboneligi useGlobalWiring'de app genelinde yapilir (cift satir olmasin);
    // loglar store (useUiStore.botLogs) uzerinden buraya akar.
    const unsub2 = wsClient.on('bot:started', () => fetchStatus());
    const unsub3 = wsClient.on('bot:stopped', () => fetchStatus());
    return () => { unsub2(); unsub3(); };
  }, [fetchStatus, fetchLogs]);

  useEffect(() => {
    fetchTrades(activeAccountId, 500);
    if (activeAccountId != null) {
      api.get<any[]>(`/accounts/${activeAccountId}/equity`).then((data) => {
        setEquityData(data.map((d: any) => ({
          time: d.recorded_at.split('T')[0].split(' ')[0],
          value: d.equity,
        })));
      }).catch(() => {});
    } else {
      setEquityData([]);
    }
  }, [activeAccountId, fetchTrades]);

  const handleStart = async () => {
    if (!activeAccountId) return;
    setLoading(true);
    try {
      const status = await api.post<any>('/bot/start', { accountId: activeAccountId });
      setBotStatus(activeAccountId, status);
      fetchLogs();
    } catch {}
    setLoading(false);
  };

  const handleStop = async () => {
    if (!activeAccountId) return;
    setLoading(true);
    try {
      const status = await api.post<any>('/bot/stop', { accountId: activeAccountId });
      setBotStatus(activeAccountId, status);
    } catch {}
    setLoading(false);
  };

  const isRunning = botStatus?.status === 'running';
  const logs = botLogs || [];

  const closed = trades.filter((t) => t.status === 'closed');
  const winners = closed.filter((t) => (t.pnl || 0) > 0);
  const losers = closed.filter((t) => (t.pnl || 0) <= 0);
  const totalPnl = closed.reduce((s, t) => s + (t.pnl || 0), 0);
  const totalFees = closed.reduce((s, t) => s + t.fee, 0);
  const avgWin = winners.length > 0 ? winners.reduce((s, t) => s + (t.pnl || 0), 0) / winners.length : 0;
  const avgLoss = losers.length > 0 ? Math.abs(losers.reduce((s, t) => s + (t.pnl || 0), 0) / losers.length) : 0;
  const grossProfit = winners.reduce((s, t) => s + (t.pnl || 0), 0);
  const grossLoss = Math.abs(losers.reduce((s, t) => s + (t.pnl || 0), 0));
  const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : (grossProfit > 0 ? 99 : 0);
  const bestTrade = closed.reduce((best, t) => (t.pnl || 0) > (best?.pnl || -Infinity) ? t : best, closed[0]);
  const worstTrade = closed.reduce((worst, t) => (t.pnl || 0) < (worst?.pnl || Infinity) ? t : worst, closed[0]);

  const pnlData = closed.slice(-50).map((t) => ({
    time: (t.closed_at || t.opened_at).split('T')[0].split(' ')[0],
    value: t.pnl || 0,
    color: (t.pnl || 0) >= 0 ? '#22C55E' : '#EF4444',
  }));

  const cellTrades = useMemo(() => {
    if (!selectedCell) return [];
    return closed.filter((t) => {
      const { day, hb } = istDayHour(t.closed_at || t.opened_at);
      return day === selectedCell.row && hb === selectedCell.col;
    });
  }, [closed, selectedCell]);

  const cellPnl = cellTrades.reduce((s, t) => s + (t.pnl || 0), 0);
  const cellWins = cellTrades.filter((t) => (t.pnl || 0) > 0).length;

  if (!activeAccountId) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <p className="text-ink-400 text-[13px] mb-1">Bot kontrolu icin bir hesap secin</p>
          <p className="text-ink-500 text-[11px]">Sol paneldeki dropdown'dan belirli bir hesap secin.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-auto">
      <div className="grid grid-cols-4">
        <StatCard label="STATUS" value={isRunning ? 'RUNNING' : 'STOPPED'} color={isRunning ? 'text-up' : 'text-ink-400'} />
        <StatCard label="SCANS" value={String(botStatus?.totalScans ?? 0)} />
        <StatCard label="SIGNALS" value={String(botStatus?.totalSignals ?? 0)} />
        <StatCard label="ORDERS" value={String(botStatus?.totalOrders ?? 0)} last />
      </div>


      {account && (
        <section className="border-t border-white/5">
          <div className="flex items-center px-4 h-7 border-b border-white/5 bg-ink-850">
            <div className="text-[9px] text-ink-300 tracking-[0.3em]">[ CONFIG - {account.name.toUpperCase()} ]</div>
          </div>
          <div className="flex flex-wrap gap-x-5 gap-y-0 px-4 py-1.5">
            <ConfigItem label="LONG" value={account.long_min_score} />
            <ConfigItem label="SHORT" value={account.short_min_score} />
            <ConfigItem label="LEV" value={`${account.bot_leverage}x`} />
            <ConfigItem label="POS" value={account.max_positions} />
            <ConfigItem label="TP/SL PRICE" value={`${Number(account.tp_percent).toFixed(2)}/${Number(account.sl_percent).toFixed(2)}%`} />
            <ConfigItem label="DD" value={account.max_drawdown_enabled ? `${account.max_drawdown}%` : 'OFF'} />
            <ConfigItem label="SCAN" value={`${account.scan_interval}s`} />
            <ConfigItem label="SRC" value={(account.signal_source || 'scanner').toUpperCase()} />
            <ConfigItem label="TRAIL" value={`${account.trailing_percent || 1}%`} />
          </div>
        </section>
      )}

      <section className="border-t border-white/5">
        <div className="grid grid-cols-2 lg:grid-cols-6 border-b border-white/5">
          <AnalStat label="NET PNL" value={formatUsd(totalPnl)} color={totalPnl >= 0 ? 'text-up' : 'text-down'} />
          <AnalStat label="WIN RATE" value={closed.length > 0 ? `${((winners.length / closed.length) * 100).toFixed(1)}%` : '-'} />
          <AnalStat label="PROFIT FACTOR" value={profitFactor > 0 ? profitFactor.toFixed(2) : '-'} />
          <AnalStat label="TOTAL FEES" value={formatUsd(totalFees)} />
          <AnalStat label="BEST TRADE" value={bestTrade ? formatUsd(bestTrade.pnl || 0) : '-'} color="text-up" />
          <AnalStat label="WORST TRADE" value={worstTrade ? formatUsd(worstTrade.pnl || 0) : '-'} color="text-down" />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 border-b border-white/5">
          <div className="border-r border-white/5">
            <div className="h-9 bg-ink-850 border-b border-white/5 flex items-center px-4 justify-between">
              <span className="text-[9px] tracking-[0.3em] text-ink-400 uppercase">[ PNL CALENDAR ]</span>
              <div className="flex items-center gap-2">
                <WinRateDonut wins={winners.length} losses={losers.length} size={24} />
                <span className="text-[9px] text-ink-300 num">{winners.length}W/{losers.length}L</span>
              </div>
            </div>
            <div className="p-2 bg-ink-900">
              <PnLCalendar
                trades={closed}
                selectedDate={selectedDate}
                onDayClick={(date, dayTrades) => {
                  if (selectedDate === date) { setSelectedDate(null); setSelectedDateTrades([]); }
                  else { setSelectedDate(date); setSelectedDateTrades(dayTrades); }
                }}
              />
            </div>
          </div>
          <div>
            {selectedDate ? (
              <>
                <div className="h-9 bg-ink-850 border-b border-white/5 flex items-center justify-between px-4">
                  <div className="flex items-center gap-3">
                    <span className="text-[9px] tracking-[0.3em] text-ink-400 uppercase">[ {selectedDate} ]</span>
                    <span className="text-[10px] text-ink-300 num">{selectedDateTrades.length}t</span>
                    <span className={`text-[10px] font-medium num ${selectedDateTrades.reduce((s: number, t: any) => s + (t.pnl || 0), 0) >= 0 ? 'text-up' : 'text-down'}`}>
                      {formatUsd(selectedDateTrades.reduce((s: number, t: any) => s + (t.pnl || 0), 0))}
                    </span>
                  </div>
                  <button onClick={() => { setSelectedDate(null); setSelectedDateTrades([]); }} className="text-ink-400 hover:text-ink-200 transition-colors">
                    <X size={14} />
                  </button>
                </div>
                {selectedDateTrades.length > 0 ? (
                  <div className="max-h-[280px] overflow-auto">
                    <table className="w-full text-[11px]">
                      <thead className="sticky top-0 bg-ink-850 z-10">
                        <tr className="text-ink-400 text-[9px] tracking-widest text-left">
                          <th className="px-3 py-2 font-medium">SYMBOL</th>
                          <th className="px-3 py-2 font-medium">SIDE</th>
                          <th className="px-3 py-2 font-medium text-right">PNL</th>
                          <th className="px-3 py-2 font-medium text-right">PNL%</th>
                          <th className="px-3 py-2 font-medium text-right">SCORE</th>
                          <th className="px-3 py-2 font-medium">REASON</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedDateTrades.map((t: any) => {
                          const pnl = t.pnl || 0;
                          const pnlColor = pnl > 0 ? 'text-up' : pnl < 0 ? 'text-down' : 'text-ink-400';
                          return (
                            <tr key={t.id}
                              onClick={() => navigate(`/trade/${t.id}`)}
                              className="border-b border-white/5 hover:bg-white/[0.02] cursor-pointer transition-colors">
                              <td className="px-3 py-1.5 text-ink-100 font-medium">{t.symbol.replace('USDT', '')}</td>
                              <td className="px-3 py-1.5">
                                <span className={`inline-flex items-center gap-0.5 ${t.side === 'long' ? 'text-up' : 'text-down'}`}>
                                  {t.side === 'long' ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
                                  {t.side.toUpperCase()}
                                </span>
                              </td>
                              <td className={`px-3 py-1.5 text-right font-medium num ${pnlColor}`}>{formatUsd(pnl)}</td>
                              <td className={`px-3 py-1.5 text-right num ${pnlColor}`}>{formatPercent(t.pnl_percent)}</td>
                              <td className="px-3 py-1.5 text-right num">
                                <span className={`${(t.signal_score || 0) > 0 ? 'text-up' : (t.signal_score || 0) < 0 ? 'text-down' : 'text-ink-500'}`}>
                                  {t.signal_score?.toFixed(1) ?? '-'}
                                </span>
                              </td>
                              <td className="px-3 py-1.5 text-ink-300 text-[10px] truncate max-w-[80px]">{t.exit_reason || '-'}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="flex items-center justify-center h-[200px] text-ink-500 text-[11px]">No trades on this day</div>
                )}
              </>
            ) : (
              <div className="flex items-center justify-center h-full text-ink-500 text-[11px]">Click a day to see trades</div>
            )}
          </div>
        </div>

      </section>

      <section className="border-t border-white/5 flex-1 flex flex-col min-h-0">
        <div className="flex items-center px-4 h-9 border-b border-white/5 bg-ink-850 gap-3">
          <div className="text-[9px] text-ink-400 tracking-[0.3em]">[ LOGS ]</div>
          {logsCount && (
            <span className="text-[9px] text-ink-500">
              {logs.length}/{logsCount.total.toLocaleString('tr-TR')} satır
              {logsCount.oldest && <span className="ml-2 text-ink-600">· {logsCount.oldest.slice(0, 10)} → {logsCount.newest?.slice(0, 10)}</span>}
            </span>
          )}
          <div className="ml-auto flex items-center gap-2">
            <select
              value={logsLimit}
              onChange={(e) => setLogsLimit(parseInt(e.target.value))}
              className="bg-ink-800 border border-white/5 text-ink-300 text-[10px] px-1.5 py-0.5 focus:outline-none cursor-pointer"
            >
              <option value={100}>son 100</option>
              <option value={500}>son 500</option>
              <option value={1000}>son 1000</option>
              <option value={5000}>son 5000</option>
              <option value={10000}>son 10K</option>
            </select>
            <button
              onClick={exportLogsCsv}
              disabled={exporting || !activeAccountId}
              className="flex items-center gap-1 text-[10px] text-info hover:text-info/80 disabled:opacity-40 transition-colors"
              title="Tüm logları CSV olarak indir"
            >
              <Download size={11} /> {exporting ? 'indiriliyor…' : 'CSV indir'}
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto max-h-[300px]">
          {logs.length === 0 ? (
            <p className="text-ink-500 text-[11px] px-4 py-3">No logs yet</p>
          ) : (
            logs.slice().reverse().map((log, i) => (
              <div key={i} className={`px-4 py-1 border-b border-white/5 font-mono text-[11px] ${
                log.level === 'error' ? 'text-down' : log.level === 'warn' ? 'text-warn' : 'text-ink-300'
              }`}>
                <span className="text-ink-500 num">{log.time.slice(11, 19)}</span>
                {' '}
                <span className={`font-medium ${
                  log.level === 'error' ? 'text-down' : log.level === 'warn' ? 'text-warn' : 'text-ink-400'
                }`}>[{log.level}]</span>
                {' '}{log.message}
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}

function buildHourHeatmap(trades: any[]) {
  const grid: Array<Array<{ label: string; value: number; count: number }>> = [];
  for (let day = 0; day < 7; day++) {
    const row: Array<{ label: string; value: number; count: number }> = [];
    for (let hb = 0; hb < 6; hb++) row.push({ label: '', value: 0, count: 0 });
    grid.push(row);
  }
  for (const t of trades) {
    const { day, hb } = istDayHour(t.closed_at || t.opened_at);
    if (grid[day]?.[hb]) { grid[day][hb].value += t.pnl || 0; grid[day][hb].count++; }
  }
  return grid;
}

function StatCard({ label, value, color, last }: { label: string; value: string; color?: string; last?: boolean }) {
  return (
    <div className={`px-4 py-3 bg-ink-900 ${last ? '' : 'border-r border-white/5'}`}>
      <p className="text-[9px] text-ink-400 tracking-[0.25em] mb-1">{label}</p>
      <p className={`text-[20px] font-semibold num ${color || 'text-ink-50'}`}>{value}</p>
    </div>
  );
}

function ConfigItem({ label, value }: { label: string; value: any }) {
  return (
    <span className="inline-flex items-center gap-1.5 py-1">
      <span className="text-[9px] text-ink-200 tracking-wide">{label}:</span>
      <span className="text-[11px] text-ink-50 num font-medium">{value}</span>
    </span>
  );
}

function AnalStat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="border-r border-white/5 px-4 py-3 bg-ink-900">
      <p className="text-[9px] tracking-[0.25em] text-ink-400 uppercase mb-1">{label}</p>
      <p className={`text-[16px] font-semibold num ${color || 'text-ink-50'}`}>{value}</p>
    </div>
  );
}
