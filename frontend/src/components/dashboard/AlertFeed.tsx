import { useEffect, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAlertStore, type Alert } from '../../store/alert-store';
import { wsClient } from '../../lib/ws';
import { api } from '../../lib/api';
import { Star } from 'lucide-react';

type SourceKey = 'sniper' | 'hammer' | 'fr' | 'm1_a';
type ChannelStatus = 'active' | 'stale' | 'parse_error' | 'no_data' | 'disabled';

interface ChannelHealth {
  source_type: string;
  label: string;
  configured: boolean;
  status: ChannelStatus;
  last_message_at: string | null;
  last_parsed_at: string | null;
  last_unparsed_at: string | null;
  messages_24h: number;
  parsed_24h: number;
  unparsed_24h: number;
  parse_fail_rate_24h: number;
  stale_minutes: number;
  note: string;
}

const ALL_SOURCES: SourceKey[] = ['sniper', 'hammer', 'fr', 'm1_a'];
const DEFAULT_SOURCES: SourceKey[] = ['sniper', 'hammer', 'fr'];
const STORAGE_KEY = 'alertFeed.activeSources';

const SOURCE_TO_DB: Record<SourceKey, string> = {
  sniper: '4s_sniper',
  hammer: 'hammer',
  fr: 'fr',
  m1_a: 'm1_a',
};

function loadActiveSources(): Set<SourceKey> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const arr = JSON.parse(raw) as string[];
      const valid = arr.filter((k): k is SourceKey => (ALL_SOURCES as string[]).includes(k));
      if (valid.length > 0) return new Set(valid);
    }
  } catch {}
  return new Set(DEFAULT_SOURCES);
}

function parseJsonSafe(str: string | null): Record<string, number> {
  if (!str) return {};
  try { return JSON.parse(str); } catch { return {}; }
}

function isRsiExtreme(v: number): boolean {
  return v <= 30 || v >= 70;
}

function isSrsiExtreme(v: number): boolean {
  return v <= 10 || v >= 90;
}

function borderColor(sourceType: string): string {
  if (sourceType === 'hammer') return 'border-l-warn';
  if (sourceType === '4s_sniper') return 'border-l-info';
  if (sourceType === 'fr') return 'border-l-emerald-400';
  if (sourceType === 'm1_a') return 'border-l-purple-400';
  return 'border-l-ink-500';
}

function sourceLabel(a: Alert): { text: string; color: string } {
  if (a.source_type === 'hammer') {
    return { text: `HAMMER · ${a.direction}`, color: 'text-warn' };
  }
  if (a.source_type === '4s_sniper') {
    const sig = a.signal_type && a.signal_type !== 'UNKNOWN' ? a.signal_type : '';
    return { text: `SNIPER · ${sig ? sig + ' ' : ''}${a.direction}`, color: 'text-info' };
  }
  if (a.source_type === 'fr') {
    const changed = a.funding_changed === 1 ? ' CHANGED' : '';
    return { text: `FR${changed} · ${a.direction}`, color: 'text-emerald-400' };
  }
  if (a.source_type === 'm1_a') {
    return { text: `M1-A · ${a.direction}`, color: 'text-purple-400' };
  }
  return { text: `ALERT · ${a.direction}`, color: 'text-ink-400' };
}

