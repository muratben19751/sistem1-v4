export function formatUsd(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return '--';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatPercent(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return '--';
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

export function formatPrice(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return '--';
  if (value >= 1000) return value.toFixed(2);
  if (value >= 1) return value.toFixed(4);
  return value.toFixed(6);
}

export function parseServerDateMs(dateStr: string | null | undefined): number {
  if (!dateStr) return NaN;
  const iso = dateStr.includes('T') ? dateStr : dateStr.replace(' ', 'T');
  const utc = /Z$|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + 'Z';
  return new Date(utc).getTime();
}

export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '--';
  const iso = dateStr.includes('T') ? dateStr : dateStr.replace(' ', 'T');
  const utc = iso.endsWith('Z') ? iso : iso + 'Z';
  return new Date(utc).toLocaleString('tr-TR', { timeZone: 'Europe/Istanbul' });
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || isNaN(seconds)) return '--';
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
}
