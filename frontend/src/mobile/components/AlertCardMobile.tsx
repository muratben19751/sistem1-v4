import type { Alert } from '../../store/alert-store';
import { formatPrice } from '../../lib/formatters';

function borderColor(sourceType: string): string {
  if (sourceType === 'hammer') return 'border-l-warn';
  if (sourceType === '4s_sniper') return 'border-l-info';
  if (sourceType === 'fr') return 'border-l-emerald-400';
  if (sourceType === 'm1_a') return 'border-l-purple-400';
  return 'border-l-ink-500';
}

function sourceLabel(a: Alert): { text: string; color: string } {
  if (a.source_type === 'hammer') return { text: 'HAMMER', color: 'text-warn' };
  if (a.source_type === '4s_sniper') return { text: a.signal_type && a.signal_type !== 'UNKNOWN' ? `SNIPER ${a.signal_type}` : 'SNIPER', color: 'text-info' };
  if (a.source_type === 'fr') return { text: a.funding_changed === 1 ? 'FR CHANGED' : 'FR', color: 'text-emerald-400' };
  if (a.source_type === 'm1_a') return { text: 'M1-A', color: 'text-purple-400' };
  return { text: a.source_type.toUpperCase(), color: 'text-ink-300' };
}

function ago(createdAt: string): string {
  const iso = createdAt.includes('T') ? createdAt : createdAt.replace(' ', 'T');
  const utc = iso.endsWith('Z') ? iso : iso + 'Z';
  const s = Math.max(0, Math.floor((Date.now() - new Date(utc).getTime()) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}d`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}s`;
  return `${Math.floor(h / 24)}g`;
}

export default function AlertCardMobile({ a }: { a: Alert }) {
  const label = sourceLabel(a);
  const isUp = a.direction === 'UP';

  return (
    <div className={`rounded-md border border-white/5 border-l-2 ${borderColor(a.source_type)} bg-ink-850 px-3 py-2.5`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-semibold text-ink-50 truncate">{a.symbol}</span>
          <span className={`text-xs font-medium ${isUp ? 'text-up' : 'text-down'}`}>{a.direction}</span>
          {a.matched_with_bot === 1 && (
            <span className="text-[9px] text-up border border-up/30 bg-up/10 rounded px-1 py-0.5">MATCHED</span>
          )}
        </div>
        <span className="text-[10px] text-ink-500 num shrink-0">{ago(a.created_at)}</span>
      </div>
      <div className="mt-1 flex items-center justify-between text-[11px]">
        <span className={label.color}>{label.text}</span>
        <span className="text-ink-300 num">
          {a.price != null && <>{formatPrice(a.price)}</>}
          {a.source_type === 'fr' && a.funding_rate != null && (
            <span className={`ml-2 ${a.funding_rate >= 0 ? 'text-up' : 'text-down'}`}>
              {a.funding_rate >= 0 ? '+' : ''}{a.funding_rate.toFixed(4)}
            </span>
          )}
        </span>
      </div>
    </div>
  );
}
