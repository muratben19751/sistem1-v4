import { useEffect, useMemo, useState } from 'react';
import { useAccountStore } from '../../store/account-store';
import { useBacktestStore, type OptimizerResultRow } from '../../store/backtest-store';
import { formatUsd } from '../../lib/formatters';
import { wsClient } from '../../lib/ws';
import EquityCurve from '../../components/charts/EquityCurve';

const SOURCES = ['', 'fr', 'hammer', 'sniper', 'm1_a', 'v3_a', 'hammer+sniper+fr', 'all'];
function cl(v: number) { return v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-ink-200'; }

function Cell({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="bg-ink-850 border border-white/5 rounded px-2.5 py-2">
      <div className="text-[9px] tracking-wider text-ink-400 uppercase">{label}</div>
      <div className={`num text-[15px] font-semibold ${tone || 'text-ink-50'}`}>{value}</div>
    </div>
  );
}

function ManualTab() {
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
  const inp = 'h-10 w-full bg-ink-800 border border-white/10 rounded px-2 text-[13px] text-ink-100 outline-none';

  return (
    <div className="p-3 space-y-3">
      <div className="space-y-2">
        <select value={accountId ?? ''} onChange={(e) => setAccountId(Number(e.target.value))} className={inp}>
          {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        <select value={source} onChange={(e) => setSource(e.target.value)} className={inp}>
          {SOURCES.map((s) => <option key={s} value={s}>{s ? `kaynak: ${s}` : 'kaynak: (bot ayari)'}</option>)}
        </select>
        <div className="grid grid-cols-2 gap-2">
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={inp} />
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className={inp} />
        </div>
        <button onClick={doRun} disabled={loading || accountId == null} className="h-11 w-full rounded bg-up/20 border border-up/40 text-up text-[13px] font-medium active:bg-up/30 disabled:opacity-40">
          {loading ? 'Calisiyor...' : 'Backtest Et'}
        </button>
        {loading && progress && (
          <div className="text-[11px] text-ink-400 text-center">
            {progress.phase === 'preload' ? `Kline cekiliyor ${progress.done}/${progress.total}...` : progress.phase === 'simulate' ? `Simule ${progress.done}/${progress.total}...` : 'Baslatiliyor...'}
          </div>
        )}
        {error && <div className="text-[12px] text-down text-center">{error}</div>}
      </div>

      {m && (
        <>
          <div className="grid grid-cols-2 gap-2">
            <Cell label="Net PnL" value={`${m.totalPnl >= 0 ? '+' : ''}${formatUsd(m.totalPnl)}`} tone={cl(m.totalPnl)} />
            <Cell label="PnL %" value={`${m.totalPnlPct >= 0 ? '+' : ''}${m.totalPnlPct.toFixed(1)}%`} tone={cl(m.totalPnlPct)} />
            <Cell label="Win Rate" value={`%${m.winRate.toFixed(1)}`} />
            <Cell label="Islem" value={`${m.trades} · ${m.wins}W/${m.losses}L`} />
            <Cell label="Max DD" value={`-${m.maxDrawdown.toFixed(1)}%`} tone={m.maxDrawdown >= 20 ? 'text-down' : m.maxDrawdown >= 10 ? 'text-warn' : 'text-ink-200'} />
            <Cell label="Calmar" value={m.calmar.toFixed(2)} tone={m.calmar >= 1 ? 'text-up' : 'text-ink-200'} />
          </div>
          {result && <div className="text-[10px] text-ink-500 text-center">PF {m.profitFactor.toFixed(2)} · Sharpe {m.sharpe.toFixed(2)} · giris {result.coverage.entered}/{result.coverage.totalSignals} · kapsam %{result.coverage.avgTfCoverage}</div>}
          {equityDaily.length > 1 && (
            <div className="bg-ink-850 border border-white/5 rounded p-1">
              <EquityCurve data={equityDaily} height={170} />
            </div>
          )}
          <div className="space-y-1">
            {(result?.trades ?? []).slice(0, 50).map((t, i) => (
              <div key={i} className="flex items-center justify-between bg-ink-850 border border-white/5 rounded px-2.5 py-1.5 text-[11px]">
                <span className="text-ink-100 w-16 truncate">{t.symbol.replace('USDT', '')}</span>
                <span className={t.side === 'long' ? 'text-up w-10' : 'text-down w-10'}>{t.side.toUpperCase()}</span>
                <span className={`num ${t.exitReason === 'tp_hit' ? 'text-up' : t.exitReason === 'sl_hit' ? 'text-down' : 'text-ink-400'} w-14 text-center text-[10px]`}>{t.exitReason}</span>
                <span className={`num ${cl(t.pnl)} w-16 text-right`}>{t.pnl >= 0 ? '+' : ''}{formatUsd(t.pnl)}</span>
              </div>
            ))}
          </div>
        </>
      )}
      {!m && !loading && <p className="text-center text-ink-500 text-[12px] py-8">Bot + tarih secip "Backtest Et"e bas.</p>}
    </div>
  );
}

function OptimizerTab() {
  const { optStatus, optResults, fetchOptimizer, startOptimizer, stopOptimizer } = useBacktestStore();
  const [sel, setSel] = useState<OptimizerResultRow | null>(null);

  useEffect(() => {
    fetchOptimizer();
    const t = setInterval(fetchOptimizer, 5000);
    const u = wsClient.on('optimizer:cycle-complete', () => fetchOptimizer());
    return () => { clearInterval(t); u(); };
  }, [fetchOptimizer]);

  const cfg = useMemo(() => { try { return sel ? JSON.parse(sel.config_json) : null; } catch { return null; } }, [sel]);
  const running = optStatus?.running;

  return (
    <div className="p-3 space-y-3">
      <div className="bg-ink-850 border border-white/5 rounded px-3 py-2 flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${running ? 'bg-up' : 'bg-ink-500'}`} />
        <span className="text-[12px] text-ink-200">{running ? 'CALISIYOR' : 'DURDU'}</span>
        <span className="text-[10px] text-ink-400 num">Gen {optStatus?.generation ?? '-'} · {optStatus?.evaluated ?? 0} deg · Calmar {optStatus?.bestCalmar ?? 0}</span>
        <div className="ml-auto flex gap-1.5">
          <button onClick={startOptimizer} disabled={running} className="h-8 px-2.5 text-[11px] rounded bg-up/20 border border-up/40 text-up disabled:opacity-40">Baslat</button>
          <button onClick={stopOptimizer} disabled={!running} className="h-8 px-2.5 text-[11px] rounded bg-down/20 border border-down/40 text-down disabled:opacity-40">Dur</button>
        </div>
      </div>
      {optStatus?.currentName && <div className="text-[10px] text-ink-500 num truncate">→ {optStatus.currentName}</div>}

      <div className="space-y-1">
        {optResults.length === 0 ? (
          <p className="text-center text-ink-500 text-[12px] py-8">Henuz sonuc yok. "Baslat"a bas.</p>
        ) : optResults.map((r, i) => (
          <button key={r.id} onClick={() => setSel(sel?.id === r.id ? null : r)} className="w-full text-left bg-ink-850 border border-white/5 rounded px-2.5 py-1.5">
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-ink-500 w-5">{i + 1}</span>
              <span className="text-ink-100 flex-1 truncate">{r.strategy_name}</span>
              <span className="num text-up w-12 text-right font-medium">{r.calmar.toFixed(2)}</span>
            </div>
            <div className="flex items-center justify-between text-[10px] text-ink-400 mt-0.5">
              <span>T {r.trades} · %{r.win_rate.toFixed(0)}</span>
              <span className={`num ${cl(r.total_pnl)}`}>{formatUsd(r.total_pnl)}</span>
              <span className="text-warn num">-{r.max_drawdown.toFixed(1)}%</span>
              <span className="num">PF {r.profit_factor.toFixed(2)}</span>
            </div>
            {sel?.id === r.id && cfg && (
              <div className="mt-1 pt-1 border-t border-white/5 text-[9px] text-ink-500">
                {cfg.signalSource} · lev {cfg.leverage}x · TP {Number(cfg.tpPercent).toFixed(1)}/SL {Number(cfg.slPercent).toFixed(1)} · minS {Number(cfg.longMinScore).toFixed(1)} · {(cfg.enabledRules?.length ?? 0)} kural
              </div>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function MobileBacktest() {
  const [tab, setTab] = useState<'manual' | 'optimizer'>('manual');
  return (
    <div>
      <div className="sticky top-0 z-10 flex gap-1 px-3 py-2 bg-ink-900 border-b border-white/5">
        <button onClick={() => setTab('manual')} className={`flex-1 h-9 rounded text-[12px] border ${tab === 'manual' ? 'bg-up/15 border-up/40 text-up' : 'bg-ink-800 border-white/5 text-ink-300'}`}>Manuel</button>
        <button onClick={() => setTab('optimizer')} className={`flex-1 h-9 rounded text-[12px] border ${tab === 'optimizer' ? 'bg-up/15 border-up/40 text-up' : 'bg-ink-800 border-white/5 text-ink-300'}`}>Optimizer</button>
      </div>
      {tab === 'manual' ? <ManualTab /> : <OptimizerTab />}
    </div>
  );
}
