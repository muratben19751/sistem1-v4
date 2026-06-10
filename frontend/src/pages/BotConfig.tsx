import { useState, useEffect, useRef, useCallback } from 'react';
import { useAccountStore } from '../store/account-store';
import { useTradingStore } from '../store/trading-store';
import { usePositionStore } from '../store/position-store';
import { api } from '../lib/api';
import { ruleLabel } from '../lib/rule-labels';
import { Save, RotateCcw, Trash2, Plus, Check, Info, Loader2, DollarSign, Pencil, Star } from 'lucide-react';
import { RULES_DEFS, CATEGORY_COLORS, RuleModal } from '../lib/rule-defs';
import type { RuleDef } from '../lib/rule-defs';

interface RuleInfo { key: string; name: string; sources?: string[] }

export default function BotConfig() {
  const { accounts, fetchAccounts, activeAccountId } = useAccountStore();
  const fetchTrades = useTradingStore((s) => s.fetchTrades);
  const fetchPositions = usePositionStore((s) => s.fetchPositions);
  const [selectedId, setSelectedId] = useState<number | null>(activeAccountId);
  const [creating, setCreating] = useState(false);
  useEffect(() => { setSelectedId(activeAccountId); }, [activeAccountId]);

  const resolvedId = selectedId != null && accounts.some((a) => a.id === selectedId)
    ? selectedId
    : (accounts[0]?.id ?? null);
  const selected = accounts.find((a) => a.id === resolvedId);
  const selectedIsPaper = selected ? selected.type !== 'real' && selected.engine !== 'bybit' : false;

  return (
    <div className="flex flex-col h-full">
      <div className="h-9 bg-ink-850 border-b border-white/5 flex items-center px-4 justify-between">
        <span className="text-[9px] tracking-[0.3em] text-ink-400 uppercase">[ BOT CONFIG ]</span>
        <button onClick={() => setCreating(true)}
          className="flex items-center gap-1.5 text-[11px] text-up hover:text-up/80 transition-colors">
          <Plus size={12} /> New Bot
        </button>
      </div>

      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-white/5">
        <select
          value={resolvedId ?? ''}
          onChange={(e) => { setSelectedId(parseInt(e.target.value)); setCreating(false); }}
          className="flex-1 bg-ink-800 text-ink-50 text-[13px] px-3 py-2 border border-white/5 focus:outline-none focus:border-white/20"
        >
          {accounts.map((acc) => (
            <option key={acc.id} value={acc.id}>{acc.name}</option>
          ))}
        </select>
      </div>

      <div className="flex-1 overflow-y-auto">
        {creating ? (
          <BotForm
            onClose={() => setCreating(false)}
            onSaved={() => { setCreating(false); fetchAccounts(); }}
          />
        ) : selected ? (
          <>
            <BotForm
              key={selected.id}
              account={selected}
              onClose={() => {}}
              onSaved={() => fetchAccounts()}
              onReset={selectedIsPaper ? async () => {
                if (!confirm(`"${selected.name}" sifirlansin mi? Cuzdan, pozisyonlar ve equity sifirlanir; bot adi bosaltilir.`)) return;
                const clearTrades = confirm('Trade gecmisini de sil?\n\nEvet = arsivlenip (ayri tutulur) temizlenir.\nHayir = trade gecmisi korunur.');
                await api.post(`/accounts/${selected.id}/reset`, { clearTrades });
                await fetchAccounts();
                await fetchTrades(selected.id, 500);
                await fetchPositions(selected.id);
              } : undefined}
              onSetDefault={!selected.is_default ? async () => {
                await api.post(`/accounts/${selected.id}/default`);
                await fetchAccounts();
              } : undefined}
              onDelete={selectedIsPaper ? async () => {
                if (!confirm(`"${selected.name}" silinsin mi?${selected.is_default ? ' (Varsayilan baska hesaba tasinacak.)' : ''}`)) return;
                await api.delete(`/accounts/${selected.id}`);
                setSelectedId(null);
                await fetchAccounts();
              } : undefined}
            />
            <RulesPanel accountId={selected.id} />
          </>
        ) : (
          <div className="flex items-center justify-center h-full text-ink-400 text-[12px]">Bir bot secin</div>
        )}
      </div>
    </div>
  );
}

