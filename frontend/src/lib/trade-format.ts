import { ruleLabel } from './rule-labels';

const MANUAL_REASONS = new Set(['manual', 'manual_suggested', 'manual_order']);

export function isManualTrade(entryReason: string | null | undefined): boolean {
  return entryReason != null && MANUAL_REASONS.has(entryReason);
}

export function fmtScore(score: number): string {
  const s = Number.isInteger(score) ? String(score) : score.toFixed(2);
  return score > 0 ? `+${s}` : s;
}

export function parseActiveRules(activeRules: string | null): Array<{ key: string; score: number | null }> {
  if (!activeRules) return [];
  return activeRules
    .split(',')
    .filter(Boolean)
    .map((item) => {
      const idx = item.indexOf(':');
      const key = idx >= 0 ? item.slice(0, idx) : item;
      const scoreStr = idx >= 0 ? item.slice(idx + 1) : '';
      const score = scoreStr !== '' && !Number.isNaN(Number(scoreStr)) ? Number(scoreStr) : null;
      return { key, score };
    })
    .sort((a, b) => Math.abs(b.score ?? 0) - Math.abs(a.score ?? 0));
}

export function formatSignal(t: { entry_reason: string | null; active_rules: string | null; side: string; trigger_source?: string | null }): string {
  const dir = t.side === 'long' ? 'UP' : 'DOWN';
  if (isManualTrade(t.entry_reason)) return `MANUEL ${dir}`;
  const src = (t.trigger_source || t.entry_reason || '').toUpperCase();
  const rules = t.active_rules?.split(',').map((s) => s.split(':')[0]).filter(Boolean) || [];
  const topRule = rules[0] ? ruleLabel(rules[0]) : '';
  if (src) return topRule ? `${src} / ${topRule} ${dir}` : `${src} ${dir}`;
  return topRule ? `${topRule} ${dir}` : `${dir}`;
}

export function formatCloseReason(reason: string | null): { text: string; color: string } {
  if (!reason) return { text: '-', color: 'text-ink-500' };
  const r = reason.toLowerCase();
  if (r.includes('tp') || r.includes('take_profit')) return { text: 'TP HIT', color: 'text-up' };
  if (r.includes('sl') || r.includes('stop_loss')) return { text: 'SL HIT', color: 'text-down' };
  if (r.includes('trail')) return { text: 'TRAILING', color: 'text-up' };
  if (r.includes('kill') || r.includes('manual')) return { text: 'MANUAL', color: 'text-warn' };
  if (r.includes('circuit')) return { text: 'CIRCUIT', color: 'text-down' };
  return { text: reason.toUpperCase().slice(0, 10), color: 'text-ink-400' };
}

export function formatTriggerSource(source: string | null | undefined): string {
  if (!source) return '-';
  return source.toUpperCase();
}

export function timeOnly(dateStr: string | null): string {
  if (!dateStr) return '-';
  const utc = dateStr.endsWith('Z') ? dateStr : dateStr + 'Z';
  return new Date(utc).toLocaleTimeString('en-GB', { timeZone: 'Europe/Istanbul', hour: '2-digit', minute: '2-digit' });
}

export function dateKey(dateStr: string | null): string {
  if (!dateStr) return 'unknown';
  const utc = dateStr.endsWith('Z') ? dateStr : dateStr + 'Z';
  return new Date(utc).toLocaleDateString('en-GB', { timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit' });
}

export function formatAge(openedAt: string): string {
  const iso = openedAt.includes('T') ? openedAt : openedAt.replace(' ', 'T');
  const utc = iso.endsWith('Z') ? iso : iso + 'Z';
  const ms = Date.now() - new Date(utc).getTime();
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

export function riskProgress(p: { entry_price: number; mark_price: number | null; sl_price: number | null; tp_price: number | null; side: string }): { pct: number; color: string } {
  const mark = p.mark_price ?? p.entry_price;
  if (!p.sl_price || !p.tp_price) return { pct: 50, color: 'bg-ink-400' };
  const totalRange = Math.abs(p.tp_price - p.sl_price);
  if (totalRange === 0) return { pct: 50, color: 'bg-ink-400' };
  const fromSl = p.side === 'long' ? mark - p.sl_price : p.sl_price - mark;
  const raw = (fromSl / totalRange) * 100;
  const clamped = Math.max(0, Math.min(100, raw));
  const color = clamped < 25 ? 'bg-down' : clamped > 65 ? 'bg-up' : 'bg-warn';
  return { pct: clamped, color };
}
