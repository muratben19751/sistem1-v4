import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import { formatUsd, formatPercent, formatDate, formatDuration } from '../lib/formatters';
import { RULES_DEFS } from '../lib/rule-defs';
import type { SignalResult, Position } from '../types';
import { ArrowLeft } from 'lucide-react';
import TradeReviewChart from '../components/charts/TradeReviewChart';

const RULE_DEF_MAP = new Map(RULES_DEFS.map((r) => [r.key, r]));

function fmtScore(score: number): string {
  const s = Number.isInteger(score) ? String(score) : score.toFixed(2);
  return score > 0 ? `+${s}` : s;
}

interface Trade {
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

export default function TradeDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [trade, setTrade] = useState<Trade | null>(null);
  const [live, setLive] = useState<SignalResult | null>(null);
  const [liveState, setLiveState] = useState<'idle' | 'loading' | 'error'>('idle');
  const [pos, setPos] = useState<Position | null>(null);

  useEffect(() => {
    if (id) {
      api.get<Trade>(`/trades/${id}`).then(setTrade).catch(() => {});
    }
  }, [id]);

  useEffect(() => {
    if (!trade || trade.status !== 'open') {
      setLive(null);
      setLiveState('idle');
      return;
    }
    let cancelled = false;
    setLive(null);
    setLiveState('loading');
    const params = new URLSearchParams({ accountId: String(trade.account_id) });
    api.get<SignalResult>(`/analysis/analyze/${encodeURIComponent(trade.symbol)}?${params.toString()}`)
      .then((res) => { if (!cancelled) { setLive(res); setLiveState('idle'); } })
      .catch(() => { if (!cancelled) { setLive(null); setLiveState('error'); } });
    return () => { cancelled = true; };
  }, [trade?.id, trade?.status, trade?.symbol, trade?.account_id]);

  // Acik trade icin pozisyonu cek (grafikte TP/SL cizgileri icin).
  useEffect(() => {
    if (!trade || trade.status !== 'open') { setPos(null); return; }
    let cancelled = false;
    api.get<Position[]>(`/positions?accountId=${trade.account_id}`)
      .then((list) => {
        if (cancelled) return;
        setPos(list.find((p) => p.symbol === trade.symbol && p.side === trade.side) ?? null);
      })
      .catch(() => { if (!cancelled) setPos(null); });
    return () => { cancelled = true; };
  }, [trade?.id, trade?.status, trade?.symbol, trade?.side, trade?.account_id]);

  if (!trade) {
    return (
      <div className="min-h-screen bg-ink-900 p-4">
        <p className="text-ink-500 text-[11px]">Yukleniyor...</p>
      </div>
    );
  }

  const rules = (trade.active_rules ? trade.active_rules.split(',').filter(Boolean) : [])
    .map((item) => {
      const idx = item.indexOf(':');
      const key = idx >= 0 ? item.slice(0, idx) : item;
      const scoreStr = idx >= 0 ? item.slice(idx + 1) : '';
      const score = scoreStr !== '' && !Number.isNaN(Number(scoreStr)) ? Number(scoreStr) : null;
      return { key, score };
    })
    .sort((a, b) => Math.abs(b.score ?? 0) - Math.abs(a.score ?? 0));

  const hasScores = rules.some((r) => r.score !== null);
  const totalScore = rules.reduce((sum, r) => sum + (r.score ?? 0), 0);

  const liveRules = live
    ? live.rules.filter((r) => r.score !== 0).sort((a, b) => Math.abs(b.score) - Math.abs(a.score))
    : [];

