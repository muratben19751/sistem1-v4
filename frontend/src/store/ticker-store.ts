import { create } from 'zustand';
import { api } from '../lib/api';

export interface TickerItem {
  symbol: string;
  lastPrice: number;
  change24h: number;
  volume24h: number;
  high24h: number;
  low24h: number;
  fundingRate: number;
}

interface TickerStore {
  tickers: TickerItem[];
  status: 'ok' | 'error' | 'loading';
  fetchTickers: () => Promise<void>;
}

export const useTickerStore = create<TickerStore>((set) => ({
  tickers: [],
  status: 'loading',

  fetchTickers: async () => {
    try {
      const data = await api.get<TickerItem[]>('/market/tickers');
      set({ tickers: data, status: 'ok' });
    } catch {
      set({ status: 'error' });
    }
  },
}));
