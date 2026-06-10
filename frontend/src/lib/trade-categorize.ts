export type TradeCategory = 'scalp' | 'swing' | 'manual';

interface CategorizableTrade {
  status?: string;
  pnl?: number | null;
  entry_reason?: string | null;
  duration_seconds?: number | null;
}

const MANUAL_REASONS = new Set(['manual', 'manual_suggested', 'manual_order']);
const SCALP_MAX_SECONDS = 4 * 3600;

export function categorizeTrade(t: CategorizableTrade): TradeCategory {
  if (t.entry_reason && MANUAL_REASONS.has(t.entry_reason)) return 'manual';
  const dur = t.duration_seconds ?? 0;
  return dur < SCALP_MAX_SECONDS ? 'scalp' : 'swing';
}

export interface CategoryStats {
  total: number;
  wins: number;
  winRate: number;
  totalPnl: number;
}

export interface WinRateBreakdown {
  scalp: CategoryStats;
  swing: CategoryStats;
  manual: CategoryStats;
}

function emptyStats(): CategoryStats {
  return { total: 0, wins: 0, winRate: 0, totalPnl: 0 };
}

export function winRateBreakdown(trades: CategorizableTrade[]): WinRateBreakdown {
  const buckets: WinRateBreakdown = {
    scalp: emptyStats(),
    swing: emptyStats(),
    manual: emptyStats(),
  };
  for (const t of trades) {
    if (t.status !== 'closed' || t.pnl === null || t.pnl === undefined) continue;
    const cat = categorizeTrade(t);
    const bucket = buckets[cat];
    bucket.total += 1;
    bucket.totalPnl += t.pnl;
    if (t.pnl > 0) bucket.wins += 1;
  }
  for (const cat of ['scalp', 'swing', 'manual'] as const) {
    const b = buckets[cat];
    b.winRate = b.total > 0 ? (b.wins / b.total) * 100 : 0;
  }
  return buckets;
}

export const CATEGORY_LABELS: Record<TradeCategory, string> = {
  scalp: 'SCALP',
  swing: 'SWING',
  manual: 'MANUEL',
};

export const CATEGORY_COLORS: Record<TradeCategory, string> = {
  scalp: 'text-info',
  swing: 'text-purple-400',
  manual: 'text-amber-400',
};
