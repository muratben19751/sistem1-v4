import { create } from 'zustand';
import { api } from '../lib/api';

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
  entry_fr?: number | null;
}

interface TradeMetrics {
  realizedPnl: number;
  fees: number;
  closedTrades: number;
}

interface TradingStore {
  trades: Trade[];
  metrics24h: TradeMetrics;
  loading: boolean;
  fetchTrades: (accountId?: number | null, limit?: number, withFr?: boolean) => Promise<void>;
  fetchMetrics24h: (accountId?: number | null) => Promise<void>;
}

let latestTradesRequest = 0;
let latestMetricsRequest = 0;

export const useTradingStore = create<TradingStore>((set) => ({
  trades: [],
  metrics24h: { realizedPnl: 0, fees: 0, closedTrades: 0 },
  loading: false,

  fetchTrades: async (accountId, limit = 100, withFr = false) => {
    const requestId = ++latestTradesRequest;
    set({ loading: true });
    try {
      const fr = withFr ? '&withFr=1' : '';
      const url = accountId != null
        ? `/trades?accountId=${accountId}&limit=${limit}${fr}`
        : `/trades?limit=${limit}${fr}`;
      const trades = await api.get<Trade[]>(url);
      if (requestId === latestTradesRequest) {
        set({ trades, loading: false });
      }
    } catch {
      if (requestId === latestTradesRequest) {
        set({ loading: false });
      }
    }
  },

  fetchMetrics24h: async (accountId) => {
    const requestId = ++latestMetricsRequest;
    const accountParam = accountId == null ? '' : `&accountId=${accountId}`;
    try {
      const metrics24h = await api.get<TradeMetrics>(`/trades/metrics?hours=24${accountParam}`);
      if (requestId === latestMetricsRequest) {
        set({ metrics24h });
      }
    } catch {
      if (requestId === latestMetricsRequest) {
        set({ metrics24h: { realizedPnl: 0, fees: 0, closedTrades: 0 } });
      }
    }
  },
}));
