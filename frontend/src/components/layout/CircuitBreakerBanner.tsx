import { AlertTriangle, X } from 'lucide-react';
import { useUiStore } from '../../store/ui-store';
import { useAccountStore } from '../../store/account-store';

export default function CircuitBreakerBanner() {
  const alerts = useUiStore((s) => s.circuitBreakers);
  const dismiss = useUiStore((s) => s.dismissCircuitBreaker);
  const accounts = useAccountStore((s) => s.accounts);

  if (alerts.length === 0) return null;

  return (
    <div className="flex flex-col">
      {alerts.map((a) => {
        const acc = accounts.find((x) => x.id === a.accountId);
        return (
          <div
            key={a.accountId}
            className="flex items-center gap-3 px-4 py-2 bg-down/20 border-b border-down/40 text-down"
          >
            <AlertTriangle size={14} className="shrink-0 blink" />
            <span className="text-[11px] font-semibold tracking-wide">CIRCUIT BREAKER</span>
            <span className="text-[11px]">
              {acc?.name || `Hesap #${a.accountId}`} - drawdown <span className="font-bold num">{a.drawdown.toFixed(2)}%</span>
              {' '}max limit asildi, bot DURAKLATILDI.
            </span>
            <button
              onClick={() => dismiss(a.accountId)}
              className="ml-auto text-down/70 hover:text-down transition-colors"
              title="Kapat"
            >
              <X size={14} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
