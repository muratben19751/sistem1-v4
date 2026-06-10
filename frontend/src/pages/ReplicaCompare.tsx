import { useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../lib/api';

interface FeedItem {
  symbol: string;
  direction: 'UP' | 'DOWN';
  origin: 'real' | 'replica';
  ts: number;
  matched: boolean;
  agree: boolean;
}

interface ChannelCmp {
  channel: string;
  label: string;
  sourceType: string;
  realCount: number;
  realOffBybit: number;
  replicaCount: number;
  realSymbols: number;
  replicaSymbols: number;
  matched: number;
  agree: number;
  agreePct: number | null;
  coveragePct: number | null;
  precisionPct: number | null;
  feed: FeedItem[];
}

interface CompareData {
  minutes: number;
  generatedAt: number;
  running: boolean;
  channels: ChannelCmp[];
}

const WINDOWS = [15, 30, 60, 240];

function pctColor(p: number | null): string {
  if (p == null) return 'text-ink-500';
  if (p >= 75) return 'text-up';
  if (p >= 50) return 'text-warn';
  return 'text-down';
}

function fmtTime(ts: number): string {
  const d = new Date(ts);
  return d.toISOString().slice(11, 19);
}

function Stat({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[9px] text-ink-500 tracking-[0.18em] uppercase">{label}</span>
      <span className={`text-[15px] num ${cls ?? 'text-ink-100'}`}>{value}</span>
    </div>
  );
}

function ChannelCard({ c }: { c: ChannelCmp }) {
  return (
    <div className="border border-white/5 bg-ink-850 flex flex-col min-h-0">
      <div className="flex items-center justify-between px-3 py-2 border-b border-white/5">
        <span className="text-[12px] text-ink-50 tracking-wide">{c.label}</span>
        <span className="text-[9px] text-ink-500">
          {c.realOffBybit > 0 && <span className="text-ink-600" title="Gercek sinyal Binance-only, Bybit'te yok, kiyasa dahil degil">{c.realOffBybit} Bybit-disi · </span>}
          {c.sourceType}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-2 px-3 py-2.5 border-b border-white/5">
        <Stat label="Gercek" value={String(c.realCount)} cls="text-sky-400" />
        <Stat label="Replica" value={String(c.replicaCount)} cls="text-amber-400" />
        <Stat label="Ortak" value={String(c.matched)} />
        <Stat label="Yon uyumu" value={c.agreePct == null ? '--' : `%${c.agreePct}`} cls={pctColor(c.agreePct)} />
        <Stat label="Kapsama" value={c.coveragePct == null ? '--' : `%${c.coveragePct}`} cls={pctColor(c.coveragePct)} />
        <Stat label="Isabet" value={c.precisionPct == null ? '--' : `%${c.precisionPct}`} cls={pctColor(c.precisionPct)} />
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin">
        {c.feed.length === 0 ? (
          <p className="text-[10px] text-ink-600 text-center py-6">Bu pencerede sinyal yok</p>
        ) : (
          c.feed.map((f, i) => (
            <div key={i} className="flex items-center gap-2 px-3 py-1 text-[10px] border-b border-white/[0.03] hover:bg-white/[0.02]">
              <span className="text-ink-600 w-[58px] flex-shrink-0">{fmtTime(f.ts)}</span>
              <span
                className={`w-[14px] text-center flex-shrink-0 ${f.origin === 'real' ? 'text-sky-400' : 'text-amber-400'}`}
                title={f.origin === 'real' ? 'Gercek telegram' : 'Replica'}
              >
                {f.origin === 'real' ? 'T' : 'R'}
              </span>
              <span className="text-ink-200 flex-1 truncate">{f.symbol}</span>
              <span className={`w-[42px] text-right flex-shrink-0 ${f.direction === 'UP' ? 'text-up' : 'text-down'}`}>
                {f.direction}
              </span>
              <span className="w-[16px] text-center flex-shrink-0" title={f.matched ? (f.agree ? 'Eslesti + yon ayni' : 'Eslesti, yon farkli') : 'Eslesmedi'}>
                {f.matched ? (f.agree ? <span className="text-up">✓</span> : <span className="text-warn">≠</span>) : <span className="text-ink-700">·</span>}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default function ReplicaCompare() {
  const [minutes, setMinutes] = useState(30);
  const [data, setData] = useState<CompareData | null>(null);
  const [err, setErr] = useState('');
  // Pencere degisiminde havadaki eski yanit yenisini ezmesin (monoton istek sayaci)
  const reqIdRef = useRef(0);

  const load = useCallback(() => {
    const reqId = ++reqIdRef.current;
    api.get<CompareData>(`/replica-compare?minutes=${minutes}`)
      .then((d) => { if (reqId !== reqIdRef.current) return; setData(d); setErr(''); })
      .catch((e) => { if (reqId !== reqIdRef.current) return; setErr(e?.message ?? 'hata'); });
  }, [minutes]);

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <div className="flex flex-col h-full font-mono">
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
        <div>
          <h1 className="text-[14px] text-ink-50 tracking-wide">Replica ↔ Telegram Canli Kiyas</h1>
          <p className="text-[10px] text-ink-500 mt-0.5">
            Yerel uretecler vs gercek telegram · sadece Bybit-tradable sembollerde kiyas · {data?.running ? <span className="text-up">aktif</span> : <span className="text-down">durmus</span>}
            {data && <span className="text-ink-600"> · son {fmtTime(data.generatedAt)}</span>}
          </p>
        </div>
        <div className="flex items-center gap-1">
          {WINDOWS.map((w) => (
            <button
              key={w}
              onClick={() => setMinutes(w)}
              className={`px-2.5 py-1 text-[11px] border transition-colors ${
                minutes === w ? 'border-up/40 bg-up/10 text-up' : 'border-white/10 text-ink-300 hover:bg-white/[0.03]'
              }`}
            >
              {w >= 60 ? `${w / 60}s` : `${w}d`}
            </button>
          ))}
        </div>
      </div>

      {err && <div className="px-4 py-2 text-[11px] text-down">Hata: {err}</div>}

      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-2 gap-3 p-3 overflow-auto">
        {(data?.channels ?? []).map((c) => <ChannelCard key={c.channel} c={c} />)}
      </div>

      <div className="px-4 py-1.5 border-t border-white/5 text-[9px] text-ink-600 flex gap-4">
        <span><span className="text-sky-400">T</span> = gercek telegram</span>
        <span><span className="text-amber-400">R</span> = replica</span>
        <span><span className="text-up">✓</span> eslesti+yon ayni</span>
        <span><span className="text-warn">≠</span> eslesti+yon farkli</span>
        <span>Yon uyumu: ortak sembollerde yon ayni %'si · Kapsama: gercegin ne kadarini yakaladik · Isabet: replica'nin ne kadari gercekte var</span>
      </div>
    </div>
  );
}
