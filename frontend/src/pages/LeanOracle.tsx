import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ShieldCheck, ArrowRight, Boxes, Cpu, Scale, AlertTriangle, CheckCircle2, MinusCircle, Info, Terminal, Play, Loader2 } from 'lucide-react';
import { api } from '../lib/api';

interface OracleStatus {
  dockerAvailable: boolean;
  leanInstalled: boolean;
  runCount: number;
  latestRun: string | null;
  exportRootExists: boolean;
}

interface RunSummary {
  trades?: number;
  totalPnl?: number;
  totalPnlPct?: number;
  winRate?: number;
  profitFactor?: number;
  sharpe?: number;
  maxDrawdown?: number;
  calmar?: number;
}

interface RunItem {
  runId: string;
  strategy?: string;
  window?: string;
  execTf?: string;
  signalCount?: number;
  tradedSymbols?: string[];
  summary?: RunSummary;
  hasReport?: boolean;
}

interface ReportRow {
  metric: string;
  mine: number | null;
  lean: number | null;
  relPct: number | null;
  kind: 'mechanical' | 'modeling' | 'definitional';
  verdict: 'PASS' | 'MINOR' | 'INVESTIGATE' | 'NOTE' | 'N/A';
  note: string;
}

interface ReportMeta {
  strategy?: string;
  window?: string;
  symbols?: string;
  execTf?: string;
  startIso?: string;
  endIso?: string;
  initialBalance?: number;
  leanSource?: string;
}

interface ReportResponse {
  empty: boolean;
  reason?: string;
  runId?: string;
  meta?: ReportMeta;
  rows?: ReportRow[];
  manifest?: { tradedSymbols?: string[]; signalCount?: number };
}

const KIND_LABEL: Record<string, string> = {
  mechanical: 'Mekanik',
  modeling: 'Modelleme',
  definitional: 'Tanimsal',
};

function fmt(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return '—';
  const r = Number(v.toFixed(digits));
  return String(r);
}