  return (
    <div className="min-h-screen bg-ink-900 p-4 space-y-4">
      <button
        onClick={() => navigate(-1)}
        className="flex items-center gap-2 text-ink-400 hover:text-ink-50 text-[11px] transition-colors"
      >
        <ArrowLeft size={14} /> Geri
      </button>

      <div className="h-9 flex items-center px-3 bg-ink-850 border-b border-white/5">
        <span className="text-[9px] tracking-[0.3em] text-ink-400">[ TRADE #{trade.id} ]</span>
      </div>

      <div className="bg-ink-900 border border-white/5">
        <div className="h-9 flex items-center justify-between px-3 bg-ink-850 border-b border-white/5">
          <span className="text-[9px] tracking-[0.3em] text-ink-400">[ GRAFIK · GIRIS / CIKIS ]</span>
          <span className="text-[10px] text-ink-500">
            <span className={trade.side === 'long' ? 'text-up' : 'text-down'}>GIRIS {trade.side === 'long' ? '▲' : '▼'}</span>
            <span className="mx-2 text-ink-600">|</span>
            <span className="text-warn">CIKIS ●</span>
          </span>
        </div>
        <div className="p-3">
          <TradeReviewChart
            symbol={trade.symbol}
            side={trade.side as 'long' | 'short'}
            entry_price={trade.entry_price}
            exit_price={trade.exit_price}
            opened_at={trade.opened_at}
            closed_at={trade.closed_at}
            tp_price={pos?.tp_price ?? null}
            sl_price={pos?.sl_price ?? null}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-ink-900 border border-white/5">
          <div className="h-9 flex items-center px-3 bg-ink-850 border-b border-white/5">
            <span className="text-[9px] tracking-[0.3em] text-ink-400">[ TRADE BILGILERI ]</span>
          </div>
          <div className="p-3 space-y-0">
            <Row label="Sembol" value={trade.symbol} />
            <Row label="Yon">
              <span className={trade.side === 'long' ? 'text-up' : 'text-down'}>
                {trade.side.toUpperCase()}
              </span>
            </Row>
            <Row label="Durum">
              <span className={`px-2 py-0.5 text-[10px] font-medium border ${
                trade.status === 'open'
                  ? 'bg-info/10 text-info border-info/30'
                  : 'bg-ink-700 text-ink-300 border-white/10'
              }`}>
                {trade.status.toUpperCase()}
              </span>
            </Row>
            <Row label="Miktar" value={trade.size.toFixed(6)} />
            <Row label="Leverage" value={`${trade.leverage}x`} />
            <Row label="Giris Fiyat" value={trade.entry_price.toFixed(4)} />
            <Row label="Cikis Fiyat" value={trade.exit_price?.toFixed(4) ?? '-'} />
            <Row label="Acilis" value={formatDate(trade.opened_at)} />
            <Row label="Kapanis" value={trade.closed_at ? formatDate(trade.closed_at) : '-'} />
            <Row label="Sure" value={trade.duration_seconds ? formatDuration(trade.duration_seconds) : '-'} />
          </div>
        </div>

        <div className="bg-ink-900 border border-white/5">
          <div className="h-9 flex items-center px-3 bg-ink-850 border-b border-white/5">
            <span className="text-[9px] tracking-[0.3em] text-ink-400">[ PNL & ANALIZ ]</span>
          </div>
          <div className="p-3 space-y-0">
            <Row label="PnL">
              <span className={`text-lg font-semibold num ${(trade.pnl || 0) >= 0 ? 'text-up' : 'text-down'}`}>
                {formatUsd(trade.pnl || 0)}
              </span>
            </Row>
            <Row label="PnL %">
              <span className={`num ${(trade.pnl_percent || 0) >= 0 ? 'text-up' : 'text-down'}`}>
                {formatPercent(trade.pnl_percent || 0)}
              </span>
            </Row>
            <Row label="Fee" value={formatUsd(trade.fee)} />
            <Row label="Sinyal Skoru">
              <span className={`font-medium num ${
                (trade.signal_score || 0) > 0 ? 'text-up' :
                (trade.signal_score || 0) < 0 ? 'text-down' : 'text-ink-400'
              }`}>
                {trade.signal_score?.toFixed(1) ?? '-'}
              </span>
            </Row>
            <Row label="Giris Nedeni" value={trade.entry_reason || '-'} />
            <Row label="Cikis Nedeni" value={trade.exit_reason || '-'} />
          </div>
        </div>

        {rules.length > 0 && (
          <div className="lg:col-span-2 bg-ink-900 border border-white/5">
            <div className="h-9 flex items-center justify-between px-3 bg-ink-850 border-b border-white/5">
              <span className="text-[9px] tracking-[0.3em] text-ink-400">[ AKTIF KURALLAR ]</span>
              {hasScores && (
                <span className="text-[10px] text-ink-400">
                  Toplam:{' '}
                  <span className={`num font-medium ${totalScore > 0 ? 'text-up' : totalScore < 0 ? 'text-down' : 'text-ink-400'}`}>
                    {fmtScore(Math.round(totalScore * 100) / 100)}
                  </span>
                </span>
              )}
            </div>
            <div className="p-3 flex flex-wrap gap-2">
              {rules.map(({ key, score }) => {
                const def = RULE_DEF_MAP.get(key);
                return (
                  <span
                    key={key}
                    className="flex items-center gap-2 px-3 py-1.5 bg-ink-800 border border-white/5 text-ink-300 text-[10px]"
                  >
                    <span>{def ? `#${def.num} ${def.name}` : key}</span>
                    {score !== null && (
                      <span className={`num font-medium ${score > 0 ? 'text-up' : score < 0 ? 'text-down' : 'text-ink-400'}`}>
                        {fmtScore(score)}
                      </span>
                    )}
                  </span>
                );
              })}
            </div>
          </div>
        )}

        {trade.status === 'open' && (
          <div className="lg:col-span-2 bg-ink-900 border border-white/5">
            <div className="h-9 flex items-center justify-between px-3 bg-ink-850 border-b border-white/5">
              <span className="text-[9px] tracking-[0.3em] text-ink-400">[ GUNCEL KURAL SKORLARI ]</span>
              {liveState === 'idle' && live && (
                <span className="text-[10px] text-ink-400">
                  Toplam:{' '}
                  <span className={`num font-medium ${live.totalScore > 0 ? 'text-up' : live.totalScore < 0 ? 'text-down' : 'text-ink-400'}`}>
                    {fmtScore(Math.round(live.totalScore * 100) / 100)}
                  </span>
                </span>
              )}
            </div>
            <div className="px-3 pt-2">
              <p className="text-[9px] text-ink-500">
                Hesabin rule ayarlari ve agirliklariyla su an icin yeniden hesaplandi (giris anindaki degil).
              </p>
            </div>
            <div className="p-3 pt-2">
              {liveState === 'loading' && <p className="text-ink-500 text-[10px]">Hesaplaniyor...</p>}
              {liveState === 'error' && <p className="text-down text-[10px]">Canli skor alinamadi.</p>}
              {liveState === 'idle' && live && liveRules.length === 0 && (
                <p className="text-ink-500 text-[10px]">Su an etkin kural yok (tum skorlar 0).</p>
              )}
              {liveRules.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {liveRules.map((r) => {
                    const def = RULE_DEF_MAP.get(r.key);
                    return (
                      <span
                        key={r.key}
                        className="flex items-center gap-2 px-3 py-1.5 bg-ink-800 border border-white/5 text-ink-300 text-[10px]"
                      >
                        <span>{def ? `#${def.num} ${def.name}` : r.name || r.key}</span>
                        <span className={`num font-medium ${r.score > 0 ? 'text-up' : r.score < 0 ? 'text-down' : 'text-ink-400'}`}>
                          {fmtScore(r.score)}
                        </span>
                      </span>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ label, value, children }: { label: string; value?: string; children?: React.ReactNode }) {
  return (
    <div className="flex justify-between items-center py-1.5 border-b border-white/5">
      <span className="text-ink-400 text-[10px]">{label}</span>
      {children || <span className="text-ink-200 text-[11px] num">{value}</span>}
    </div>
  );
}
