const TOKEN_MAP: Record<string, string[]> = {
  hammer: ['hammer'],
  sniper: ['4s_sniper', 'sniper'],
  fr: ['fr'],
  m1_a: ['m1_a'],
  scanner: ['scanner'],
};

const ALL = ['hammer', '4s_sniper', 'sniper', 'fr', 'm1_a', 'scanner'];

export function botSourceTypes(signalSource?: string | null): string[] {
  if (!signalSource) return [];
  if (signalSource === 'all') return ALL;
  const set = new Set<string>();
  for (const part of signalSource.split('+')) {
    for (const s of TOKEN_MAP[part.trim()] || []) set.add(s);
  }
  return [...set];
}

export const SOURCE_META: Record<string, { label: string; color: string }> = {
  hammer: { label: 'HAMMER', color: '#f59e0b' },
  '4s_sniper': { label: 'SNIPER', color: '#38bdf8' },
  sniper: { label: 'SNIPER', color: '#38bdf8' },
  fr: { label: 'FR', color: '#34d399' },
  m1_a: { label: 'M1-A', color: '#a78bfa' },
  scanner: { label: 'SCANNER', color: '#9ca3af' },
  unknown: { label: 'ALERT', color: '#6b7280' },
};

export function sourceMeta(st: string) {
  return SOURCE_META[st] || SOURCE_META.unknown;
}

export const STRIP_LANES = ['hammer', '4s_sniper', 'fr', 'm1_a'];