function VerdictChip({ verdict }: { verdict: ReportRow['verdict'] }) {
  const map: Record<string, { cls: string; icon: JSX.Element; text: string }> = {
    PASS: { cls: 'text-up bg-up/10 border-up/30', icon: <CheckCircle2 size={11} />, text: 'PASS' },
    MINOR: { cls: 'text-warn bg-warn/10 border-warn/30', icon: <MinusCircle size={11} />, text: 'MINOR' },
    INVESTIGATE: { cls: 'text-down bg-down/10 border-down/30', icon: <AlertTriangle size={11} />, text: 'INCELE' },
    NOTE: { cls: 'text-ink-300 bg-white/5 border-white/10', icon: <Info size={11} />, text: 'NOT' },
    'N/A': { cls: 'text-ink-500 bg-white/5 border-white/10', icon: <MinusCircle size={11} />, text: 'N/A' },
  };
  const v = map[verdict] ?? map['N/A'];
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[9px] tracking-wide ${v.cls}`}>
      {v.icon}{v.text}
    </span>
  );
}

function StatusPill({ ok, label, okText, noText }: { ok: boolean; label: string; okText: string; noText: string }) {
  return (
    <div className="flex items-center gap-2 bg-ink-850 border border-white/5 rounded px-2.5 py-1.5">
      <span className={`w-1.5 h-1.5 rounded-full ${ok ? 'bg-up' : 'bg-down'}`} />
      <span className="text-[9px] text-ink-400 tracking-[0.2em] uppercase">{label}</span>
      <span className={`text-[10px] ${ok ? 'text-up' : 'text-down'}`}>{ok ? okText : noText}</span>
    </div>
  );
}

function StepCard({ icon, n, title, desc }: { icon: JSX.Element; n: string; title: string; desc: string }) {
  return (
    <div className="flex-1 bg-ink-850 border border-white/5 rounded p-3">
      <div className="flex items-center gap-2 mb-1.5">
        <span className="w-6 h-6 flex items-center justify-center rounded bg-up/10 text-up">{icon}</span>
        <span className="text-[9px] text-ink-500 tracking-[0.2em]">ADIM {n}</span>
      </div>
      <h3 className="text-[12px] text-ink-100 mb-1">{title}</h3>
      <p className="text-[10px] leading-[15px] text-ink-400">{desc}</p>
    </div>
  );
}

export default function LeanOracle() {
  const [status, setStatus] = useState<OracleStatus | null>(null);
  const [runs, setRuns] = useState<RunItem[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchParams] = useSearchParams();
  const strategyParam = searchParams.get('strategy');

  useEffect(() => {
    Promise.all([
      api.get<OracleStatus>('/lean-oracle/status').catch(() => null),
      api.get<{ runs: RunItem[] }>('/lean-oracle/runs').catch(() => ({ runs: [] })),
    ]).then(([st, rs]) => {
      setStatus(st);
      setRuns(rs?.runs ?? []);
      setLoading(false);
    });
  }, []);

  // OptimizerLab'den ?strategy=<ad> ile gelince o stratejinin en son kosumunu sec.
  useEffect(() => {
    if (!runs.length) return;
    if (strategyParam) {
      const match = runs.find((r) => r.strategy === strategyParam);
      setSelected(match ? match.runId : null);
    } else if (!selected) {
      setSelected(runs[0].runId);
    }
  }, [runs, strategyParam]);

  useEffect(() => {
    if (!selected) { setReport(null); return; }
    api.get<ReportResponse>(`/lean-oracle/report?run=${encodeURIComponent(selected)}`)
      .then(setReport)
      .catch(() => setReport(null));
  }, [selected]);

  const [jobRunning, setJobRunning] = useState(false);
  const [jobMsg, setJobMsg] = useState('');
  // Kendini yeniden kuran poll zinciri unmount'tan sonra devam etmesin
  const pollTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const pollActiveRef = useRef(true);

  useEffect(() => {
    pollActiveRef.current = true;
    return () => {
      pollActiveRef.current = false;
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
  }, []);

  const triggerRun = async (strategy: string) => {
    setJobRunning(true);
    setJobMsg('Koşum başlatılıyor…');
    try {
      await api.post('/lean-oracle/run', { strategy });
    } catch (e: any) {
      setJobMsg('Başlatılamadı (başka koşum sürüyor olabilir): ' + (e?.message || ''));
      setJobRunning(false);
      return;
    }
    const poll = async () => {
      if (!pollActiveRef.current) return;
      const st = await api.get<any>('/lean-oracle/run-status').catch(() => null);
      if (!pollActiveRef.current) return;
      if (st && st.running) {
        setJobMsg(`Koşuyor (${st.mode || '…'} modu) — ~1-2 dk, lütfen bekleyin…`);
        pollTimerRef.current = setTimeout(poll, 3000);
        return;
      }
      setJobRunning(false);
      if (st?.error) {
        setJobMsg('Koşum hatası: ' + st.error);
      } else {
        setJobMsg('Koşum tamamlandı ✓');
        const rs = await api.get<{ runs: RunItem[] }>('/lean-oracle/runs').catch(() => ({ runs: [] }));
        if (!pollActiveRef.current) return;
        setRuns(rs?.runs ?? []);
      }
    };
    pollTimerRef.current = setTimeout(poll, 2500);
  };

  const meta = report?.meta;
  const rows = report?.rows ?? [];
  const isStub = meta?.leanSource === 'stub';
  const investigate = rows.filter((r) => r.verdict === 'INVESTIGATE');
  const strategyHasRun = !strategyParam || runs.some((r) => r.strategy === strategyParam);

  return (
    <div className="p-5 max-w-[1100px] mx-auto font-mono">
      {/* Baslik */}
      <div className="flex items-start gap-3 mb-1">
        <span className="w-9 h-9 flex items-center justify-center rounded bg-up/10 text-up mt-0.5"><ShieldCheck size={18} /></span>
        <div>
          <h1 className="text-[16px] text-ink-50 tracking-wide">LEAN Doğrulama Kâhini <span className="text-ink-500">(Oracle)</span></h1>
          <p className="text-[11px] text-ink-400 mt-0.5 max-w-[760px] leading-[16px]">
            Kendi <span className="text-ink-200">run_backtest()</span> motorumun <span className="text-ink-200">icra matematiğini</span> —
            giriş → TP/SL/çıkış, komisyon, slippage, kaldıraç, portföy yürüyüşü, drawdown ve equity —
            QuantConnect <span className="text-ink-200">LEAN</span>'in kanıtlanmış motoruyla <span className="text-ink-200">bağımsız</span> kıyaslar.
            Amaç: sinyal üretimini değil, en çok gizli bug barındıran <span className="text-ink-200">mekanik icrayı</span> doğrulamak.
          </p>
        </div>
      </div>

      {/* Durum */}
      <div className="flex flex-wrap gap-2 mt-3 mb-5">
        <StatusPill ok={!!status?.leanInstalled} label="lean CLI" okText="kurulu" noText="yok" />
        <StatusPill ok={!!status?.dockerAvailable} label="Docker" okText="hazır" noText="kurulu değil" />
        <div className="flex items-center gap-2 bg-ink-850 border border-white/5 rounded px-2.5 py-1.5">
          <span className="text-[9px] text-ink-400 tracking-[0.2em] uppercase">Koşum</span>
          <span className="text-[10px] text-ink-100">{status?.runCount ?? 0}</span>
        </div>
        {isStub && (
          <div className="flex items-center gap-2 bg-warn/10 border border-warn/30 rounded px-2.5 py-1.5">
            <Info size={11} className="text-warn" />
            <span className="text-[10px] text-warn">STUB modu — boru hattı doğrulaması (gerçek LEAN değil)</span>
          </div>
        )}
      </div>

      {/* OptimizerLab'den strateji ile gelindi */}
      {strategyParam && (
        <div className={`rounded border px-3 py-2 mb-4 text-[11px] flex items-start gap-2 ${
          strategyHasRun ? 'bg-up/10 border-up/30 text-up' : 'bg-warn/10 border-warn/30 text-warn'
        }`}>
          {strategyHasRun ? <ShieldCheck size={13} className="mt-0.5" /> : <Info size={13} className="mt-0.5" />}
          {strategyHasRun ? (
            <span><span className="text-ink-100">{strategyParam}</span> — LEAN parite raporu gösteriliyor.</span>
          ) : (
            <div className="flex flex-col gap-2 w-full">
              <span><span className="text-ink-100">{strategyParam}</span> için henüz LEAN koşumu yok.</span>
              <div className="flex items-center gap-2 flex-wrap">
                <button
                  onClick={() => triggerRun(strategyParam)}
                  disabled={jobRunning}
                  className="flex items-center gap-1.5 text-[10px] px-2.5 py-1 rounded border border-up/40 bg-up/10 text-up hover:bg-up/20 disabled:opacity-50"
                >
                  {jobRunning ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
                  {jobRunning ? 'Koşuyor…' : 'Koşum Yap'}
                </button>
                {jobMsg && <span className="text-[10px] text-ink-300">{jobMsg}</span>}
              </div>
              <span className="text-[9px] text-ink-500">
                Docker varsa gerçek LEAN motoru, yoksa stub modu çalışır (~1-2 dk). Manuel:{' '}
                <code className="text-ink-400">python -m lean_oracle.run --strategy {strategyParam} --mode lean</code>
              </span>
            </div>
          )}
        </div>
      )}

      {/* Tasarim kisidi */}
      <div className="bg-ink-850 border border-white/5 rounded p-3.5 mb-4">
        <div className="text-[9px] text-ink-500 tracking-[0.25em] uppercase mb-1.5">Tasarım Kısıdı — Neden Böyle?</div>
        <p className="text-[11px] leading-[17px] text-ink-300">
          27 kuralım / sinyal skorlamam LEAN'de <span className="text-ink-100">yeniden yazılmaz</span>. Bu, sürüklenmeye açık üçüncü bir
          implementasyon yaratır ve funding/OI bağımlı kurallar LEAN'de sadık üretilemez. Bunun yerine: kendi backtest'imin
          <span className="text-ink-100"> zaten verdiği giriş kararlarını</span> (zaman, sembol, yön, referans fiyat + TP/SL/kaldıraç/pozisyon
          config'i) LEAN'e beslerim. LEAN <span className="text-ink-100">yalnızca icra simülasyonunu</span> yapar; çıkışı kendi fill motoruyla
          bağımsız türetir. Böylece iki motor <span className="text-ink-100">aynı girişlerden</span> yola çıkar ve yalnızca icra matematiği kıyaslanır.
        </p>
      </div>

      {/* 3 adim */}
      <div className="flex flex-col sm:flex-row gap-2 mb-5 items-stretch">
        <StepCard icon={<Boxes size={14} />} n="1" title="EXPORT"
          desc="Seçilen strateji + pencere için kendi run_backtest()'imi koşar; açtığı girişleri, metriklerini ve kullandığı mumları diske yazar. Mumlar kendi SQLite cache'imden gelir — QC veri seti satın alınmaz." />
        <div className="flex items-center justify-center text-ink-600"><ArrowRight size={16} /></div>
        <StepCard icon={<Cpu size={14} />} n="2" title="LEAN"
          desc="LEAN algoritması girişleri replay eder: maxPositions / sembol-başına-tek / sermaye kısıtına uyup pozisyon açar, TP/SL kurar, çıkışı LEAN motoruna bırakır. Bybit brokerage + Margin → komisyonlar benimkiyle eşleşir." />
        <div className="flex items-center justify-center text-ink-600"><ArrowRight size={16} /></div>
        <StepCard icon={<Scale size={14} />} n="3" title="COMPARE"
          desc="LEAN istatistiklerini benim metriklerimle yan yana koyar; her metrik için mutlak/oransal farkı hesaplar ve 'beklenen modelleme farkı' mı yoksa 'açıklanamayan sapma = olası bug' mı diye sınıflandırır." />
      </div>

      {/* Bos durum */}
      {!loading && runs.length === 0 && (
        <div className="bg-ink-850 border border-white/5 rounded p-5 text-center">
          <ShieldCheck size={28} className="text-ink-600 mx-auto mb-2" />
          <p className="text-[12px] text-ink-200 mb-1">Henüz parite koşumu yok</p>
          <p className="text-[10px] text-ink-500 mb-3 max-w-[520px] mx-auto leading-[15px]">
            Bir doğrulama koşumu üretmek için aşağıdaki komutu çalıştır. Docker yokken <span className="text-ink-300">stub</span> modu
            export → compare boru hattını uçtan uca doğrular ve bir parite raporu üretir.
          </p>
          <pre className="text-left text-[10px] text-up bg-ink-900 border border-white/5 rounded p-3 inline-block">
{`cd backend
python -m lean_oracle.run --window 90d --symbols TOP10`}
          </pre>
        </div>
      )}

      {/* Koşum secici + ozet */}
      {runs.length > 0 && (
        <>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-[9px] text-ink-500 tracking-[0.2em] uppercase">Koşum</span>
            <select
              value={selected ?? ''}
              onChange={(e) => setSelected(e.target.value)}
              className="bg-ink-800 border border-white/10 rounded px-2 py-1 text-[11px] text-ink-100 outline-none focus:border-up"
            >
              {runs.map((r) => (
                <option key={r.runId} value={r.runId}>
                  {r.strategy} · {r.window} · {r.signalCount} sinyal · {r.tradedSymbols?.length ?? 0} sembol
                </option>
              ))}
            </select>
          </div>

          {meta && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
              {[
                ['Strateji', meta.strategy],
                ['Pencere', `${meta.window} · ${meta.execTf}m`],
                ['Semboller', report?.manifest?.tradedSymbols?.join(', ') ?? meta.symbols],
                ['Başlangıç', `${meta.initialBalance} USDT`],
              ].map(([k, v]) => (
                <div key={k} className="bg-ink-850 border border-white/5 rounded px-2.5 py-1.5">
                  <div className="text-[9px] text-ink-500 tracking-[0.2em] uppercase">{k}</div>
                  <div className="text-[10px] text-ink-100 mt-0.5 truncate" title={String(v ?? '')}>{v ?? '—'}</div>
                </div>
              ))}
            </div>
          )}

          {/* Ozet hukum */}
          {rows.length > 0 && (
            <div className={`rounded border px-3 py-2 mb-4 text-[11px] flex items-start gap-2 ${
              investigate.length > 0 ? 'bg-down/10 border-down/30 text-down' : 'bg-up/10 border-up/30 text-up'
            }`}>
              {investigate.length > 0 ? <AlertTriangle size={13} className="mt-0.5" /> : <CheckCircle2 size={13} className="mt-0.5" />}
              <span>
                {investigate.length > 0
                  ? `${investigate.length} mekanik metrikte >%5 açıklanamayan sapma var — icra mantığında olası bug. İncele: ${investigate.map((r) => r.metric).join(', ')}.`
                  : 'Tüm mekanik metrikler tolerans içinde (>%5 sapma yok). İcra matematiği LEAN ile uyumlu görünüyor.'}
              </span>
            </div>
          )}

          {/* Parite tablosu */}
          {rows.length > 0 && (
            <div className="bg-ink-850 border border-white/5 rounded overflow-hidden mb-2">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-ink-500 text-[9px] tracking-[0.15em] uppercase border-b border-white/5">
                    <th className="text-left font-normal px-3 py-2">Metrik</th>
                    <th className="text-right font-normal px-3 py-2">Benimki</th>
                    <th className="text-right font-normal px-3 py-2">LEAN</th>
                    <th className="text-right font-normal px-3 py-2">Fark %</th>
                    <th className="text-left font-normal px-3 py-2">Sınıf</th>
                    <th className="text-left font-normal px-3 py-2">Hüküm</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.metric} className="border-b border-white/[0.03] hover:bg-white/[0.015]">
                      <td className="px-3 py-2 text-ink-100">
                        {r.metric}
                        <div className="text-[9px] text-ink-500 leading-[13px] mt-0.5 max-w-[340px]">{r.note}</div>
                      </td>
                      <td className="px-3 py-2 text-right text-ink-200 num">{fmt(r.mine)}</td>
                      <td className="px-3 py-2 text-right text-ink-200 num">{fmt(r.lean)}</td>
                      <td className={`px-3 py-2 text-right num ${
                        r.relPct == null ? 'text-ink-500'
                          : r.kind !== 'definitional' && r.relPct > 5 ? 'text-down'
                          : r.kind !== 'definitional' && r.relPct > 1 ? 'text-warn'
                          : 'text-ink-300'
                      }`}>{r.relPct == null ? '—' : `${r.relPct.toFixed(2)}%`}</td>
                      <td className="px-3 py-2 text-ink-400 text-[10px]">{KIND_LABEL[r.kind]}</td>
                      <td className="px-3 py-2"><VerdictChip verdict={r.verdict} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* Lejant */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-5">
        <div className="bg-ink-850 border border-white/5 rounded p-3">
          <div className="text-[9px] text-ink-500 tracking-[0.25em] uppercase mb-2">Sınıflar</div>
          <ul className="space-y-1.5 text-[10px] leading-[15px]">
            <li><span className="text-ink-100">Mekanik</span> <span className="text-ink-400">— iki motor aynı şeyi ölçer (işlem sayısı, net getiri, kazanma oranı). Fark yalnızca komisyon/slippage/çıkış-zamanlaması kaynaklı olmalı. &lt;%1 PASS, &lt;%5 MINOR, <span className="text-down">&gt;%5 İNCELE = olası bug</span>.</span></li>
            <li><span className="text-ink-100">Modelleme</span> <span className="text-ink-400">— küçük metodoloji farkı (örn. drawdown LEAN'de bar-içi, bende kapanış-bazlı). Küçük sapma beklenir.</span></li>
            <li><span className="text-ink-100">Tanımsal</span> <span className="text-ink-400">— metrik tanımı farklı (Sharpe yıllıklama, Profit Factor vs Profit-Loss Ratio, $ vs % birim). Sapma BEKLENİR, bug değildir.</span></li>
          </ul>
        </div>
        <div className="bg-ink-850 border border-white/5 rounded p-3">
          <div className="text-[9px] text-ink-500 tracking-[0.25em] uppercase mb-2">Modelleme Notları</div>
          <ul className="space-y-1.5 text-[10px] leading-[15px] text-ink-400">
            <li><span className="text-ink-200">Funding/OI:</span> iki tarafta da modellenmez → tutarlı (rapor bunu varsayar).</li>
            <li><span className="text-ink-200">Slippage:</span> girişe referans (pre-slippage) fiyat verilir; slippage'ı LEAN uygular → çift sayım önlenir.</li>
            <li><span className="text-ink-200">Gating:</span> maxPositions / sembol-başına-tek / sermaye kısıtı LEAN tarafında da uygulanır.</li>
            <li><span className="text-ink-200">Fee:</span> Bybit futures → %0.02 maker / %0.055 taker, benim .env değerlerimle eşleşir.</li>
          </ul>
        </div>
      </div>

      {/* Nasil calistirilir */}
      <div className="bg-ink-850 border border-white/5 rounded p-3 mt-3">
        <div className="flex items-center gap-1.5 text-[9px] text-ink-500 tracking-[0.25em] uppercase mb-2">
          <Terminal size={11} /> Nasıl Çalıştırılır
        </div>
        <pre className="text-[10px] text-up bg-ink-900 border border-white/5 rounded p-3 overflow-x-auto leading-[16px]">
{`cd backend

# Docker yokken — boru hattı doğrulaması (stub LEAN istatistiği):
python -m lean_oracle.run --window 90d --symbols TOP10

# Gerçek LEAN motoru (lean CLI + Docker gerekir):
pip install -r tools/lean_oracle/requirements.txt
python -m lean_oracle.run --window 90d --symbols TOP10 --mode lean`}
        </pre>
        {!status?.dockerAvailable && (
          <p className="text-[10px] text-warn mt-2 leading-[15px]">
            Docker bu makinede kurulu değil. Gerçek LEAN motoruyla kıyas için Docker Desktop kurup başlatman gerekir;
            o zamana kadar <span className="text-ink-200">stub</span> modu boru hattını uçtan uca doğrular.
          </p>
        )}
      </div>
    </div>
  );
}