function RulesPanel({ accountId }: { accountId: number }) {
  const fetchAccounts = useAccountStore((s) => s.fetchAccounts);
  const [rules, setRules] = useState<RuleInfo[]>([]);
  const [enabledRules, setEnabledRules] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [modalRule, setModalRule] = useState<RuleDef | null>(null);
  const mounted = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    api.get<RuleInfo[]>('/analysis/rules').then(setRules).catch(() => {});
  }, []);

  // Sadece hesap secimi (accountId) degisince sifirla; her WS kaynakli accounts
  // yenilemesinde sifirlamak kaydedilmemis toggle'lari ve bekleyen autosave'i ezerdi.
  useEffect(() => {
    if (rules.length === 0) return;
    const acc = useAccountStore.getState().accounts.find((a) => a.id === accountId) as any;
    if (!acc) return;
    setEnabledRules(
      acc.enabled_rules === '__none__' ? new Set() :
      acc.enabled_rules ? new Set(acc.enabled_rules.split(',')) :
      new Set(rules.map((r) => r.key))
    );
    mounted.current = false;
  }, [accountId, rules]);

  const toggleRule = (key: string) => {
    const next = new Set(enabledRules);
    if (next.has(key)) next.delete(key); else next.add(key);
    setEnabledRules(next);
  };

  const doSave = useCallback(async () => {
    setSaving(true);
    try {
      const allEnabled = enabledRules.size === rules.length;
      const noneEnabled = enabledRules.size === 0;
      await api.put(`/accounts/${accountId}/config`, {
        enabled_rules: allEnabled ? null : noneEnabled ? '__none__' : Array.from(enabledRules).join(','),
      });
      await fetchAccounts();
      setSaved(true);
      setTimeout(() => setSaved(false), 1200);
    } catch {}
    setSaving(false);
  }, [enabledRules, rules, accountId]);

  useEffect(() => {
    if (!mounted.current) { mounted.current = true; return; }
    if (rules.length === 0) return;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(doSave, 600);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [enabledRules]);

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-ink-300 num">{enabledRules.size}/{rules.length} active</span>
          {saving && <Loader2 size={10} className="animate-spin text-ink-400" />}
          {saved && <span className="text-[9px] text-up font-medium">SAVED</span>}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setEnabledRules(new Set(rules.map((r) => r.key)))}
            className="text-[10px] text-up hover:text-up/80 transition-colors">All</button>
          <button onClick={() => setEnabledRules(new Set())}
            className="text-[10px] text-down hover:text-down/80 transition-colors">Clear</button>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-1.5">
        {rules.map((r) => {
          const on = enabledRules.has(r.key);
          const def = RULES_DEFS.find((d) => d.key === r.key);
          const catClass = def ? (CATEGORY_COLORS[def.category] || '') : '';
          return (
            <div key={r.key} className={`flex items-center border transition-colors ${
              on ? 'border-up/30 bg-up/[0.07]' : 'border-white/5 bg-ink-800/50'
            }`}>
              <button onClick={() => toggleRule(r.key)}
                className="flex items-center gap-2.5 px-3 py-2 flex-1 min-w-0 text-left">
                <span className={`w-4 h-4 rounded border-2 flex items-center justify-center flex-shrink-0 ${
                  on ? 'border-up bg-up' : 'border-ink-500'
                }`}>
                  {on && <Check size={10} className="text-ink-900" />}
                </span>
                <span className={`text-[11px] font-medium truncate ${on ? 'text-ink-50' : 'text-ink-400'}`}>
                  {ruleLabel(r.key)}
                </span>
              </button>
              <div className="flex items-center gap-1.5 pr-3 shrink-0">
                {def && (
                  <span className={`px-1.5 py-0.5 text-[8px] tracking-wider border ${catClass}`}>
                    {def.category.toUpperCase()}
                  </span>
                )}
                {def && (
                  <button onClick={() => setModalRule(def)}
                    className="text-ink-500 hover:text-info transition-colors p-0.5 ml-1">
                    <Info size={13} />
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {modalRule && <RuleModal rule={modalRule} onClose={() => setModalRule(null)} />}
    </div>
  );
}

function BotForm({ account, onClose, onSaved, onReset, onDelete, onSetDefault }: {
  account?: any; onClose: () => void; onSaved: (newId?: number) => void; onReset?: () => void; onDelete?: () => void; onSetDefault?: () => void;
}) {
  const [form, setForm] = useState({
    name: account?.name || '',
    color: account?.color || '#3b82f6',
    initial_balance: account?.initial_balance || 10000,
    long_min_score: account?.long_min_score ?? 4,
    short_min_score: account?.short_min_score ?? -4,
    leverage: account?.bot_leverage || 2,
    max_positions: account?.max_positions ?? 5,
    tp_percent: account?.tp_percent ?? 5,
    sl_percent: account?.sl_percent ?? 3,
    max_drawdown: account?.max_drawdown || 30,
    max_drawdown_enabled: account?.max_drawdown_enabled ?? 0,
    scan_interval: account?.scan_interval || 30,
    trailing_percent: account?.trailing_percent || 1,
    trailing_stop: account?.trailing_stop ?? 0,
    signal_source: account?.signal_source || 'scanner',
    alert_freshness_minutes: account?.alert_freshness_minutes || 30,
    alert_score_boost: account?.alert_score_boost ?? 2.0,
    position_size_pct: account?.position_size_pct ?? 2,
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [equityEdit, setEquityEdit] = useState(false);
  const [equityValue, setEquityValue] = useState(account?.available_balance ?? account?.wallet_balance ?? account?.balance ?? account?.initial_balance ?? 10000);
  const [accountType, setAccountType] = useState<'paper' | 'demo'>('paper');
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [credentialSaving, setCredentialSaving] = useState(false);
  const [credentialSaved, setCredentialSaved] = useState(false);
  const [credentialError, setCredentialError] = useState('');
  const mounted = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    if (!mounted.current) { mounted.current = true; return; }
    if (!account) return;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(async () => {
      setSaving(true);
      try {
        await api.put(`/accounts/${account.id}/config`, {
          name: form.name, color: form.color,
          long_min_score: form.long_min_score, short_min_score: form.short_min_score,
          leverage: form.leverage, max_positions: form.max_positions,
          tp_percent: form.tp_percent, sl_percent: form.sl_percent,
          max_drawdown: form.max_drawdown, max_drawdown_enabled: form.max_drawdown_enabled,
          scan_interval: form.scan_interval,
          trailing_percent: form.trailing_percent,
          trailing_stop: form.trailing_stop,
          position_size_pct: form.position_size_pct,
          signal_source: form.signal_source,
          alert_freshness_minutes: form.alert_freshness_minutes,
          alert_score_boost: form.alert_score_boost,
        });
        onSaved();
        setSaveError('');
        setSaved(true);
        setTimeout(() => setSaved(false), 1200);
      } catch (e) {
        console.error('Bot config kaydedilemedi:', e);
        setSaveError('KAYIT HATASI');
      }
      setSaving(false);
    }, 600);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [form]);

  const handleCreate = async () => {
    setSaving(true);
    try {
      const isDemo = accountType === 'demo';
      const res = await api.post<{ accountId: number }>('/accounts', {
        name: form.name,
        type: accountType,
        engine: isDemo ? 'demo' : 'paper',
        balance: form.initial_balance, leverage: form.leverage, color: form.color,
        ...(isDemo ? { apiKey: apiKey.trim(), apiSecret: apiSecret.trim() } : {}),
      });
      onSaved(res.accountId);
    } catch {}
    setSaving(false);
  };

  const handleCredentialUpdate = async () => {
    if (!account || !apiKey.trim() || !apiSecret.trim()) return;
    setCredentialSaving(true);
    setCredentialError('');
    try {
      await api.put(`/accounts/${account.id}/credentials`, {
        apiKey: apiKey.trim(),
        apiSecret: apiSecret.trim(),
      });
      setApiKey('');
      setApiSecret('');
      setCredentialSaved(true);
      onSaved();
      setTimeout(() => setCredentialSaved(false), 1500);
    } catch {
      setCredentialError('Credential update failed');
    } finally {
      setCredentialSaving(false);
    }
  };

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] text-ink-300 tracking-[0.2em]">GENERAL</span>
        <div className="flex items-center gap-2">
          {saving && <Loader2 size={12} className="animate-spin text-ink-400" />}
          {saved && <span className="text-[9px] text-up font-medium tracking-wider">SAVED</span>}
          {saveError && !saving && <span className="text-[9px] text-down font-medium tracking-wider">{saveError}</span>}
          {!account && (
            <>
              <button onClick={handleCreate} disabled={saving || !form.name || (accountType === 'demo' && (!apiKey.trim() || !apiSecret.trim()))}
                className="flex items-center gap-1.5 bg-up/15 border border-up/30 text-up disabled:opacity-50 px-3 py-1.5 text-[10px] font-medium transition-colors hover:bg-up/25">
                <Save size={12} /> Create
              </button>
              <button onClick={onClose} className="text-[10px] text-ink-300 hover:text-ink-100 px-3 py-1.5 transition-colors">Cancel</button>
            </>
          )}
          {onReset && (
            <button onClick={onReset}
              className="flex items-center gap-1.5 text-[10px] text-amber-400 px-3 py-1.5 bg-ink-800 border border-white/5 hover:border-white/10 transition-colors">
              <RotateCcw size={11} /> Reset
            </button>
          )}
          {onSetDefault && (
            <button onClick={onSetDefault}
              className="flex items-center gap-1.5 text-[10px] text-info px-3 py-1.5 bg-ink-800 border border-white/5 hover:border-white/10 transition-colors">
              <Star size={11} /> Varsayilan Yap
            </button>
          )}
          {onDelete && (
            <button onClick={onDelete}
              className="flex items-center gap-1.5 text-[10px] text-down px-3 py-1.5 bg-ink-800 border border-white/5 hover:border-white/10 transition-colors">
              <Trash2 size={11} /> Delete
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5">
        <ConfigCard label="NAME">
          <input type="text" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="w-full bg-transparent text-ink-50 text-[12px] focus:outline-none num" />
        </ConfigCard>
        <ConfigCard label="COLOR">
          <div className="flex items-center gap-2">
            <input type="color" value={form.color} onChange={(e) => setForm({ ...form, color: e.target.value })}
              className="w-6 h-6 border border-white/10 cursor-pointer bg-transparent rounded" />
            <span className="text-[11px] text-ink-200 num">{form.color}</span>
          </div>
        </ConfigCard>
        {!account && (
          <NumCard label="INITIAL BALANCE" value={form.initial_balance} onChange={(v) => setForm({ ...form, initial_balance: v })} min={100} step={1000} suffix="$" />
        )}
        {!account && (
          <ConfigCard label="ACCOUNT TYPE">
            <select value={accountType} onChange={(e) => setAccountType(e.target.value as 'paper' | 'demo')}
              className="w-full bg-transparent text-ink-50 text-[12px] focus:outline-none">
              <option value="paper" className="bg-ink-800">Paper (sanal cuzdan)</option>
              <option value="demo" className="bg-ink-800">Bybit Demo (api-demo)</option>
            </select>
          </ConfigCard>
        )}
        {!account && accountType === 'demo' && (
          <>
            <ConfigCard label="DEMO API KEY">
              <input type="text" value={apiKey} onChange={(e) => setApiKey(e.target.value)} autoComplete="off"
                className="w-full bg-transparent text-ink-50 text-[12px] focus:outline-none num" />
            </ConfigCard>
            <ConfigCard label="DEMO API SECRET">
              <input type="password" value={apiSecret} onChange={(e) => setApiSecret(e.target.value)} autoComplete="off"
                className="w-full bg-transparent text-ink-50 text-[12px] focus:outline-none num" />
            </ConfigCard>
          </>
        )}
        {account && account.engine === 'demo' && account.credentials_valid === 0 && (
          <div className="md:col-span-2 border border-down/30 bg-down/5 p-3 space-y-2">
            <div className="text-[10px] text-down tracking-wider">
              ENCRYPTED API CREDENTIALS CANNOT BE DECRYPTED. RE-ENTER THEM TO RE-ENABLE THIS ACCOUNT.
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5">
              <ConfigCard label="DEMO API KEY">
                <input type="text" value={apiKey} onChange={(e) => setApiKey(e.target.value)}
                  autoComplete="off" className="w-full bg-transparent text-ink-50 text-[12px] focus:outline-none num" />
              </ConfigCard>
              <ConfigCard label="DEMO API SECRET">
                <input type="password" value={apiSecret} onChange={(e) => setApiSecret(e.target.value)}
                  autoComplete="off" className="w-full bg-transparent text-ink-50 text-[12px] focus:outline-none num" />
              </ConfigCard>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={handleCredentialUpdate}
                disabled={credentialSaving || !apiKey.trim() || !apiSecret.trim()}
                className="flex items-center gap-1.5 bg-up/15 border border-up/30 text-up disabled:opacity-50 px-3 py-1.5 text-[10px] font-medium">
                {credentialSaving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                Update Credentials
              </button>
              {credentialSaved && <span className="text-[10px] text-up">Updated</span>}
              {credentialError && <span className="text-[10px] text-down">{credentialError}</span>}
            </div>
          </div>
        )}
        {account && account.type !== 'real' && account.engine !== 'bybit' && account.engine !== 'demo' && (
          <div className="flex items-center justify-between border border-white/5 bg-ink-800/50 px-3 py-2 md:col-span-2">
            <div className="flex items-center gap-2">
              <DollarSign size={12} className="text-ink-400" />
              <span className="text-[10px] text-ink-300 tracking-wider">AVAILABLE BALANCE</span>
            </div>
            {equityEdit ? (
              <div className="flex items-center gap-2">
                <input type="number" value={equityValue} onChange={(e) => setEquityValue(parseFloat(e.target.value) || 0)}
                  min={0} step={100}
                  className="w-28 bg-ink-700 text-ink-50 text-[12px] num focus:outline-none text-right px-2 py-1 border border-white/10" autoFocus />
                <span className="text-[10px] text-ink-400">$</span>
                <button onClick={async () => {
                  await api.put(`/accounts/${account.id}/equity`, { balance: equityValue });
                  onSaved();
                  setEquityEdit(false);
                }}
                  className="text-[10px] text-up px-2 py-1 bg-up/10 border border-up/30 hover:bg-up/20 transition-colors">Set</button>
                <button onClick={() => { setEquityValue(account.available_balance ?? account.wallet_balance ?? account.balance ?? account.initial_balance); setEquityEdit(false); }}
                  className="text-[10px] text-ink-400 hover:text-ink-200 transition-colors">Cancel</button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <span className="text-[13px] text-ink-50 num">${(account.available_balance ?? account.wallet_balance ?? account.balance ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                <button onClick={() => { setEquityValue(account.available_balance ?? account.wallet_balance ?? account.balance ?? account.initial_balance); setEquityEdit(true); }}
                  className="text-ink-500 hover:text-info transition-colors p-0.5">
                  <Pencil size={11} />
                </button>
              </div>
            )}
          </div>
        )}
        <NumCard label="LONG MIN SCORE" value={form.long_min_score} onChange={(v) => setForm({ ...form, long_min_score: v })} step={0.5} />
        <NumCard label="SHORT MIN SCORE" value={form.short_min_score} onChange={(v) => setForm({ ...form, short_min_score: v })} step={0.5} />
        <NumCard label="LEVERAGE" value={form.leverage} onChange={(v) => setForm({ ...form, leverage: v })} min={1} max={50} step={1} suffix="x" />
        <NumCard label="MAX POSITIONS" value={form.max_positions} onChange={(v) => setForm({ ...form, max_positions: v })} min={1} max={20} step={1} />
        <NumCard label="TP PRICE %" value={form.tp_percent} onChange={(v) => setForm({ ...form, tp_percent: v })} step={0.5} suffix="%" />
        <NumCard label="SL PRICE %" value={form.sl_percent} onChange={(v) => setForm({ ...form, sl_percent: v })} step={0.5} suffix="%" />
        <button
          type="button"
          onClick={() => setForm({ ...form, max_drawdown_enabled: form.max_drawdown_enabled ? 0 : 1 })}
          title="Max drawdown devre kesicisini etkinlestir/devre disi birak. Acik oldugunda drawdown limiti asilirsa yeni pozisyon acilmaz."
          className={`flex flex-col justify-center px-3 py-2 rounded border text-left transition-colors ${form.max_drawdown_enabled ? 'border-up/40 bg-up/10' : 'border-white/10 bg-ink-850 hover:border-white/20'}`}
        >
          <span className="text-[9px] tracking-[0.2em] text-ink-400 uppercase">Max Drawdown</span>
          <span className={`text-[13px] font-semibold ${form.max_drawdown_enabled ? 'text-up' : 'text-ink-500'}`}>{form.max_drawdown_enabled ? 'ACIK' : 'KAPALI'}</span>
        </button>
        {!!form.max_drawdown_enabled && (
          <NumCard label="MAX DRAWDOWN %" value={form.max_drawdown} onChange={(v) => setForm({ ...form, max_drawdown: v })} step={1} suffix="%" />
        )}
        <NumCard label="SCAN INTERVAL" value={form.scan_interval} onChange={(v) => setForm({ ...form, scan_interval: v })} min={5} step={5} suffix="s" />
        <NumCard label="POSITION SIZE" value={form.position_size_pct} onChange={(v) => setForm({ ...form, position_size_pct: v })} min={0.5} max={100} step={0.5} suffix="%" />
        <NumCard label="TRAILING %" value={form.trailing_percent} onChange={(v) => setForm({ ...form, trailing_percent: v })} step={0.5} suffix="%" />
        <button
          type="button"
          onClick={() => setForm({ ...form, trailing_stop: form.trailing_stop ? 0 : 1 })}
          title="Trailing stop'u etkinlestir/devre disi birak. Acik oldugunda yeni pozisyonlarda trailing % uygulanir."
          className={`flex flex-col justify-center px-3 py-2 rounded border text-left transition-colors ${form.trailing_stop ? 'border-up/40 bg-up/10' : 'border-white/10 bg-ink-850 hover:border-white/20'}`}
        >
          <span className="text-[9px] tracking-[0.2em] text-ink-400 uppercase">Trailing Stop</span>
          <span className={`text-[13px] font-semibold ${form.trailing_stop ? 'text-up' : 'text-ink-500'}`}>{form.trailing_stop ? 'ACIK' : 'KAPALI'}</span>
        </button>
      </div>

      <div className="mt-4 mb-2">
        <span className="text-[10px] text-ink-300 tracking-[0.2em]">SIGNAL SOURCE</span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5">
        <ConfigCard label="SOURCE">
          <select value={form.signal_source} onChange={(e) => setForm({ ...form, signal_source: e.target.value })}
            className="w-full bg-transparent text-ink-50 text-[12px] focus:outline-none cursor-pointer">
            <option value="scanner">Scanner (top gainers)</option>
            <option value="hammer">Hammer alerts only</option>
            <option value="sniper">Sniper alerts only</option>
            <option value="fr">FR alerts only</option>
            <option value="m1_a">M1-A alerts only</option>
            <option value="v3_a">V3-A alerts only</option>
            <option value="hammer+sniper">Hammer + Sniper</option>
            <option value="hammer+fr">Hammer + FR</option>
            <option value="sniper+fr">Sniper + FR</option>
            <option value="hammer+sniper+fr+m1_a">Hammer + Sniper + FR + M1-A</option>
            <option value="scanner+hammer">Scanner + Hammer boost</option>
            <option value="scanner+sniper">Scanner + Sniper boost</option>
            <option value="scanner+fr">Scanner + FR boost</option>
            <option value="scanner+m1_a">Scanner + M1-A boost</option>
            <option value="scanner+v3_a">Scanner + V3-A boost</option>
            <option value="hammer+sniper+fr">Hammer + Sniper + FR</option>
            <option value="scanner+hammer+sniper+fr">Scanner + H + S + FR</option>
            <option value="scanner+hammer+sniper+fr+m1_a">Scanner + H + S + FR + M1-A</option>
            <option value="all">All sources</option>
          </select>
        </ConfigCard>
        {form.signal_source !== 'scanner' && (
          <NumCard label="ALERT FRESHNESS" value={form.alert_freshness_minutes}
            onChange={(v) => setForm({ ...form, alert_freshness_minutes: v })} min={5} max={120} step={5} suffix="min" />
        )}
        {form.signal_source.includes('+') && (
          <NumCard label="ALERT SCORE BOOST" value={form.alert_score_boost}
            onChange={(v) => setForm({ ...form, alert_score_boost: v })} min={0} max={10} step={0.5} />
        )}
      </div>
    </div>
  );
}

function ConfigCard({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between border border-white/5 bg-ink-800/50 px-3 py-2">
      <span className="text-[10px] text-ink-300 tracking-wider">{label}</span>
      {children}
    </div>
  );
}

function NumCard({ label, value, onChange, min, max, step = 1, suffix }: {
  label: string; value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; suffix?: string;
}) {
  // Ham girdi yerel string olarak tutulur: alan bosken/yarimken 0 autosave edilmesin
  const [text, setText] = useState(String(value));
  const focused = useRef(false);
  useEffect(() => { if (!focused.current) setText(String(value)); }, [value]);
  return (
    <div className="flex items-center justify-between border border-white/5 bg-ink-800/50 px-3 py-2">
      <span className="text-[10px] text-ink-300 tracking-wider">{label}</span>
      <div className="flex items-center gap-1">
        <input type="number" value={text}
          onFocus={() => { focused.current = true; }}
          onChange={(e) => {
            setText(e.target.value);
            const v = parseFloat(e.target.value);
            if (Number.isFinite(v)) onChange(v); // sadece gecerli sayi yayilir/kaydedilir
          }}
          onBlur={(e) => {
            focused.current = false;
            if (!Number.isFinite(parseFloat(e.target.value))) setText(String(value)); // bos/gecersiz -> son gecerli degere don
          }}
          min={min} max={max} step={step}
          className="w-20 bg-transparent text-ink-50 text-[12px] num focus:outline-none text-right" />
        {suffix && <span className="text-[10px] text-ink-400">{suffix}</span>}
      </div>
    </div>
  );
}
