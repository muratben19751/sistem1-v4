import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronDown, Monitor, Bell } from 'lucide-react';
import { useAccountStore } from '../../store/account-store';
import { useUiStore } from '../../store/ui-store';
import { formatUsd } from '../../lib/formatters';
import { clearForceDesktop, setForceDesktop } from '../forceDesktop';

function equityOf(a: { account_equity?: number; wallet_balance?: number; balance?: number }): number {
  return a.account_equity ?? a.wallet_balance ?? a.balance ?? 0;
}

export default function MobileTopBar({ onOpenAlerts, alertUnread = 0 }: { onOpenAlerts?: () => void; alertUnread?: number }) {
  const navigate = useNavigate();
  const { accounts, activeAccountId, setActiveAccount } = useAccountStore();
  const wsLatency = useUiStore((s) => s.wsLatency);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const active = accounts.find((a) => a.id === activeAccountId);
  const isAll = activeAccountId === null;
  const equity = isAll
    ? accounts.reduce((s, a) => s + equityOf(a), 0)
    : equityOf(active ?? {});

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  const pick = (id: number | null) => {
    setActiveAccount(id);
    setOpen(false);
  };

  const goDesktop = () => {
    setForceDesktop();
    navigate('/');
  };

  // Mobil gorunume kilitlenmeyi temizle (kullanici mobil sekmede gezerken).
  useEffect(() => { clearForceDesktop(); }, []);

  const latColor = wsLatency === 0 ? 'bg-ink-500' : wsLatency < 200 ? 'bg-up' : wsLatency < 600 ? 'bg-warn' : 'bg-down';

  return (
    <header className="shrink-0 bg-ink-900 border-b-2 border-demo/50 px-3 pt-3 pb-2">
      <div className="flex items-center justify-between">
        <div className="relative flex-1 min-w-0" ref={ref}>
          <button
            onClick={() => setOpen(!open)}
            className="flex items-center gap-2 min-w-0 text-left"
          >
            <span className="relative flex h-2.5 w-2.5 shrink-0">
              {!isAll && <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-up opacity-60" />}
              <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${isAll ? 'bg-ink-300' : 'bg-up'}`} />
            </span>
            <span className="text-sm font-semibold text-ink-50 truncate">
              {isAll ? 'Tüm Hesaplar' : (active?.name ?? 'Hesap yok')}
            </span>
            <ChevronDown size={16} className={`text-ink-400 shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
          </button>
          {open && accounts.length > 0 && (
            <div className="absolute z-50 mt-2 left-0 right-0 bg-ink-800 border border-white/10 rounded shadow-xl max-h-72 overflow-y-auto">
              <button
                onClick={() => pick(null)}
                className={`w-full text-left flex items-center gap-2 px-3 min-h-[44px] text-sm border-b border-white/5 ${isAll ? 'text-up bg-up/5' : 'text-ink-200'}`}
              >
                <span className="w-2 h-2 rounded-full bg-ink-300" />
                Tüm Hesaplar
              </button>
              {accounts.map((acc) => (
                <button
                  key={acc.id}
                  onClick={() => pick(acc.id)}
                  className={`w-full text-left flex items-center gap-2 px-3 min-h-[44px] text-sm ${acc.id === activeAccountId ? 'text-up bg-up/5' : 'text-ink-200'}`}
                >
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: acc.color || '#3ddc97' }} />
                  <span className="truncate">{acc.name}</span>
                  <span className="ml-auto text-xs text-ink-400">{formatUsd(equityOf(acc))}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        <span className="ml-2 shrink-0 text-[10px] font-bold tracking-[0.2em] text-demo border border-demo/40 bg-demo/10 rounded px-1.5 py-0.5">
          DEMO
        </span>
        <button
          onClick={onOpenAlerts}
          aria-label="Alertleri ac"
          className="ml-2 shrink-0 relative flex items-center justify-center text-ink-300 border border-white/10 rounded px-2 min-h-[36px] active:bg-white/5"
        >
          <Bell size={16} />
          {alertUnread > 0 && (
            <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full bg-demo text-[9px] font-bold text-black flex items-center justify-center">
              {alertUnread > 99 ? '99+' : alertUnread}
            </span>
          )}
        </button>
        <button
          onClick={goDesktop}
          className="ml-2 shrink-0 flex items-center gap-1 text-xs text-ink-400 border border-white/10 rounded px-2 min-h-[36px] active:bg-white/5"
        >
          <Monitor size={13} /> Masaüstü
        </button>
      </div>
      <div className="mt-1.5 flex items-end justify-between">
        <div>
          <div className="text-[10px] tracking-[0.2em] uppercase text-ink-500">Net Likidite</div>
          <div className="text-2xl font-bold text-ink-50 num leading-tight">{formatUsd(equity)}</div>
        </div>
        <div className="flex items-center gap-1.5 text-[10px] text-ink-500 num">
          <span className={`w-1.5 h-1.5 rounded-full ${latColor}`} />
          {wsLatency > 0 ? `${wsLatency}ms` : 'bağlanıyor'}
        </div>
      </div>
    </header>
  );
}
