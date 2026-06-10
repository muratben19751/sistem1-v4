interface PositionMathInput {
  entry_price: number;
  mark_price?: number | null;
  size: number;
  leverage: number;
  unrealized_pnl?: number | null;
}

export function positionEntryValue(p: PositionMathInput): number {
  return p.entry_price * p.size;
}

export function positionMarkValue(p: PositionMathInput): number {
  return p.size * (p.mark_price ?? p.entry_price);
}

export function positionMargin(p: PositionMathInput): number {
  const leverage = Number.isFinite(p.leverage) && p.leverage > 0 ? p.leverage : 1;
  return positionEntryValue(p) / leverage;
}

export function positionPnlPercent(p: PositionMathInput): number {
  const margin = positionMargin(p);
  if (margin <= 0) return 0;
  return ((p.unrealized_pnl || 0) / margin) * 100;
}

export function aggregatePositionPnlPercent(positions: PositionMathInput[]): number {
  const totalMargin = positions.reduce((sum, p) => sum + positionMargin(p), 0);
  if (totalMargin <= 0) return 0;
  const totalPnl = positions.reduce((sum, p) => sum + (p.unrealized_pnl || 0), 0);
  return (totalPnl / totalMargin) * 100;
}

interface SlDistanceInput {
  entry_price: number;
  mark_price?: number | null;
  sl_price?: number | null;
  side: string;
}

export function slDistancePct(p: SlDistanceInput): number | null {
  if (!p.sl_price || p.sl_price <= 0) return null;
  const mark = p.mark_price ?? p.entry_price;
  if (!mark || mark <= 0) return null;
  const diff = p.side === 'long' ? mark - p.sl_price : p.sl_price - mark;
  return (diff / mark) * 100;
}

export function slDistanceTone(distPct: number | null): string {
  if (distPct === null) return 'text-ink-500';
  if (distPct <= 0) return 'text-down font-semibold';
  if (distPct < 0.5) return 'text-down';
  if (distPct < 2) return 'text-warn';
  return 'text-up';
}
