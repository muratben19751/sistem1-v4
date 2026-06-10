import { useEffect, useState } from 'react';
import { useAccountStore } from '../../store/account-store';
import { useUiStore } from '../../store/ui-store';
import { formatUsd } from '../../lib/formatters';

function istanbulNow() {
  return new Date().toLocaleTimeString('en-GB', { timeZone: 'Europe/Istanbul', hour12: false });
}

export default function Header() {
  const { accounts, activeAccountId } = useAccountStore();
  const wsLatency = useUiStore((s) => s.wsLatency);
  const botStatuses = useUiStore((s) => s.botStatuses);
  const account = accounts.find((a) => a.id === activeAccountId);
  const [clock, setClock] = useState(istanbulNow);

  useEffect(() => {
    const id = setInterval(() => setClock(istanbulNow()), 1000);
    return () => clearInterval(id);
  }, []);

  const isAll = activeAccountId === null;
  const botStatus = !isAll ? botStatuses[activeAccountId || 0] : null;
  const isRunning = botStatus?.status === 'running';
  const pnl = isAll ? accounts.reduce((s, a) => s + (a.total_pnl || 0), 0) : (account?.total_pnl ?? 0);
  const pnlUp = pnl >= 0;
  const equity = isAll
    ? accounts.reduce((s, a) => s + (a.account_equity ?? a.wallet_balance ?? a.balance ?? 0), 0)
    : (account?.account_equity ?? account?.wallet_balance ?? account?.balance ?? 0);

  let dd: number;
  if (isAll) {
    const peak = accounts.reduce(
      (s, a) => s + Math.max(a.peak_equity ?? 0, a.initial_balance ?? 0, a.account_equity ?? a.wallet_balance ?? a.balance ?? 0),
      0,
    );
    dd = peak > 0 ? Math.max(0, ((peak - equity) / peak) * 100) : 0;
  } else {
    dd = account?.current_drawdown ?? 0;
  }
  const ddColor = dd >= 5 ? 'text-down' : dd >= 2 ? 'text-warn' : dd > 0 ? 'text-ink-300' : 'text-ink-500';

  return (
    <header className="h-10 bg-[#471c0b] border-b-2 border-orange-500/50 sticky top-0 z-30 flex items-center select-none">

      <div className="w-[212px] shrink-0 flex items-center px-3 border-r border-white/5">
        <div className="flex items-center gap-1.5 bg-white rounded px-2 py-0.5 leading-none">
          <span className="text-[12px] font-extrabold text-red-600 tracking-wide">PYTHON</span>
          <span className="text-[11px] font-semibold text-red-600">Sistem1</span>
        </div>
      </div>

      <div className="flex items-center gap-2 px-3 border-r border-white/5 shrink-0">
        <span className="text-[11px] text-ink-200 num">
          {isAll ? 'ALL' : (account?.name ?? '---')}
        </span>
        {isRunning && (
          <span className="flex items-center gap-1 bg-up/10 text-up text-[9px] font-semibold tracking-[0.25em] px-1.5 py-0.5 rounded">
            <span className="w-1.5 h-1.5 rounded-full bg-up pulse-dot" />
            LIVE
          </span>
        )}
      </div>

      <div className="flex-1" />

      <div className="flex items-center gap-3 px-3 shrink-0 border-l border-white/5">
        <div className="flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full ${wsLatency > 0 ? 'bg-up pulse-dot' : 'bg-ink-500'}`} />
          <span className="text-[9px] text-ink-400 tracking-[0.25em]">WS</span>
          <span className="text-[11px] text-ink-300 num">{wsLatency > 0 ? `${wsLatency}ms` : '--'}</span>
        </div>

        <div className="h-3 w-px bg-white/5" />

        <div className="flex items-center gap-1">
          <span className="text-[9px] text-ink-400 tracking-[0.25em]">P/L</span>
          <span className={`text-[11px] num ${pnlUp ? 'text-up' : 'text-down'}`}>
            {pnlUp ? '+' : ''}{formatUsd(pnl)}
          </span>
        </div>

        <div className="h-3 w-px bg-white/5" />

        <div className="flex items-center gap-1">
          <span className="text-[9px] text-ink-400 tracking-[0.25em]">EQ</span>
          <span className="text-[11px] text-ink-100 num">
            {formatUsd(equity)}
          </span>
        </div>

        <div className="h-3 w-px bg-white/5" />

        <div className="flex items-center gap-1" title={isAll ? 'Tum hesaplarin peak-to-current toplam dusus' : `${account?.name ?? ''} peak-to-current dusus`}>
          <span className="text-[9px] text-ink-400 tracking-[0.25em]">DD</span>
          <span className={`text-[11px] num ${ddColor}`}>
            {dd > 0 ? '-' : ''}{dd.toFixed(2)}%
          </span>
        </div>

        <div className="h-3 w-px bg-white/5" />

        <span className="text-[11px] text-ink-300 num">{clock}<span className="text-[9px] text-ink-500 ml-0.5 tracking-[0.25em]">IST</span></span>

      </div>
    </header>
  );
}
