import { create } from 'zustand';
import { api } from '../lib/api';

interface Account {
  id: number;
  name: string;
  type: string;
  strategy: string;
  balance: number;
  initial_balance: number;
  leverage: number;
  color: string;
  is_default: number;
  wallet_balance: number;
  available_balance: number;
  account_equity: number;
  reserved_margin: number;
  open_unrealized_pnl: number;
  total_pnl: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  long_min_score: number;
  short_min_score: number;
  bot_leverage: number;
  max_positions: number;
  tp_percent: number;
  sl_percent: number;
  max_drawdown: number;
  max_drawdown_enabled: number;
  peak_equity?: number;
  current_drawdown?: number;
  max_drawdown_realized?: number;
  wr_scalp?: number;
  n_scalp?: number;
  wr_swing?: number;
  n_swing?: number;
  wr_manual?: number;
  n_manual?: number;
  scan_interval: number;
  trailing_stop: number;
  trailing_percent: number;
  enabled_rules: string | null;
  rule_sources: string | null;
  signal_source: string;
  alert_freshness_minutes: number;
  alert_score_boost: number;
  position_size_pct: number;
  bot_enabled?: number;
  engine: string;
  has_api_credentials: number;
  credentials_valid?: number | null;
  created_at: string;
  updated_at: string;
}

interface AccountStore {
  accounts: Account[];
  activeAccountId: number | null;
  loading: boolean;
  fetchAccounts: () => Promise<void>;
  setActiveAccount: (id: number | null) => void;
}

// Eski yanitlarin yenisini ezmemesi icin monoton istek sayaci (trading-store deseni)
let latestAccountsRequest = 0;

export const useAccountStore = create<AccountStore>((set) => ({
  accounts: [],
  activeAccountId: null,
  loading: false,

  fetchAccounts: async () => {
    const requestId = ++latestAccountsRequest;
    set({ loading: true });
    try {
      const accounts = await api.get<Account[]>('/accounts');
      if (requestId !== latestAccountsRequest) return; // bayat yanit, yenisini ezme
      const current = useAccountStore.getState().activeAccountId;
      if (current === null) {
        set({ accounts, loading: false });
      } else {
        const stillExists = accounts.some((a) => a.id === current);
        const defaultAccount = accounts.find((a) => a.is_default) || accounts[0];
        set({
          accounts,
          activeAccountId: stillExists ? current : (defaultAccount?.id ?? null),
          loading: false,
        });
      }
    } catch {
      if (requestId === latestAccountsRequest) {
        set({ loading: false });
      }
    }
  },

  setActiveAccount: (id) => set({ activeAccountId: id }),
}));
