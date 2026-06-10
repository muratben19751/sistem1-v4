import { create } from 'zustand';
import { api } from '../lib/api';

export interface RuleLabel {
  rule_key: string;
  custom_name: string | null;
  custom_note: string | null;
  updated_at: string;
}

interface Store {
  overrides: Record<string, RuleLabel>;
  loading: boolean;
  fetch(): Promise<void>;
  set(key: string, name: string | null, note: string | null): Promise<void>;
  reset(key: string): Promise<void>;
  resetAll(): Promise<void>;
}

export const useRuleLabelsStore = create<Store>((set, get) => ({
  overrides: {},
  loading: false,

  async fetch() {
    set({ loading: true });
    try {
      const rows = await api.get<RuleLabel[]>('/rule-labels');
      const map: Record<string, RuleLabel> = {};
      for (const r of rows) map[r.rule_key] = r;
      set({ overrides: map, loading: false });
    } catch {
      set({ loading: false });
    }
  },

  async set(key, name, note) {
    await api.put(`/rule-labels/${encodeURIComponent(key)}`, { custom_name: name, custom_note: note });
    set({
      overrides: {
        ...get().overrides,
        [key]: { rule_key: key, custom_name: name, custom_note: note, updated_at: new Date().toISOString() },
      },
    });
  },

  async reset(key) {
    await api.delete(`/rule-labels/${encodeURIComponent(key)}`);
    const next = { ...get().overrides };
    delete next[key];
    set({ overrides: next });
  },

  async resetAll() {
    await api.delete('/rule-labels');
    set({ overrides: {} });
  },
}));

export function getOverrideName(key: string): string | null {
  return useRuleLabelsStore.getState().overrides[key]?.custom_name ?? null;
}

export function getOverrideNote(key: string): string | null {
  return useRuleLabelsStore.getState().overrides[key]?.custom_note ?? null;
}
