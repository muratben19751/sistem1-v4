import { create } from 'zustand';
import { api } from '../lib/api';

interface Position {
  id: number;
  account_id: number;
  symbol: string;
  side: string;
  size: number;
  entry_price: number;
  mark_price: number | null;
  leverage: number;
  unrealized_pnl: number;
  tp_price: number | null;
  sl_price: number | null;
  trailing_stop: number;
  opened_at: string;
}

interface PositionStore {
  positions: Position[];
  loading: boolean;
  fetchPositions: (accountId?: number | null) => Promise<void>;
  updatePosition: (symbol: string, data: Partial<Position>, side?: string, accountId?: number) => void;
  removePosition: (symbol: string, side?: string, accountId?: number) => void;
  addPosition: (pos: Position) => void;
  syncPrices: (priceOf: (symbol: string) => number | undefined) => void;
}

let latestPositionsRequest = 0;

export const usePositionStore = create<PositionStore>((set) => ({
  positions: [],
  loading: false,

  fetchPositions: async (accountId) => {
    const requestId = ++latestPositionsRequest;
    set({ loading: true });
    try {
      const url = accountId != null ? `/positions?accountId=${accountId}` : '/positions';
      const positions = await api.get<Position[]>(url);
      if (requestId === latestPositionsRequest) {
        set({ positions, loading: false });
      }
    } catch {
      if (requestId === latestPositionsRequest) {
        set({ loading: false });
      }
    }
  },

  updatePosition: (symbol, data, side, accountId) =>
    set((s) => {
      const definedData = Object.fromEntries(
        Object.entries(data).filter(([, value]) => value !== undefined),
      ) as Partial<Position>;
      return {
        positions: s.positions.map((p) => {
        if (p.symbol !== symbol) return p;
        if (side != null && p.side !== side) return p;
        if (accountId != null && p.account_id !== accountId) return p;
          return { ...p, ...definedData };
        }),
      };
    }),

  removePosition: (symbol, side, accountId) =>
    set((s) => ({
      positions: s.positions.filter((p) => {
        if (p.symbol !== symbol) return true;
        if (side != null && p.side !== side) return true;
        if (accountId != null && p.account_id !== accountId) return true;
        return false;
      }),
    })),

  addPosition: (pos) =>
    set((s) => ({ positions: [...s.positions, pos] })),

  syncPrices: (priceOf) =>
    set((s) => {
      let changed = false;
      const positions = s.positions.map((p) => {
        const live = priceOf(p.symbol);
        if (live == null || !Number.isFinite(live) || live <= 0 || live === p.mark_price) return p;
        const pnl = p.side === 'long'
          ? (live - p.entry_price) * p.size
          : (p.entry_price - live) * p.size;
        changed = true;
        return { ...p, mark_price: live, unrealized_pnl: pnl };
      });
      return changed ? { positions } : {};
    }),
}));
