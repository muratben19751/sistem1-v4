import { create } from 'zustand';
import { api } from '../lib/api';

export interface Alert {
  id: number;
  symbol: string;
  direction: string;
  signal_type: string | null;
  source_type: string;
  rsi_h1: number | null;
  rsi_h4: number | null;
  rsi_d1: number | null;
  rsi_1m: number | null;
  rsi_5m: number | null;
  srsi: number | null;
  srsi_1m: number | null;
  srsi_5m: number | null;
  srsi_1h: number | null;
  srsi_4h: number | null;
  srsi_1d: number | null;
  rsi_data: string | null;
  srsi_data: string | null;
  boost_value: number | null;
  price: number | null;
  previous_price: number | null;
  funding_rate: number | null;
  previous_funding: number | null;
  time_remaining: string | null;
  funding_changed: number;
  stars: number;
  raw_message: string | null;
  source: string | null;
  matched_with_bot: number;
  created_at: string;
}

interface AlertStats {
  total: number;
  matched: number;
  upCount: number;
  downCount: number;
  topSymbols: Array<{ symbol: string; cnt: number }>;
}

interface AlertStore {
  alerts: Alert[];
  stats: AlertStats | null;
  loading: boolean;
  filter: { symbol: string; direction: string };
  fetchAlerts: () => Promise<void>;
  fetchStats: () => Promise<void>;
  setFilter: (filter: Partial<{ symbol: string; direction: string }>) => void;
  addAlert: (alert: any) => void;
}

export const useAlertStore = create<AlertStore>((set, get) => ({
  alerts: [],
  stats: null,
  loading: false,
  filter: { symbol: '', direction: '' },

  fetchAlerts: async () => {
    set({ loading: true });
    try {
      const { symbol, direction } = get().filter;
      const params = new URLSearchParams();
      params.set('limit', '100');
      if (symbol) params.set('symbol', symbol);
      if (direction) params.set('direction', direction);
      const alerts = await api.get<Alert[]>(`/alerts?${params}`);
      set({ alerts, loading: false });
    } catch (err) {
      console.error('[alert-store] fetchAlerts failed:', err);
      set({ loading: false });
    }
  },

  fetchStats: async () => {
    try {
      const stats = await api.get<AlertStats>('/alerts/stats');
      set({ stats });
    } catch {}
  },

  setFilter: (filter) => {
    set((s) => ({ filter: { ...s.filter, ...filter } }));
    get().fetchAlerts();
  },

  addAlert: (alert) =>
    set((s) => ({
      alerts: [
        alert,
        ...s.alerts.filter((a) => a.id !== alert?.id),
      ].slice(0, 100),
    })),
}));
