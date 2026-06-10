import { create } from 'zustand';

export interface BotStatus {
  status: 'running' | 'stopped';
  accountId: number;
  startedAt: string | null;
  totalScans: number;
  totalSignals: number;
  totalOrders: number;
  lastScan: string | null;
  monitorRunning: boolean;
}

export interface BotLog {
  time: string;
  level: string;
  message: string;
  accountId?: number;
}

const defaultBotStatus: BotStatus = {
  status: 'stopped',
  accountId: 0,
  startedAt: null,
  totalScans: 0,
  totalSignals: 0,
  totalOrders: 0,
  lastScan: null,
  monitorRunning: false,
};

export interface CircuitBreakerAlert {
  accountId: number;
  drawdown: number;
  triggeredAt: string;
}

interface UiStore {
  botStatuses: Record<number, BotStatus>;
  botLogs: Record<number, BotLog[]>;
  wsLatency: number;
  exchangeStatus: 'ok' | 'error' | 'loading';
  circuitBreakers: CircuitBreakerAlert[];
  cbDismissed: Record<number, number>;

  setBotStatus: (accountId: number, status: BotStatus) => void;
  addBotLog: (log: BotLog) => void;
  setBotLogs: (accountId: number, logs: BotLog[]) => void;
  setWsLatency: (ms: number) => void;
  setExchangeStatus: (s: 'ok' | 'error' | 'loading') => void;
  pushCircuitBreaker: (alert: CircuitBreakerAlert) => void;
  dismissCircuitBreaker: (accountId: number) => void;
}

const CB_DISMISS_TTL_MS = 30 * 60 * 1000;

export const useUiStore = create<UiStore>((set) => ({
  botStatuses: {},
  botLogs: {},
  wsLatency: 0,
  exchangeStatus: 'loading',
  circuitBreakers: [],
  cbDismissed: {},

  setBotStatus: (accountId, status) =>
    set((s) => ({
      botStatuses: { ...s.botStatuses, [accountId]: status },
    })),

  addBotLog: (log) =>
    set((s) => {
      const accountId = log.accountId || 0;
      const prev = s.botLogs[accountId] || [];
      return {
        botLogs: { ...s.botLogs, [accountId]: [...prev, log].slice(-200) },
      };
    }),

  setBotLogs: (accountId, logs) =>
    set((s) => ({
      botLogs: { ...s.botLogs, [accountId]: logs },
    })),

  setWsLatency: (wsLatency) => set({ wsLatency }),
  setExchangeStatus: (exchangeStatus) => set({ exchangeStatus }),

  pushCircuitBreaker: (alert) =>
    set((s) => {
      const dismissedAt = s.cbDismissed[alert.accountId];
      if (dismissedAt && Date.now() - dismissedAt < CB_DISMISS_TTL_MS) {
        return s;
      }
      return {
        circuitBreakers: [
          ...s.circuitBreakers.filter((c) => c.accountId !== alert.accountId),
          alert,
        ],
      };
    }),

  dismissCircuitBreaker: (accountId) =>
    set((s) => ({
      circuitBreakers: s.circuitBreakers.filter((c) => c.accountId !== accountId),
      cbDismissed: { ...s.cbDismissed, [accountId]: Date.now() },
    })),
}));

