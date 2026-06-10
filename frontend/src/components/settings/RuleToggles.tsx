import { useEffect, useState } from 'react';
import { useAccountStore } from '../../store/account-store';
import { api } from '../../lib/api';
import { ruleLabel } from '../../lib/rule-labels';
import { Save, Check } from 'lucide-react';

interface RuleInfo { key: string; name: string }

export default function RuleToggles() {
  const { accounts, activeAccountId, fetchAccounts } = useAccountStore();
  const [rules, setRules] = useState<RuleInfo[]>([]);
  const [selectedAccount, setSelectedAccount] = useState<number | null>(null);
  const [enabledRules, setEnabledRules] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.get<RuleInfo[]>('/analysis/rules').then(setRules).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedAccount && accounts.length > 0) setSelectedAccount(activeAccountId || accounts[0].id);
  }, [accounts, activeAccountId]);

  useEffect(() => {
    if (!selectedAccount || rules.length === 0) return;
    const acc = accounts.find((a) => a.id === selectedAccount);
    if (!acc) return;
    setEnabledRules(
      acc.enabled_rules === '__none__' ? new Set() :
      acc.enabled_rules ? new Set(acc.enabled_rules.split(',').filter(Boolean)) :
      new Set(rules.map((r) => r.key))
    );
  }, [selectedAccount, accounts, rules]);

  const toggleRule = (key: string) => {
    const next = new Set(enabledRules);
    if (next.has(key)) next.delete(key); else next.add(key);
    setEnabledRules(next);
  };

  const handleSave = async () => {
    if (!selectedAccount) return;
    setSaving(true);
    try {
      const allEnabled = rules.length > 0 && enabledRules.size === rules.length;
      const noneEnabled = enabledRules.size === 0;
      await api.put(`/accounts/${selectedAccount}/config`, {
        enabled_rules: allEnabled ? null : noneEnabled ? '__none__' : Array.from(enabledRules).join(','),
      });
      await fetchAccounts();
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch {}
    setSaving(false);
  };

  return (
    <div className="space-y-5">
      <div className="bg-ink-850 border border-white/5">
        <div className="h-10 bg-ink-850 border-b border-white/5 flex items-center px-4">
          <span className="text-[12px] tracking-[0.2em] text-ink-200 font-medium">SELECT BOT</span>
        </div>
        <div className="flex flex-wrap gap-2 p-4">
          {accounts.map((acc) => (
            <button key={acc.id} onClick={() => setSelectedAccount(acc.id)}
              className={`flex items-center gap-2.5 px-4 py-2.5 text-[13px] font-medium transition-colors border ${
                selectedAccount === acc.id
                  ? 'border-up/50 bg-up/10 text-up'
                  : 'border-white/5 bg-ink-800 text-ink-300 hover:border-white/10 hover:text-ink-100'
              }`}>
              <span className="w-3 h-3 rounded" style={{ backgroundColor: acc.color }} />
              {acc.name}
            </button>
          ))}
        </div>
      </div>

      {selectedAccount && (
        <div className="bg-ink-850 border border-white/5">
          <div className="h-10 bg-ink-850 border-b border-white/5 flex items-center justify-between px-4">
            <div className="flex items-center gap-4">
              <span className="text-[12px] tracking-[0.2em] text-ink-200 font-medium">STRATEGIES</span>
              <span className="text-[12px] text-ink-300 num">{enabledRules.size}/{rules.length} active</span>
            </div>
            <div className="flex items-center gap-3">
              <button onClick={() => setEnabledRules(new Set(rules.map((r) => r.key)))}
                className="text-[12px] text-up hover:text-up/80 transition-colors">Select All</button>
              <button onClick={() => setEnabledRules(new Set())}
                className="text-[12px] text-down hover:text-down/80 transition-colors">Clear All</button>
              <button onClick={handleSave} disabled={saving}
                className="flex items-center gap-1.5 bg-up/15 border border-up/30 text-up disabled:opacity-50 px-4 py-2 text-[12px] font-medium transition-colors hover:bg-up/25">
                {saved ? <Check size={14} /> : <Save size={14} />}
                {saved ? 'Saved' : saving ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
          <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-2">
            {rules.map((r) => {
              const on = enabledRules.has(r.key);
              return (
                <button key={r.key} onClick={() => toggleRule(r.key)}
                  className={`flex items-center gap-3 px-4 py-3.5 border text-left transition-colors ${
                    on ? 'border-up/30 bg-up/[0.07] text-ink-50' : 'border-white/5 bg-ink-800/50 text-ink-400'
                  }`}>
                  <span className={`w-5 h-5 rounded border-2 flex items-center justify-center flex-shrink-0 ${
                    on ? 'border-up bg-up' : 'border-ink-500'
                  }`}>
                    {on && <Check size={12} className="text-ink-900" />}
                  </span>
                  <span className="text-[13px] font-medium">{ruleLabel(r.key)}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
