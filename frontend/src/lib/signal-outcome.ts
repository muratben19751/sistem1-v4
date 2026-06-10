import type { Kline } from '../types';

export type Outcome = 'TP' | 'SL' | 'PENDING';

export interface OutcomeResult {
  outcome: Outcome;
  bars: number;
}

export function signalOutcome(
  klines: Kline[],
  alertTimeSec: number,
  direction: string,
  entry: number,
  tpPctPrice: number,
  slPctPrice: number,
): OutcomeResult {
  if (!entry || entry <= 0) return { outcome: 'PENDING', bars: 0 };
  const up = direction === 'UP';
  const tp = up ? entry * (1 + tpPctPrice / 100) : entry * (1 - tpPctPrice / 100);
  const sl = up ? entry * (1 - slPctPrice / 100) : entry * (1 + slPctPrice / 100);

  let bars = 0;
  for (const k of klines) {
    if (k.time <= alertTimeSec) continue;
    bars++;
    if (up) {
      if (k.low <= sl) return { outcome: 'SL', bars };
      if (k.high >= tp) return { outcome: 'TP', bars };
    } else {
      if (k.high >= sl) return { outcome: 'SL', bars };
      if (k.low <= tp) return { outcome: 'TP', bars };
    }
  }
  return { outcome: 'PENDING', bars };
}

export function entryForAlert(klines: Kline[], alertTimeSec: number, alertPrice: number | null): number {
  if (alertPrice && alertPrice > 0) return alertPrice;
  for (const k of klines) {
    if (k.time >= alertTimeSec) return k.close;
  }
  return 0;
}
