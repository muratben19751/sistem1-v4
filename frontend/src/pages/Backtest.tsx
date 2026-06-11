import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAccountStore } from '../store/account-store';
import { useBacktestStore, type OptimizerResultRow } from '../store/backtest-store';
import { formatUsd, formatPrice, formatDate } from '../lib/formatters';
import { wsClient } from '../lib/ws';
import EquityCurve from '../components/charts/EquityCurve';

const SOURCES = ['', 'fr', 'hammer', 'sniper', 'm1_a', 'v3_a', 'hammer+sniper+fr', 'all'];
function cl(v: number) { return v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-ink-200'; }

// tested_at UTC ('YYYY-MM-DD HH:MM:SS') -> yerel saat 'YYYY-MM-DD HH:MM'
function localDt(s: string | null | undefined): string {
  if (!s) return '-';
  const d = new Date(s.replace(' ', 'T') + (s.endsWith('Z') ? '' : 'Z'));
  if (isNaN(d.getTime())) return s.slice(0, 16);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

const OPT_COLS: { label: string; key: keyof OptimizerResultRow | null }[] = [
  { label: '#', key: null },
  { label: 'Strateji', key: 'strategy_name' },
  { label: 'Gen', key: 'generation' },
  { label: 'Pencere', key: 'backtest_days' },
  { label: 'Islem', key: 'trades' },
  { label: 'WR', key: 'win_rate' },
  { label: 'PnL', key: 'total_pnl' },
  { label: 'MaxDD', key: 'max_drawdown' },
  { label: 'Calmar', key: 'calmar' },
  { label: 'PF', key: 'profit_factor' },
  { label: 'Sharpe', key: 'sharpe_estimate' },
  { label: 'Tarih', key: 'tested_at' },
  { label: 'LEAN', key: null },
];

const LEAN_PARITY: Record<string, { cls: string; text: string; title: string }> = {
  pass: { cls: 'text-up border-up/40 bg-up/10', text: 'UYUMLU', title: 'LEAN ile dogrulandi: win-rate paritesi tutuyor (icra/cikis matematigi sadik)' },
  warn: { cls: 'text-warn border-warn/40 bg-warn/10', text: 'KISMI', title: 'LEAN ile kismi uyum: win-rate yakin ama islem sayisi/ikincil metrikler sapiyor' },
  fail: { cls: 'text-down border-down/40 bg-down/10', text: 'INCELE', title: 'LEAN paritesi tutmadi: win-rate >%5 sapiyor (olasi icra farki)' },
};

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="px-3 py-2 bg-ink-900 border border-white/5">
      <div className="text-[9px] tracking-widest text-ink-400 uppercase">{label}</div>
      <div className={`num text-[17px] font-semibold ${tone || 'text-ink-50'}`}>{value}</div>
    </div>
  );
}

