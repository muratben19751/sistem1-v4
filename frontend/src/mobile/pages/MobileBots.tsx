import { useEffect } from 'react';
import { useAccountStore } from '../../store/account-store';
import { useUiStore, type BotStatus } from '../../store/ui-store';
import { api } from '../../lib/api';
import BotRow from '../components/BotRow';

export default function MobileBots() {
  const accounts = useAccountStore((s) => s.accounts);
  const setBotStatus = useUiStore((s) => s.setBotStatus);

  useEffect(() => {
    accounts.forEach((acc) => {
      api.get<BotStatus>(`/bot/status?accountId=${acc.id}`).then((s) => setBotStatus(acc.id, s)).catch(() => {});
    });
  }, [accounts, setBotStatus]);

  return (
    <div className="p-3 space-y-2">
      {accounts.length === 0 ? (
        <p className="text-center text-ink-500 text-sm py-12">Hesap yok</p>
      ) : (
        accounts.map((acc) => <BotRow key={acc.id} account={acc} />)
      )}
    </div>
  );
}
