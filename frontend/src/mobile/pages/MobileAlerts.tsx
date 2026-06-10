import { useEffect, useMemo, useState } from 'react';
import { useAlertStore } from '../../store/alert-store';
import { wsClient } from '../../lib/ws';
import AlertCardMobile from '../components/AlertCardMobile';

type SourceKey = 'sniper' | 'hammer' | 'fr' | 'm1_a';

const SOURCES: { key: SourceKey; label: string; db: string }[] = [
  { key: 'sniper', label: 'Sniper', db: '4s_sniper' },
  { key: 'hammer', label: 'Hammer', db: 'hammer' },
  { key: 'fr', label: 'FR', db: 'fr' },
  { key: 'm1_a', label: 'M1-A', db: 'm1_a' },
];

export default function MobileAlerts() {
  const { alerts, fetchAlerts, fetchStats, addAlert } = useAlertStore();
  const [active, setActive] = useState<Set<string>>(() => new Set(SOURCES.map((s) => s.db)));

  useEffect(() => {
    fetchAlerts();
    fetchStats();
    const unsub = wsClient.on('alert:received', (data) => {
      addAlert(data);
      fetchStats();
    });
    return () => unsub();
  }, [fetchAlerts, fetchStats, addAlert]);

  const toggle = (db: string) => {
    setActive((prev) => {
      const next = new Set(prev);
      if (next.has(db)) next.delete(db);
      else next.add(db);
      return next;
    });
  };

  const filtered = useMemo(() => alerts.filter((a) => active.has(a.source_type)), [alerts, active]);

  return (
    <div className="p-3 space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {SOURCES.map((s) => {
          const on = active.has(s.db);
          return (
            <button
              key={s.key}
              onClick={() => toggle(s.db)}
              className={`text-xs rounded-full px-3 min-h-[32px] border ${
                on ? 'bg-ink-700 border-white/10 text-ink-100' : 'border-white/5 text-ink-500'
              }`}
            >
              {s.label}
            </button>
          );
        })}
      </div>

      {filtered.length === 0 ? (
        <p className="text-center text-ink-500 text-sm py-12">Alert yok</p>
      ) : (
        <div className="space-y-2">
          {filtered.map((a) => <AlertCardMobile key={a.id} a={a} />)}
        </div>
      )}
    </div>
  );
}
