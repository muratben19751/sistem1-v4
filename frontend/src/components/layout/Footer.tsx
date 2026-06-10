import { useEffect, useState } from 'react';
import { useUiStore } from '../../store/ui-store';
import { useAccountStore } from '../../store/account-store';

interface ServiceHealth {
  name: string;
  current: 'up' | 'down';
  uptime24h: number;
  lastSeen: string | null;
  hourly?: boolean[];
  lastDown?: string | null;
  note?: string;
}

function parseTs(ts: string): number {
  let str = ts.includes('T') ? ts : ts.replace(' ', 'T');
  if (!/Z$|[+-]\d{2}:?\d{2}$/.test(str)) str += 'Z';
  return new Date(str).getTime();
}

function formatAge(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '';
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s`;
  if (ms < 3600_000) return `${Math.floor(ms / 60_000)}m`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3600_000)}h`;
  return `${Math.floor(ms / 86_400_000)}d`;
}

function UptimeBar({ hourly }: { hourly: boolean[] }) {
  return (
    <div className="flex items-center gap-[1px]">
      {hourly.map((up, i) => {
        const hoursAgo = 23 - i;
        const label = hoursAgo === 0 ? 'şu an' : `${hoursAgo} saat önce`;
        return (
          <span
            key={i}
            title={`${label}: ${up ? 'up' : 'down'}`}
            className={`w-[3px] h-[10px] rounded-[1px] ${up ? 'bg-up' : 'bg-down'}`}
          />
        );
      })}
    </div>
  );
}

function useServiceHealth(): ServiceHealth[] {
  const [services, setServices] = useState<ServiceHealth[]>([]);
  useEffect(() => {
    const load = async () => {
      try {
        const r = await fetch('/api/health/services', { credentials: 'same-origin' });
        if (!r.ok) return;
        const d = await r.json();
        if (Array.isArray(d?.services)) setServices(d.services);
      } catch {}
    };
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, []);
  return services;
}

function ServiceBox({ s }: { s: ServiceHealth }) {
  const up = s.current === 'up';
  const colorBar = up ? 'bg-up' : 'bg-down';
  const colorText = up ? 'text-up' : 'text-down';
  const ago = s.lastSeen ? formatAge(Date.now() - parseTs(s.lastSeen)) : '';
  const downAgo = s.lastDown ? formatAge(Date.now() - parseTs(s.lastDown)) : '';
  const borderClass = up ? 'border-up/50 bg-up/5' : 'border-down/50 bg-down/5';
  const subText = up ? 'text-up/80' : 'text-down/80';
  const hourly = s.hourly && s.hourly.length === 24 ? s.hourly : Array(24).fill(true);
  return (
    <div className={`flex items-center justify-center gap-1.5 px-2 py-1 border rounded ${borderClass}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${colorBar} ${up ? 'shadow-[0_0_6px] shadow-up/60' : ''}`} />
      <span className={`text-[9px] tracking-wide uppercase font-semibold ${colorText}`}>{s.name}</span>
      <span className={`text-[10px] font-mono font-bold ${colorText}`}>{s.uptime24h.toFixed(1)}%</span>
      <UptimeBar hourly={hourly} />
      <span className={`text-[8px] font-mono ${subText}`}>
        {s.note ? s.note : downAgo ? `son↓${downAgo}` : ago ? ago : '—'}
      </span>
    </div>
  );
}

export default function Footer() {
  const { activeAccountId, accounts } = useAccountStore();
  const isAll = activeAccountId === null;
  const account = accounts.find((a) => a.id === activeAccountId);
  const botStatuses = useUiStore((s) => s.botStatuses);
  const allLogs = useUiStore((s) => s.botLogs);
  const exchangeStatus = useUiStore((s) => s.exchangeStatus);
  const services = useServiceHealth();

  const aid = activeAccountId || 0;
  const botStatus = !isAll ? botStatuses[aid] : null;
  const logs = !isAll ? allLogs[aid] : null;

  const totalEvents = isAll
    ? Object.values(botStatuses).reduce((s, b) => s + (b?.totalScans || 0) + (b?.totalSignals || 0) + (b?.totalOrders || 0), 0)
    : (botStatus?.totalScans || 0) + (botStatus?.totalSignals || 0) + (botStatus?.totalOrders || 0);
  const messageCount = isAll
    ? Object.values(allLogs).reduce((s, l) => s + (l?.length || 0), 0)
    : (logs?.length || 0);

  const maxDd = account?.max_drawdown || 30;
  const ddEnabled = !!account?.max_drawdown_enabled;
  const currentEquity = account?.account_equity ?? account?.wallet_balance;
  const currentDd = currentEquity && account?.initial_balance
    ? Math.max(0, ((account.initial_balance - currentEquity) / account.initial_balance) * 100)
    : 0;
  const ddRatio = ddEnabled && maxDd > 0 ? currentDd / maxDd : 0;

  let riskLabel = isAll ? 'ALL' : 'OFF';
  let riskClass = 'bg-ink-700 text-ink-400 border-white/10';
  if (!isAll && botStatus?.status === 'running') {
    if (ddRatio < 0.5) { riskLabel = 'SAFE'; riskClass = 'bg-up/10 text-up border-up/30'; }
    else if (ddRatio < 0.8) { riskLabel = 'WARN'; riskClass = 'bg-warn/10 text-warn border-warn/30'; }
    else { riskLabel = 'DANGER'; riskClass = 'bg-down/10 text-down border-down/30'; }
  }

  return (
    <footer className="bg-ink-900 border-t border-white/5 flex flex-col">
      <div className="h-7 flex items-center justify-between px-4">
        <div className="text-[9px] text-ink-400 tracking-widest flex items-center gap-4">
          <span>sistem1 · build 1.0.0</span>
          <span className="flex items-center gap-1">
            <span className={`w-1.5 h-1.5 rounded-full ${exchangeStatus === 'ok' ? 'bg-up' : exchangeStatus === 'error' ? 'bg-down' : 'bg-ink-500'}`} />
            bybit {exchangeStatus}
          </span>
          <span>events {totalEvents}</span>
        </div>
        <div className="text-[9px] text-ink-400 flex items-center gap-4"></div>
      </div>
      {services.length > 0 && (
        <div className="border-t border-white/5 bg-ink-850/40 py-1.5 pl-[212px]">
          <div className="flex justify-center gap-2">
            {services.map((s) => (
              <ServiceBox key={s.name} s={s} />
            ))}
          </div>
        </div>
      )}
    </footer>
  );
}
