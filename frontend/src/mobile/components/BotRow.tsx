import { useState } from 'react';
import { Play, Square } from 'lucide-react';
import { useAccountStore } from '../../store/account-store';
import { useUiStore, type BotStatus } from '../../store/ui-store';
import { api } from '../../lib/api';
import { formatUsd } from '../../lib/formatters';

function equityOf(a: { account_equity?: number; wallet_balance?: number; balance?: number }): number {
  return a.account_equity ?? a.wallet_balance ?? a.balance ?? 0;
}

interface Account {
  id: number;
  name: string;
  color: string;
  account_equity?: number;
  wallet_balance?: number;
  balance?: number;
}

export default function BotRow({ account }: { account: Account }) {
  const fetchAccounts = useAccountStore((s) => s.fetchAccounts);
  const status = useUiStore((s) => s.botStatuses[account.id]);
  const setBotStatus = useUiStore((s) => s.setBotStatus);
  const [toggling, setToggling] = useState(false);

  const isRunning = status?.status === 'running';

  const toggle = async () => {
    setToggling(true);
    try {
      const result = await api.post<BotStatus>(isRunning ? '/bot/stop' : '/bot/start', { accountId: account.id });
      setBotStatus(account.id, result);
      fetchAccounts();
    } catch {}
    setToggling(false);
  };

  return (
    <div className="flex items-center gap-3 rounded-md border border-white/5 bg-ink-850 px-3 py-2.5">
      <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${isRunning ? 'bg-up pulse-dot' : 'bg-down'}`} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: account.color || '#888' }} />
          <span className="text-sm font-medium text-ink-100 truncate">{account.name}</span>
        </div>
        <div className="text-[11px] text-ink-400 num mt-0.5">
          {formatUsd(equityOf(account))}
          {isRunning && status && (
            <span className="ml-2 text-ink-500">S:{status.totalScans} G:{status.totalSignals} O:{status.totalOrders}</span>
          )}
        </div>
      </div>
      <button
        onClick={toggle}
        disabled={toggling}
        className={`shrink-0 flex items-center gap-1.5 rounded px-4 min-h-[40px] text-xs font-medium border disabled:opacity-50 ${
          isRunning ? 'bg-down/15 border-down/30 text-down' : 'bg-up/15 border-up/30 text-up'
        }`}
      >
        {isRunning ? <Square size={12} /> : <Play size={12} />}
        {isRunning ? 'Durdur' : 'Başlat'}
      </button>
    </div>
  );
}
