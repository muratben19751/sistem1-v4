import { useState } from 'react';
import { Search, ArrowUp, ArrowDown, Loader2 } from 'lucide-react';
import { useAccountStore } from '../../store/account-store';
import { usePositionStore } from '../../store/position-store';
import { api } from '../../lib/api';
import { ruleLabel } from '../../lib/rule-labels';
import { placeManualOrder, orderNotional } from '../../lib/trading-actions';
import { formatUsd } from '../../lib/formatters';
import type { SignalResult } from '../../types';

export default function OrderSheet() {
  const { activeAccountId, fetchAccounts } = useAccountStore();
  const account = useAccountStore((s) => s.accounts.find((a) => a.id === s.activeAccountId));
  const fetchPositions = usePositionStore((s) => s.fetchPositions);

  const [input, setInput] = useState('');
  const [signal, setSignal] = useState<SignalResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [ordering, setOrdering] = useState(false);
  const [msg, setMsg] = useState<{ text: string; tone: 'ok' | 'err' } | null>(null);

  const analyze = async (sym: string) => {
    setSignal(null);
    setMsg(null);
    setAnalyzing(true);
    try {
      const params = activeAccountId ? `?accountId=${encodeURIComponent(String(activeAccountId))}` : '';
      setSignal(await api.get<SignalResult>(`/analysis/analyze/${encodeURIComponent(sym)}${params}`));
    } catch {
      setMsg({ text: 'Analiz başarısız', tone: 'err' });
    }
    setAnalyzing(false);
  };

  const onSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const clean = input.trim().toUpperCase();
    if (!clean) return;
    analyze(clean.endsWith('USDT') ? clean : clean + 'USDT');
  };

  const order = async (side: 'long' | 'short') => {
    if (!signal || ordering) return;
    if (!activeAccountId || !account) {
      setMsg({ text: 'İşlem için belirli bir hesap seçin', tone: 'err' });
      return;
    }
    const minLong = account.long_min_score ?? 4;
    const minShort = account.short_min_score ?? -4;
    const passes = side === 'long' ? signal.totalScore >= minLong : signal.totalScore <= minShort;
    if (!passes) {
      const thresh = side === 'long' ? minLong : minShort;
      const ok = window.confirm(
        `Skor ${signal.totalScore.toFixed(2)}, ${side.toUpperCase()} eşiği ${thresh}.\nBot bu sinyali açmazdı. Yine de manuel açmak istiyor musun?`,
      );
      if (!ok) return;
    }
    setMsg(null);
    setOrdering(true);
    try {
      await placeManualOrder(activeAccountId, account, signal, side);
      await fetchAccounts();
      await fetchPositions(activeAccountId);
      setMsg({ text: `${signal.symbol} ${side.toUpperCase()} açıldı`, tone: 'ok' });
      setSignal(null);
      setInput('');
    } catch (err: any) {
      setMsg({ text: err?.message || 'Emir başarısız', tone: 'err' });
    }
    setOrdering(false);
  };

  const noAccount = !activeAccountId;
  const notional = account ? orderNotional(account) : 0;

  return (
    <div className="rounded-md border border-white/5 bg-ink-850 p-3">
      <form onSubmit={onSearch} className="flex items-center gap-2">
        <div className="flex-1 flex items-center gap-2 bg-ink-800 border border-white/10 rounded px-3 min-h-[44px]">
          <Search size={16} className="text-ink-500" />
          <input
            value={input}
            onChange={(e) => setInput(e.target.value.toUpperCase())}
            placeholder="Sembol (örn BTC)"
            autoCapitalize="characters"
            autoCorrect="off"
            className="flex-1 bg-transparent outline-none text-sm text-ink-100 placeholder:text-ink-500"
          />
        </div>
        <button
          type="submit"
          disabled={!input.trim() || analyzing}
          className="shrink-0 text-sm text-ink-100 border border-white/10 rounded px-4 min-h-[44px] disabled:opacity-50 active:bg-white/5"
        >
          {analyzing ? <Loader2 size={16} className="animate-spin" /> : 'Analiz'}
        </button>
      </form>

      {noAccount && (
        <p className="mt-2 text-[11px] text-warn">İşlem için üstten belirli bir hesap seç (Tüm Hesaplar'da emir verilemez).</p>
      )}

      {msg && (
        <p className={`mt-2 text-xs ${msg.tone === 'ok' ? 'text-up' : 'text-down'}`}>{msg.text}</p>
      )}

      {signal && !analyzing && (
        <div className="mt-3">
          <div className="flex items-center justify-between">
            <span className="text-base font-semibold text-ink-50">{signal.symbol}</span>
            <span className={`text-2xl font-bold num ${signal.totalScore > 0 ? 'text-up' : signal.totalScore < 0 ? 'text-down' : 'text-ink-400'}`}>
              {signal.totalScore > 0 ? '+' : ''}{signal.totalScore.toFixed(1)}
            </span>
          </div>
          <div className="mt-0.5 text-[11px] text-ink-400">
            {account && <>İşlem büyüklüğü ≈ {formatUsd(notional)} · {account.bot_leverage || 2}x · TP {account.tp_percent || 5}% / SL {account.sl_percent || 3}%</>}
          </div>

          <div className="mt-3 grid grid-cols-2 gap-2">
            <button
              onClick={() => order('long')}
              disabled={ordering || noAccount}
              className="flex items-center justify-center gap-1.5 bg-up/15 border border-up/30 text-up rounded min-h-[48px] text-sm font-medium disabled:opacity-50 active:bg-up/25"
            >
              <ArrowUp size={16} /> LONG
            </button>
            <button
              onClick={() => order('short')}
              disabled={ordering || noAccount}
              className="flex items-center justify-center gap-1.5 bg-down/15 border border-down/30 text-down rounded min-h-[48px] text-sm font-medium disabled:opacity-50 active:bg-down/25"
            >
              <ArrowDown size={16} /> SHORT
            </button>
          </div>

          <div className="mt-3 grid grid-cols-2 gap-1">
            {signal.rules.filter((r) => r.score !== 0).map((r) => (
              <div
                key={r.key}
                className={`flex justify-between px-2 py-1.5 text-[11px] rounded border ${
                  r.score > 0 ? 'bg-up/[0.05] border-up/10' : 'bg-down/[0.05] border-down/10'
                }`}
              >
                <span className="text-ink-400 truncate mr-2">{ruleLabel(r.key)}</span>
                <span className={`num font-medium shrink-0 ${r.score > 0 ? 'text-up' : 'text-down'}`}>
                  {r.score > 0 ? '+' : ''}{r.score}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