function formatTime(dateStr: string): string {
  const utc = dateStr.endsWith('Z') ? dateStr : dateStr + 'Z';
  return new Date(utc).toLocaleTimeString('en-GB', { timeZone: 'Europe/Istanbul', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function parseTimeMs(dateStr: string | null): number | null {
  if (!dateStr) return null;
  let value = dateStr.includes('T') ? dateStr : dateStr.replace(' ', 'T');
  if (!/Z$|[+-]\d{2}:?\d{2}$/.test(value)) value += 'Z';
  const ms = new Date(value).getTime();
  return Number.isFinite(ms) ? ms : null;
}

function formatAge(dateStr: string | null): string {
  const ms = parseTimeMs(dateStr);
  if (ms === null) return '--';
  const diff = Math.max(0, Date.now() - ms);
  if (diff < 60_000) return `${Math.floor(diff / 1000)}s`;
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)}m`;
  return `${Math.floor(diff / 3600_000)}h`;
}

function healthTone(status: ChannelStatus): string {
  if (status === 'active') return 'bg-up shadow-up/60';
  if (status === 'stale' || status === 'no_data') return 'bg-warn shadow-warn/60';
  if (status === 'parse_error') return 'bg-down shadow-down/60';
  return 'bg-ink-600';
}

function healthText(status: ChannelStatus): string {
  if (status === 'active') return 'text-up';
  if (status === 'stale' || status === 'no_data') return 'text-warn';
  if (status === 'parse_error') return 'text-down';
  return 'text-ink-500';
}

function TfValues({ data, check }: { data: Record<string, number>; check: (v: number) => boolean }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return null;
  return (
    <>
      {entries.map(([tf, val], i, arr) => (
        <span key={tf}>
          <span className={check(val) ? 'text-down font-semibold' : 'text-ink-300'}>
            {tf}:{(Math.round(val * 100) / 100)}
          </span>
          {i < arr.length - 1 && <span className="text-ink-600"> | </span>}
        </span>
      ))}
    </>
  );
}

function AlertCard({ a, isNew, onOpen }: { a: Alert; isNew: boolean; onOpen: (symbol: string) => void }) {
  const rsi = parseJsonSafe(a.rsi_data);
  const srsi = parseJsonSafe(a.srsi_data);
  const label = sourceLabel(a);
  const isSniper = a.source_type === '4s_sniper';
  const isFr = a.source_type === 'fr';

  return (
    <div
      onClick={() => onOpen(a.symbol)}
      title="Analiz et"
      className={`bg-ink-850 border border-white/5 border-l-2 ${borderColor(a.source_type)} px-2 py-1 mb-0.5 transition-all duration-300 cursor-pointer hover:bg-ink-800 hover:border-white/10 ${
        isNew ? 'translate-x-0 opacity-100 animate-[slideIn_0.3s_ease-out]' : ''
      }`}
    >
      <div className="flex items-center justify-between mb-0.5">
        <span className={`text-[8px] tracking-wide font-medium flex items-center gap-1 ${label.color}`}>
          <span className={`w-2 h-2 rounded-full inline-block shadow-[0_0_6px] ${
            a.direction === 'UP' ? 'bg-up shadow-up/60' : a.direction === 'DOWN' ? 'bg-down shadow-down/60' : 'bg-ink-500'
          }`} />
          {label.text}
        </span>
        <span className="text-[9px] text-white font-mono font-medium drop-shadow-[0_0_4px_rgba(255,255,255,0.5)]">{formatTime(a.created_at)}</span>
      </div>

      <div className="mb-0.5">
        <span className="text-ink-50 font-bold text-[11px]">{a.symbol}</span>
        {a.stars > 0 && (
          <span className="ml-1 inline-flex gap-0.5">
            {Array.from({ length: a.stars }).map((_, i) => (
              <Star key={i} size={10} className="text-amber-400 fill-amber-400" />
            ))}
          </span>
        )}
        {a.matched_with_bot === 1 && (
          <span className="ml-1.5 text-[8px] text-up font-medium tracking-wider">MATCHED</span>
        )}
      </div>

      <div className="font-mono text-[9px] leading-[13px] text-ink-300 space-y-px">
        {isSniper && a.signal_type && a.signal_type !== 'UNKNOWN' && (
          <div>
            <span className="text-ink-500">Strategy </span>
            <span className="text-ink-200">{a.signal_type}</span>
          </div>
        )}
        {a.boost_value !== null && (
          <div>
            <span className="text-ink-500">Boost Value </span>
            <span className={a.boost_value >= 0 ? 'text-up' : 'text-down'}>
              {a.boost_value >= 0 ? '+' : ''}{a.boost_value}%
            </span>
          </div>
        )}
        {isFr && a.funding_rate !== null && (
          <div>
            <span className="text-ink-500">FR </span>
            <span className={a.funding_rate >= 0 ? 'text-up' : 'text-down'}>
              {a.funding_rate >= 0 ? '+' : ''}{a.funding_rate.toFixed(4)}
            </span>
            {a.previous_funding !== null && (
              <>
                <span className="text-ink-600"> | </span>
                <span className="text-ink-500">Prev </span>
                <span className="text-ink-300">{a.previous_funding >= 0 ? '+' : ''}{a.previous_funding.toFixed(4)}</span>
                <span className="text-ink-600"> | </span>
                <span className="text-ink-500">Diff </span>
                <span className={(a.funding_rate - a.previous_funding) >= 0 ? 'text-up' : 'text-down'}>
                  {(a.funding_rate - a.previous_funding) >= 0 ? '+' : ''}{(a.funding_rate - a.previous_funding).toFixed(4)}
                </span>
              </>
            )}
          </div>
        )}
        {isFr && a.funding_changed === 1 && (
          <div>
            <span className="text-warn text-[9px] font-medium tracking-wider">DIRECTION CHANGED</span>
          </div>
        )}
        {isFr && a.time_remaining && (
          <div>
            <span className="text-ink-500">Time </span>
            <span className="text-ink-300">{a.time_remaining}</span>
          </div>
        )}
        {a.price !== null && (
          <div>
            <span className="text-ink-500">Price </span>
            <span className="text-ink-200">{a.price}</span>
          </div>
        )}
        {Object.keys(rsi).length > 0 && (
          <div>
            <span className="text-ink-500">RSI </span>
            <TfValues data={rsi} check={isRsiExtreme} />
          </div>
        )}
        {Object.keys(srsi).length > 0 && (
          <div>
            <span className="text-ink-500">SRSI </span>
            <TfValues data={srsi} check={isSrsiExtreme} />
          </div>
        )}
      </div>
    </div>
  );
}

export default function AlertFeed() {
  const navigate = useNavigate();
  const { alerts, fetchAlerts, fetchStats, addAlert } = useAlertStore();
  const [activeSources, setActiveSources] = useState<Set<SourceKey>>(() => loadActiveSources());
  const [newAlertIds, setNewAlertIds] = useState<Set<number>>(new Set());
  const [channelHealth, setChannelHealth] = useState<ChannelHealth[]>([]);

  const openAnalysis = (symbol: string) => {
    navigate(`/analysis?symbol=${encodeURIComponent(symbol)}`);
  };

  const toggleSource = (key: SourceKey) => {
    setActiveSources((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify([...next])); } catch {}
      return next;
    });
  };

  const allOn = activeSources.size === ALL_SOURCES.length;
  const setAll = (on: boolean) => {
    const next = on ? new Set<SourceKey>(ALL_SOURCES) : new Set<SourceKey>();
    setActiveSources(next);
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify([...next])); } catch {}
  };
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    fetchAlerts();
    fetchStats();
    const pendingTimeouts: ReturnType<typeof setTimeout>[] = [];
    const unsub = wsClient.on('alert:received', (data) => {
      addAlert(data);
      fetchStats();
      if (data.id) {
        setNewAlertIds((prev) => new Set(prev).add(data.id));
        const t = setTimeout(() => {
          setNewAlertIds((prev) => { const next = new Set(prev); next.delete(data.id); return next; });
        }, 2000);
        pendingTimeouts.push(t);
      }
    });
    return () => { unsub(); pendingTimeouts.forEach(clearTimeout); };
  }, [fetchAlerts, fetchStats, addAlert]);

  useEffect(() => {
    const loadHealth = async () => {
      try {
        setChannelHealth(await api.get<ChannelHealth[]>('/alerts/channel-health'));
      } catch {}
    };
    loadHealth();
    const id = setInterval(loadHealth, 30000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const filteredAlerts = useMemo(() => {
    if (activeSources.size === 0) return [];
    const dbValues = new Set(Array.from(activeSources).map((k) => SOURCE_TO_DB[k]));
    return alerts.filter((a) => dbValues.has(a.source_type));
  }, [alerts, activeSources]);

  const counts = useMemo(() => {
    let sniper = 0, hammer = 0, fr = 0, m1a = 0, matched = 0;
    for (const a of alerts) {
      if (a.source_type === '4s_sniper') sniper++;
      else if (a.source_type === 'hammer') hammer++;
      else if (a.source_type === 'fr') fr++;
      else if (a.source_type === 'm1_a') m1a++;
      if (a.matched_with_bot === 1) matched++;
    }
    return { sniper, hammer, fr, m1a, matched, total: alerts.length };
  }, [alerts]);

  const newCount = newAlertIds.size;

  const chipClass = (key: SourceKey) => {
    const on = activeSources.has(key);
    const colorOn = key === 'm1_a' ? 'bg-purple-500/20 text-purple-300'
      : key === 'fr' ? 'bg-emerald-500/20 text-emerald-300'
      : key === 'sniper' ? 'bg-info/20 text-info'
      : 'bg-warn/20 text-warn';
    return `px-1 py-0.5 text-[8px] tracking-tight cursor-pointer transition-colors select-none ${
      on ? colorOn : 'text-ink-500 hover:text-ink-300'
    }`;
  };

  const currentTime = now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  return (
    <div className="w-[188px] flex-shrink-0 h-full flex flex-col bg-ink-900 border-l border-white/5">
      <div className="h-9 flex items-center justify-between px-3 bg-ink-850 border-b border-white/5 flex-shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-[9px] text-ink-400 tracking-[0.3em] font-medium">[ ALERT FEED ]</span>
          {newCount > 0 && (
            <span className="bg-down/20 text-down px-1.5 text-[9px] font-medium rounded">
              {newCount}
            </span>
          )}
        </div>
        <div className="flex items-center gap-0.5">
          <span
            onClick={() => setAll(!allOn)}
            className={`px-1 py-0.5 text-[8px] tracking-tight cursor-pointer transition-colors select-none ${
              allOn ? 'bg-ink-700 text-ink-100' : 'text-ink-500 hover:text-ink-300'
            }`}
          >ALL</span>
          <span className={chipClass('sniper')} onClick={() => toggleSource('sniper')}>SNIPER</span>
          <span className={chipClass('hammer')} onClick={() => toggleSource('hammer')}>HAMMER</span>
          <span className={chipClass('fr')} onClick={() => toggleSource('fr')}>FR</span>
          <span className={chipClass('m1_a')} onClick={() => toggleSource('m1_a')}>M1-A</span>
        </div>
      </div>

      <div className="grid grid-cols-6 border-b border-white/5 flex-shrink-0">
        {[
          { label: 'SNIPER', value: counts.sniper, color: 'text-info' },
          { label: 'HAMMER', value: counts.hammer, color: 'text-warn' },
          { label: 'FR', value: counts.fr, color: 'text-emerald-400' },
          { label: 'M1-A', value: counts.m1a, color: 'text-purple-400' },
          { label: 'MATCHED', value: counts.matched, color: 'text-up' },
          { label: 'TOTAL', value: counts.total, color: 'text-ink-100' },
        ].map((c) => (
          <div key={c.label} className="px-2 py-1.5 text-center border-r border-white/5 last:border-r-0">
            <div className="text-[9px] text-ink-500 tracking-wider">{c.label}</div>
            <div className={`text-sm font-semibold font-mono ${c.color}`}>{c.value}</div>
          </div>
        ))}
      </div>

      {channelHealth.length > 0 && (
        <div className="grid grid-cols-4 border-b border-white/5 bg-ink-900/60 flex-shrink-0">
          {channelHealth.map((h) => (
            <div
              key={h.source_type}
              title={`${h.label}: ${h.note} | parsed 24h: ${h.parsed_24h} | unparsed 24h: ${h.unparsed_24h}`}
              className="min-w-0 px-2 py-1 border-r border-white/5 last:border-r-0"
            >
              <div className="flex items-center justify-center gap-1.5 min-w-0">
                <span className={`w-1.5 h-1.5 rounded-full shadow-[0_0_6px] ${healthTone(h.status)}`} />
                <span className={`text-[8px] tracking-wider font-semibold truncate ${healthText(h.status)}`}>{h.label}</span>
                <span className="text-[8px] text-ink-500 font-mono">{formatAge(h.last_parsed_at ?? h.last_message_at)}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center gap-1.5 px-3 py-1 border-b border-white/5 flex-shrink-0">
        <span className="w-1.5 h-1.5 rounded-full bg-up animate-pulse" />
        <span className="text-[9px] text-ink-400">
          live · streaming
        </span>
        <span className="text-[9px] text-ink-500 font-mono ml-auto">{currentTime}</span>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-2 min-h-0">
        {filteredAlerts.length === 0 ? (
          <p className="text-ink-600 text-[10px] text-center py-8">No signals</p>
        ) : (
          filteredAlerts.map((a) => (
            <AlertCard key={a.id} a={a} isNew={newAlertIds.has(a.id)} onOpen={openAnalysis} />
          ))
        )}
      </div>

    </div>
  );
}
