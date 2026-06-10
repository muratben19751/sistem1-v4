import { X } from 'lucide-react';
import { useAccountStore } from '../../store/account-store';
import { formatUsd, formatPercent, formatPrice, formatDate, formatDuration } from '../../lib/formatters';
import { ruleLabel } from '../../lib/rule-labels';
import { categorizeTrade, CATEGORY_LABELS, CATEGORY_COLORS } from '../../lib/trade-categorize';

export interface MobileTrade {
  id: number;
  account_id: number;
  symbol: string;
  side: string;
  size: number;
  entry_price: number;
  exit_price: number | null;
  leverage: number;
  pnl: number | null;
  pnl_percent: number | null;
  fee: number;
  status: string;
  active_rules: string | null;
  signal_score: number | null;
  entry_reason: string | null;
  exit_reason: string | null;
  opened_at: string;
  closed_at: string | null;
  duration_seconds: number | null;
}

function closeReason(reason: string | null): { text: string; color: string } {
  if (!reason) return { text: '-', color: 'text-ink-400' };
  const r = reason.toLowerCase();
  if (r.includes('tp') || r.includes('take_profit')) return { text: 'TAKE PROFIT', color: 'text-up' };
  if (r.includes('sl') || r.includes('stop_loss')) return { text: 'STOP LOSS', color: 'text-down' };
  if (r.includes('trail')) return { text: 'TRAILING', color: 'text-up' };
  if (r.includes('manual') || r.includes('kill')) return { text: 'MANUEL', color: 'text-warn' };
  if (r.includes('circuit')) return { text: 'CIRCUIT', color: 'text-down' };
  return { text: reason.toUpperCase(), color: 'text-ink-300' };
}

function Field({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <div className="text-[10px] tracking-[0.15em] uppercase text-ink-500">{label}</div>
      <div className={`text-sm num ${tone || 'text-ink-100'}`}>{value}</div>
    </div>
  );
}

export default function TradeDetailSheet({ trade, onClose }: { trade: MobileTrade; onClose: () => void }) {
  const accounts = useAccountStore((s) => s.accounts);
  const acc = accounts.find((a) => a.id === trade.account_id);
  const pnl = trade.pnl || 0;
  const up = pnl >= 0;
  const isLong = trade.side === 'long';
  const cat = categorizeTrade(trade);
  const isManual = cat === 'manual';
  const reason = closeReason(trade.exit_reason);
  const notional = trade.entry_price * trade.size;

  const rules = (trade.active_rules || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .map((part) => {
      const [key, score] = part.split(':');
      return { key, score: Number(score) };
    });

  return (
    <div className="fixed inset-0 z-[120] flex items-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        className="relative w-full bg-ink-900 border-t border-white/10 rounded-t-2xl max-h-[88dvh] overflow-y-auto overscroll-contain pb-[env(safe-area-inset-bottom)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-ink-900 px-4 pt-3 pb-2 border-b border-white/5">
          <div className="mx-auto w-10 h-1 rounded-full bg-ink-600 mb-3" />
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-2 min-w-0">
              <span className={`inline-block w-1 h-8 rounded-full ${isLong ? 'bg-up' : 'bg-down'}`} />
              <div className="min-w-0">
                <div className="text-lg font-semibold text-ink-50 truncate">{trade.symbol}</div>
                <div className="flex items-center gap-1.5 text-[11px]">
                  <span className={isLong ? 'text-up' : 'text-down'}>{trade.side.toUpperCase()}</span>
                  <span className={`px-1 rounded border ${isManual ? 'border-warn/30 text-warn' : 'border-info/30 text-info'}`}>
                    {isManual ? 'MANUEL' : 'AUTO'}
                  </span>
                  <span className={CATEGORY_COLORS[cat]}>{CATEGORY_LABELS[cat]}</span>
                </div>
              </div>
            </div>
            <button onClick={onClose} className="shrink-0 text-ink-400 p-2 -mr-2 -mt-1">
              <X size={20} />
            </button>
          </div>
        </div>

        <div className="px-4 py-4 space-y-4">
          <div className="flex items-end justify-between">
            <div>
              <div className="text-[10px] tracking-[0.15em] uppercase text-ink-500">Kar / Zarar</div>
              <div className={`text-2xl font-bold num ${up ? 'text-up' : 'text-down'}`}>
                {up ? '+' : ''}{formatUsd(pnl)}
              </div>
              <div className={`text-sm num ${up ? 'text-up' : 'text-down'}`}>{formatPercent(trade.pnl_percent)}</div>
            </div>
            <div className="text-right">
              <div className="text-[10px] tracking-[0.15em] uppercase text-ink-500">Kapanış</div>
              <div className={`text-sm font-medium ${reason.color}`}>{reason.text}</div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-x-4 gap-y-3">
            <Field label="Giriş" value={formatPrice(trade.entry_price)} />
            <Field label="Çıkış" value={trade.exit_price ? formatPrice(trade.exit_price) : '-'} />
            <Field label="Kaldıraç" value={`${trade.leverage}x`} />
            <Field label="Büyüklük (notional)" value={formatUsd(notional)} />
            <Field label="Ücret" value={formatUsd(trade.fee)} tone={trade.fee > 0 ? 'text-down' : 'text-ink-100'} />
            <Field label="Skor" value={trade.signal_score != null ? trade.signal_score.toFixed(1) : '-'} />
            <Field label="Açılış" value={formatDate(trade.opened_at)} />
            <Field label="Kapanış" value={formatDate(trade.closed_at)} />
            <Field label="Süre" value={formatDuration(trade.duration_seconds)} />
            {acc && <Field label="Hesap" value={acc.name} />}
          </div>

          {rules.length > 0 && (
            <div>
              <div className="text-[10px] tracking-[0.15em] uppercase text-ink-500 mb-1.5">Aktif Kurallar</div>
              <div className="grid grid-cols-2 gap-1">
                {rules.map((r, i) => (
                  <div
                    key={`${r.key}-${i}`}
                    className={`flex justify-between px-2 py-1.5 text-[11px] rounded border ${
                      r.score > 0 ? 'bg-up/[0.05] border-up/10' : r.score < 0 ? 'bg-down/[0.05] border-down/10' : 'bg-ink-850 border-white/5'
                    }`}
                  >
                    <span className="text-ink-400 truncate mr-2">{ruleLabel(r.key)}</span>
                    <span className={`num font-medium shrink-0 ${r.score > 0 ? 'text-up' : r.score < 0 ? 'text-down' : 'text-ink-500'}`}>
                      {Number.isFinite(r.score) ? (r.score > 0 ? '+' : '') + r.score : '-'}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