function ManualBacktest() {
  const { accounts, activeAccountId, fetchAccounts } = useAccountStore();
  const { result, loading, error, progress, run } = useBacktestStore();
  const [accountId, setAccountId] = useState<number | null>(activeAccountId);
  const today = new Date();
  const [from, setFrom] = useState(new Date(today.getTime() - 30 * 86400000).toISOString().slice(0, 10));
  const [to, setTo] = useState(today.toISOString().slice(0, 10));
  const [source, setSource] = useState('');

  useEffect(() => { fetchAccounts(); }, [fetchAccounts]);
  useEffect(() => { if (accountId == null && accounts.length) setAccountId(activeAccountId ?? accounts[0].id); }, [accounts, activeAccountId, accountId]);

  const equityDaily = useMemo(() => {
    if (!result) return [];
    const map = new Map<string, number>();
    for (const p of result.equityCurve) map.set(new Date(p.time * 1000).toISOString().slice(0, 10), p.value);
    return [...map.entries()].map(([time, value]) => ({ time, value }));
  }, [result]);

  const doRun = () => {
    if (accountId == null) return;
    const startMs = Date.parse(from + 'T00:00:00Z');
    const endMs = Date.parse(to + 'T23:59:59Z');
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) return;
    run(accountId, startMs, endMs, source);
  };

  const m = result?.metrics;
  return (
    <>
      <div className="flex items-end gap-3 flex-wrap px-4 py-3 border-b border-white/5 bg-ink-900 shrink-0">
        <div>
          <label className="text-[9px] tracking-wider text-ink-400 uppercase block mb-1">Bot</label>
          <select value={accountId ?? ''} onChange={(e) => setAccountId(Number(e.target.value))} className="h-8 bg-ink-800 border border-white/10 px-2 text-[11px] text-ink-100 outline-none">
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[9px] tracking-wider text-ink-400 uppercase block mb-1">Kaynak</label>
          <select value={source} onChange={(e) => setSource(e.target.value)} className="h-8 bg-ink-800 border border-white/10 px-2 text-[11px] text-ink-100 outline-none">
            {SOURCES.map((s) => <option key={s} value={s}>{s || '(bot ayari)'}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[9px] tracking-wider text-ink-400 uppercase block mb-1">Baslangic</label>
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-8 bg-ink-800 border border-white/10 px-2 text-[11px] text-ink-100 outline-none" />
        </div>
        <div>
          <label className="text-[9px] tracking-wider text-ink-400 uppercase block mb-1">Bitis</label>
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="h-8 bg-ink-800 border border-white/10 px-2 text-[11px] text-ink-100 outline-none" />
        </div>
        <button onClick={doRun} disabled={loading || accountId == null} className="h-8 px-4 text-[11px] bg-up/20 border border-up/40 text-up disabled:opacity-40">
          {loading ? 'Calisiyor...' : 'Backtest Et'}
        </button>
        {error && <span className="text-[11px] text-down">{error}</span>}
      </div>

      <div className="p-3 space-y-3 overflow-y-auto">
        {loading && (
          <div className="text-[11px] text-ink-400">
            {progress?.phase === 'preload'
              ? `Tarihsel kline cekiliyor (sembol ${progress.done}/${progress.total})... ilk calistirmada uzun surebilir.`
              : progress?.phase === 'simulate'
                ? `Simule ediliyor (sinyal ${progress.done}/${progress.total})...`
                : 'Baslatiliyor...'}
          </div>
        )}
        {!result && !loading && <div className="text-[11px] text-ink-500">Bir bot ve tarih araligi secip "Backtest Et"e bas.</div>}
        {m && (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-px bg-white/5 border border-white/5">
              <Metric label="Net PnL" value={`${m.totalPnl >= 0 ? '+' : ''}${formatUsd(m.totalPnl)}`} tone={cl(m.totalPnl)} />
              <Metric label="PnL %" value={`${m.totalPnlPct >= 0 ? '+' : ''}${m.totalPnlPct.toFixed(2)}%`} tone={cl(m.totalPnlPct)} />
              <Metric label="Win Rate" value={`%${m.winRate.toFixed(1)}`} />
              <Metric label="Islem" value={`${m.trades} (${m.wins}W/${m.losses}L)`} />
              <Metric label="Profit Factor" value={m.profitFactor.toFixed(2)} tone={m.profitFactor >= 1.5 ? 'text-up' : m.profitFactor >= 1 ? 'text-warn' : 'text-down'} />
              <Metric label="Max DD" value={`-${m.maxDrawdown.toFixed(2)}%`} tone={m.maxDrawdown >= 20 ? 'text-down' : m.maxDrawdown >= 10 ? 'text-warn' : 'text-ink-200'} />
              <Metric label="Calmar" value={m.calmar.toFixed(2)} tone={m.calmar >= 1 ? 'text-up' : 'text-ink-200'} />
            </div>
            <div className="text-[10px] text-ink-500">
              Sinyal: {result!.coverage.totalSignals} · degerlendirilen: {result!.coverage.evaluated} · giris: {result!.coverage.entered} · sembol: {result!.coverage.symbols} · kural-veri kapsami: %{result!.coverage.avgTfCoverage} · Sharpe {m.sharpe.toFixed(2)} · avgWin {formatUsd(m.avgWin)} / avgLoss {formatUsd(m.avgLoss)}
            </div>
            <div className="bg-ink-900 border border-white/5">
              <div className="h-8 flex items-center px-3 bg-ink-850 border-b border-white/5"><span className="text-[9px] tracking-[0.3em] text-ink-400">[ KASA EGRISI ]</span></div>
              <div className="p-2">{equityDaily.length > 1 ? <EquityCurve data={equityDaily} height={240} /> : <div className="h-[120px] flex items-center justify-center text-[11px] text-ink-600">Yetersiz veri</div>}</div>
            </div>
            <div className="bg-ink-900 border border-white/5">
              <div className="h-8 flex items-center px-3 bg-ink-850 border-b border-white/5"><span className="text-[9px] tracking-[0.3em] text-ink-400">[ ISLEMLER ] {result!.trades.length}</span></div>
              <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
                <table className="w-full">
                  <thead className="sticky top-0 bg-ink-900"><tr className="border-b border-white/5">
                    {['Coin', 'Yon', 'Giris', 'Cikis', 'Giris$', 'Cikis$', 'PnL', 'PnL%', 'Sebep', 'Skor'].map((h) => <th key={h} className="text-left text-[9px] text-ink-500 px-2 py-1 uppercase tracking-wider">{h}</th>)}
                  </tr></thead>
                  <tbody>
                    {result!.trades.slice(0, 300).map((t, i) => (
                      <tr key={i} className="border-b border-white/5 hover:bg-white/[0.02]">
                        <td className="px-2 py-1 text-[11px] text-ink-100">{t.symbol.replace('USDT', '')}</td>
                        <td className="px-2 py-1 text-[11px]"><span className={t.side === 'long' ? 'text-up' : 'text-down'}>{t.side.toUpperCase()}</span></td>
                        <td className="px-2 py-1 text-[10px] num text-ink-400">{formatDate(new Date(t.entryMs).toISOString())}</td>
                        <td className="px-2 py-1 text-[10px] num text-ink-400">{formatDate(new Date(t.exitMs).toISOString())}</td>
                        <td className="px-2 py-1 text-[11px] num text-ink-300">{formatPrice(t.entryPrice)}</td>
                        <td className="px-2 py-1 text-[11px] num text-ink-300">{formatPrice(t.exitPrice)}</td>
                        <td className={`px-2 py-1 text-[11px] num ${cl(t.pnl)}`}>{t.pnl >= 0 ? '+' : ''}{formatUsd(t.pnl)}</td>
                        <td className={`px-2 py-1 text-[11px] num ${cl(t.pnlPercent)}`}>{t.pnlPercent.toFixed(2)}%</td>
                        <td className="px-2 py-1 text-[10px]"><span className={t.exitReason === 'tp_hit' ? 'text-up' : t.exitReason === 'sl_hit' ? 'text-down' : 'text-ink-400'}>{t.exitReason}</span></td>
                        <td className="px-2 py-1 text-[10px] num text-ink-400">{t.score}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}

export function OptimizerLab() {
  const { optStatus, optStats, optResults, optInsights, optLog, optUnique, setOptUnique, optOnlyYear, setOptOnlyYear, optHideJunk, setOptHideJunk, fetchOptimizer, startOptimizer, stopOptimizer, deployConfig, stopStrategy, fetchFreeAccounts, pushOptLog } = useBacktestStore();
  const { fetchAccounts } = useAccountStore();
  const navigate = useNavigate();
  const [selected, setSelected] = useState<OptimizerResultRow | null>(null);
  const [freeAccounts, setFreeAccounts] = useState<Array<{ id: number; name: string; engine: string; hasCredentials: boolean; running: boolean }>>([]);
  const [pickedAccount, setPickedAccount] = useState<number | null>(null);
  const [applyMsg, setApplyMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [sortKey, setSortKey] = useState<keyof OptimizerResultRow | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const toggleSort = (key: keyof OptimizerResultRow) => {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else { setSortKey(key); setSortDir('desc'); }
  };
  const sortedResults = useMemo(() => {
    if (!sortKey) return optResults;
    const dir = sortDir === 'asc' ? 1 : -1;
    return [...optResults].sort((a: any, b: any) => {
      const av = a[sortKey]; const bv = b[sortKey];
      if (typeof av === 'string' || typeof bv === 'string') return String(av ?? '').localeCompare(String(bv ?? '')) * dir;
      return ((Number(av) || 0) - (Number(bv) || 0)) * dir;
    });
  }, [optResults, sortKey, sortDir]);

  useEffect(() => {
    fetchOptimizer();
    const t = setInterval(fetchOptimizer, 5000);
    const u1 = wsClient.on('optimizer:log', (d: any) => pushOptLog(`${(d?.time || '').slice(11, 19)} ${d?.message ?? ''}`));
    const u2 = wsClient.on('optimizer:cycle-complete', () => fetchOptimizer());
    return () => { clearInterval(t); u1(); u2(); };
  }, [fetchOptimizer, pushOptLog]);

  const running = optStatus?.running;
  const cfg = useMemo(() => { try { return selected ? JSON.parse(selected.config_json) : null; } catch { return null; } }, [selected]);

  // Secili strateji canli mi? (deploy_state tabanli rozet)
  const selLive = selected != null && selected.badge === 'live';

  // Bosta API havuzunu yukle (sadece running===false olanlar gosterilir)
  const loadFreeAccounts = useCallback(async () => {
    try { setFreeAccounts(await fetchFreeAccounts()); } catch { /* ignore */ }
  }, [fetchFreeAccounts]);

  // detay paneli acildiginda / secili strateji degistiginde bos hesaplari tazele
  useEffect(() => {
    setPickedAccount(null);
    setApplyMsg('');
    if (selected) loadFreeAccounts();
  }, [selected?.id, loadFreeAccounts]);

  return (
    <div className="p-3 space-y-3 overflow-y-auto">
      <div className="flex items-center gap-3 flex-wrap bg-ink-900 border border-white/5 px-3 py-2">
        <span className={`w-2 h-2 rounded-full ${running ? 'bg-up' : 'bg-ink-500'}`} />
        <span className="text-[11px] text-ink-200">{running ? 'CALISIYOR' : 'DURDU'}</span>
        <span className="text-[10px] text-ink-400 num">Gen {optStatus?.generation ?? '-'} · degerlendirilen {optStatus?.evaluated ?? 0} · pop {optStatus?.populationSize ?? 0} · pencere {optStatus?.backtestDays ?? '-'}g</span>
        <span className="text-[10px] text-ink-400 num">En iyi Calmar: <span className="text-up">{optStatus?.bestCalmar ?? 0}</span></span>
        {optStats && (
          <span className="text-[10px] num flex items-center gap-1.5" title="Tum optimizer sonuclari uzerinden ozet (cop = maxDD=0 / Calmar=99 artifakti veya <20 islem; saglam = walk-forward robFit > 0)">
            <span className="text-ink-600">|</span>
            <span className="text-ink-400">Toplam test: <span className="text-ink-100">{optStats.total}</span></span>
            <span className="text-ink-600">·</span>
            <span className="text-ink-400">Çöp: <span className="text-warn">{optStats.junk}</span> <span className="text-ink-600">(%{optStats.junkPct})</span></span>
            <span className="text-ink-600">·</span>
            <span className="text-ink-400">Sağlam robFit&gt;0: <span className="text-up">{optStats.robust}</span></span>
            <span className="text-ink-600">·</span>
            <span className="text-ink-400">En iyi robFit: <span className="text-up">{optStats.bestRobFit != null ? Number(optStats.bestRobFit).toFixed(2) : '-'}</span></span>
          </span>
        )}
        {optStatus?.currentName && <span className="text-[10px] text-ink-500 num truncate">→ {optStatus.currentName}</span>}
        <div className="ml-auto flex gap-2">
          <button onClick={startOptimizer} disabled={running} className="h-7 px-3 text-[10px] bg-up/20 border border-up/40 text-up disabled:opacity-40">Baslat</button>
          <button onClick={stopOptimizer} disabled={!running} className="h-7 px-3 text-[10px] bg-down/20 border border-down/40 text-down disabled:opacity-40">Durdur</button>
        </div>
      </div>
      <div className="text-[10px] text-ink-500">
        Ajan sürekli yeni strateji (kural kombinasyonu + parametre) üretip Telegram geçmişinde backtest eder; max-profit / min-DD (Calmar) en iyiyi arar. İlk calistirmada kline cache doldugu icin yavas baslar.
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <div className="lg:col-span-2 bg-ink-900 border border-white/5">
          <div className="h-8 flex items-center px-3 bg-ink-850 border-b border-white/5">
            <span className="text-[9px] tracking-[0.3em] text-ink-400">[ LEADERBOARD (Calmar) ]</span>
            <button
              onClick={() => setOptOnlyYear(!optOnlyYear)}
              title="Sadece 1 yillik (365g) pencerede backtest edilmis sonuclari goster"
              className={`ml-auto h-5 px-2 text-[9px] tracking-wider border ${optOnlyYear ? 'bg-demo/15 border-demo/40 text-demo' : 'bg-ink-800 border-white/10 text-ink-400'}`}
            >Sadece 1Y {optOnlyYear ? 'ON' : 'OFF'}</button>
            <button
              onClick={() => setOptUnique(!optUnique)}
              title="Ayni performansli tekrar stratejileri gizle"
              className={`ml-2 h-5 px-2 text-[9px] tracking-wider border ${optUnique ? 'bg-up/15 border-up/40 text-up' : 'bg-ink-800 border-white/10 text-ink-400'}`}
            >Benzersiz {optUnique ? 'ON' : 'OFF'}</button>
            <button
              onClick={() => setOptHideJunk(!optHideJunk)}
              title="Cop stratejileri gizle (maxDD=0 / Calmar=99 artifakti ve <20 islem)"
              className={`ml-2 h-5 px-2 text-[9px] tracking-wider border ${optHideJunk ? 'bg-warn/15 border-warn/40 text-warn' : 'bg-ink-800 border-white/10 text-ink-400'}`}
            >Cop gizle {optHideJunk ? 'ON' : 'OFF'}</button>
          </div>
          <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
            <table className="w-full">
              <thead className="sticky top-0 bg-ink-900"><tr className="border-b border-white/5">
                {OPT_COLS.map((c) => (
                  <th
                    key={c.label}
                    onClick={c.key ? () => toggleSort(c.key!) : undefined}
                    className={`text-left text-[9px] text-ink-500 px-2 py-1 uppercase tracking-wider ${c.key ? 'cursor-pointer hover:text-ink-200 select-none' : ''}`}
                  >
                    {c.label}{c.key && sortKey === c.key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
                  </th>
                ))}
              </tr></thead>
              <tbody>
                {optResults.length === 0 ? (
                  <tr><td colSpan={13} className="text-center text-ink-600 py-6 text-[11px]">Henuz sonuc yok. "Baslat"a bas.</td></tr>
                ) : sortedResults.map((r, i) => {
                  // CANLI = bot FIILEN calisiyor (live_running). bot_enabled DB bayragi degil;
                  // durdurulmus ama bayragi 1 kalmis stratejiler STOPPED gosterilsin.
                  // live_running yoksa (eski backend) bot_enabled'a dus -> deploy sirasina dayanikli.
                  const live = r.badge === 'live';
                  const stopped = r.badge === 'stopped';
                  const rowTitle = live
                    ? `Canli: ${r.live_account_name} (#${r.live_account_id})`
                    : stopped
                      ? (r.live_account_id != null ? `Durduruldu: ${r.live_account_name} (#${r.live_account_id})` : 'Durduruldu: hesap silinmis')
                      : undefined;
                  return (
                  <tr key={r.id} onClick={() => setSelected(r)} title={rowTitle} className={`border-b border-white/5 cursor-pointer ${live ? 'bg-up/[0.07] hover:bg-up/[0.12] border-l-2 border-l-up' : stopped ? 'bg-white/[0.02] hover:bg-white/[0.05] border-l-2 border-l-ink-500' : 'hover:bg-white/[0.03]'}`}>
                    <td className="px-2 py-1 text-[10px] num">
                      {live
                        ? <span className="flex items-center gap-1 text-up font-semibold"><span className="w-1.5 h-1.5 rounded-full bg-up pulse-dot" />CANLI</span>
                        : stopped
                          ? <span className="flex items-center gap-1 text-ink-400 font-semibold"><span className="w-1.5 h-1.5 rounded-full bg-ink-500" />STOPPED</span>
                          : <span className="text-ink-500">{i + 1}</span>}
                    </td>
                    <td className="px-2 py-1 text-[11px] text-ink-100 max-w-[200px]">
                      <span className="inline-flex items-center gap-1.5 min-w-0">
                        <span className="truncate">{r.strategy_name}</span>
                        {live && <span className="shrink-0 text-[8px] font-bold tracking-[0.12em] text-up border border-up/40 bg-up/10 rounded px-1 py-px">CANLI</span>}
                        {stopped && <span className="shrink-0 text-[8px] font-bold tracking-[0.12em] text-ink-400 border border-white/20 bg-white/5 rounded px-1 py-px">STOPPED</span>}
                      </span>
                      {(live || stopped) && r.deployed_at && (
                        <span className={`block text-[8px] num mt-0.5 ${live ? 'text-up/70' : 'text-ink-500'}`} title="Canliya alindigi tarih/saat">⏱ {localDt(r.deployed_at)}</span>
                      )}
                    </td>
                    <td className="px-2 py-1 text-[10px] num text-ink-400">{r.generation}</td>
                    <td className="px-2 py-1">
                      {(() => {
                        const d = r.backtest_days ?? 0;
                        if (d >= 365) return <span title={`${d} gunluk backtest (1 yil)`} className="text-[9px] tracking-wider font-semibold text-demo border border-demo/40 bg-demo/10 rounded px-1 py-px">1Y</span>;
                        if (d > 0) return <span title={`${d} gunluk backtest`} className="text-[9px] num text-ink-500 border border-white/10 rounded px-1 py-px">{d}g</span>;
                        return <span title="pencere bilinmiyor (eski sonuc)" className="text-[10px] text-ink-700">—</span>;
                      })()}
                    </td>
                    <td className="px-2 py-1 text-[10px] num text-ink-100 font-medium" title={`${r.wins}W / ${r.losses}L`}>{r.trades}</td>
                    <td className="px-2 py-1 text-[10px] num text-ink-300">{r.win_rate.toFixed(0)}%</td>
                    <td className={`px-2 py-1 text-[10px] num ${cl(r.total_pnl)}`}>{formatUsd(r.total_pnl)}</td>
                    <td className="px-2 py-1 text-[10px] num text-warn">-{r.max_drawdown.toFixed(1)}%</td>
                    <td className="px-2 py-1 text-[10px] num text-up font-medium">{r.calmar.toFixed(2)}</td>
                    <td className="px-2 py-1 text-[10px] num text-ink-300">{r.profit_factor.toFixed(2)}</td>
                    <td className="px-2 py-1 text-[10px] num text-ink-300">{r.sharpe_estimate.toFixed(2)}</td>
                    <td className="px-2 py-1 text-[9px] num text-ink-500 whitespace-nowrap">{localDt(r.tested_at)}</td>
                    <td
                      className="px-2 py-1 whitespace-nowrap cursor-pointer"
                      onClick={(e) => { e.stopPropagation(); navigate(`/lean?strategy=${encodeURIComponent(r.strategy_name)}`); }}
                    >
                      {r.leanParity && LEAN_PARITY[r.leanParity] ? (
                        <span title={`${LEAN_PARITY[r.leanParity].title} — LEAN raporunu ac`} className={`text-[8px] font-bold tracking-[0.1em] border rounded px-1 py-px hover:brightness-125 ${LEAN_PARITY[r.leanParity].cls}`}>
                          {LEAN_PARITY[r.leanParity].text}
                        </span>
                      ) : (
                        <span title="LEAN raporunu ac (bu strateji henuz dogrulanmadiysa kosma komutu gosterilir)" className="text-[10px] text-ink-700 hover:text-ink-400">—</span>
                      )}
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {cfg && (
            <div className="border-t border-white/5 p-3 text-[10px] text-ink-300 space-y-2">
              <div className="text-ink-400">{selected?.strategy_name} · kaynak: <span className="text-ink-100">{cfg.signalSource}</span> · lev {cfg.leverage}x · {(cfg.tpAtrMult || cfg.slAtrMult) ? <span className="text-info">TP {Number(cfg.tpAtrMult).toFixed(1)}×ATR / SL {Number(cfg.slAtrMult).toFixed(1)}×ATR ({cfg.atrTimeframe ?? '15'}m)</span> : <>TP {Number(cfg.tpPercent).toFixed(1)}% / SL {Number(cfg.slPercent).toFixed(1)}%</>} · minScore {Number(cfg.longMinScore).toFixed(1)} · maxPos {cfg.maxPositions}</div>
              {(cfg.hourStart != null && cfg.hourEnd != null) || (Array.isArray(cfg.allowedDays) && cfg.allowedDays.length > 0) ? (
                <div className="text-teal-400">zaman:
                  {cfg.hourStart != null && cfg.hourEnd != null && <span> {String(cfg.hourStart).padStart(2, '0')}:00–{String(cfg.hourEnd).padStart(2, '0')}:00 UTC</span>}
                  {Array.isArray(cfg.allowedDays) && cfg.allowedDays.length > 0 && <span> · gunler: {cfg.allowedDays.map((d: number) => ['Paz', 'Pzt', 'Sal', 'Car', 'Per', 'Cum', 'Cmt'][d]).join(',')}</span>}
                </div>
              ) : null}
              <div className="text-ink-500">kurallar ({cfg.enabledRules?.length ?? 0}): {(cfg.enabledRules ?? []).join(', ') || 'tumu'}</div>
              {cfg._wf && typeof cfg._wf === 'object' ? (
                <div className="text-amber-400">
                  robustluk: robFit <span className="num">{Number(cfg._wf.robustFitness).toFixed(2)}</span>
                  {' '}· gecerli fold <span className="num">{cfg._wf.validFolds}/{cfg._wf.folds}</span>
                  {' '}· embargo {cfg._wf.embargoDays}g
                  {Array.isArray(cfg._wf.foldCalmar) && cfg._wf.foldCalmar.length > 0 && (
                    <span> · fold Calmar: {cfg._wf.foldCalmar.map((c: number) => Number(c).toFixed(2)).join(' / ')}</span>
                  )}
                  {cfg._wf.stdQuality != null && <span> · std {Number(cfg._wf.stdQuality).toFixed(2)}</span>}
                </div>
              ) : null}
              <div className="flex items-center gap-2 pt-1">
                {selLive ? (
                  <button
                    disabled={busy || !selected}
                    onClick={async () => {
                      if (!selected) return;
                      setBusy(true); setApplyMsg('');
                      try {
                        const r = await stopStrategy(selected.id);
                        await fetchAccounts(); await fetchOptimizer(); await loadFreeAccounts();
                        setApplyMsg(r.stopped?.length ? `Durduruldu (${r.stopped.length} bot)` : 'Durduruldu');
                      } catch (e: any) { setApplyMsg('Hata: ' + (e?.message || '')); }
                      finally { setBusy(false); }
                    }}
                    className="h-7 px-3 text-[10px] bg-down/20 border border-down/40 text-down disabled:opacity-40"
                    title="Bu stratejiyi calistiran botu durdur (Bybit API serbest kalir)"
                  >⏹ Durdur</button>
                ) : (
                  <>
                    <select
                      value={pickedAccount ?? ''}
                      onChange={(e) => setPickedAccount(e.target.value === '' ? null : Number(e.target.value))}
                      className="h-7 bg-ink-800 border border-white/10 px-2 text-[10px] text-ink-100 outline-none"
                    >
                      <option value="">bosta API sec...</option>
                      {freeAccounts.filter((a) => a.running === false).map((a) => (
                        <option key={a.id} value={a.id}>{a.name}{a.hasCredentials ? '' : ' (API yok)'}</option>
                      ))}
                    </select>
                    <button
                      disabled={busy || pickedAccount == null || !selected}
                      onClick={async () => {
                        if (!selected || pickedAccount == null) return;
                        setBusy(true); setApplyMsg('');
                        try {
                          const r = await deployConfig(selected.id, pickedAccount);
                          await fetchAccounts(); await fetchOptimizer(); await loadFreeAccounts();
                          setApplyMsg(`Canliya alindi: ${r.name}${r.started ? ' ✓' : ' (baslamadi)'}`);
                        } catch (e: any) { setApplyMsg('Hata: ' + (e?.message || '')); }
                        finally { setBusy(false); }
                      }}
                      className="h-7 px-3 text-[10px] bg-up/20 border border-up/40 text-up disabled:opacity-40"
                      title="Secili bos Bybit API hesabina uygula + baslat. Hesabin eski strateji istatistikleri sifirlanir (trade gecmisi arsive tasinir)"
                    >▶ Canliya Al</button>
                  </>
                )}
                {applyMsg && <span className="text-[10px] text-ink-300">{applyMsg}</span>}
              </div>
            </div>
          )}
        </div>

        <div className="space-y-3">
          <div className="bg-ink-900 border border-white/5">
            <div className="h-8 flex items-center px-3 bg-ink-850 border-b border-white/5"><span className="text-[9px] tracking-[0.3em] text-ink-400">[ ICGORULER ]</span></div>
            <div className="p-2 space-y-1 max-h-[180px] overflow-y-auto">
              {optInsights.length === 0 ? <div className="text-[10px] text-ink-600">-</div> : optInsights.map((it) => (
                <div key={it.id} className={`text-[10px] ${it.type === 'success' ? 'text-up' : 'text-ink-300'}`}>{it.message}</div>
              ))}
            </div>
          </div>
          <div className="bg-ink-900 border border-white/5">
            <div className="h-8 flex items-center px-3 bg-ink-850 border-b border-white/5"><span className="text-[9px] tracking-[0.3em] text-ink-400">[ CANLI LOG ]</span></div>
            <div className="p-2 space-y-px max-h-[220px] overflow-y-auto font-mono">
              {optLog.length === 0 ? <div className="text-[10px] text-ink-600">-</div> : optLog.slice(-60).map((l, i) => <div key={i} className="text-[9px] text-ink-400 leading-[14px]">{l}</div>)}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Backtest() {
  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="h-9 flex items-center gap-1 px-3 bg-ink-850 border-b border-white/5 shrink-0">
        <span className="text-[9px] tracking-[0.3em] text-ink-400">[ MANUEL BACKTEST ]</span>
      </div>
      <ManualBacktest />
    </div>
  );
}
