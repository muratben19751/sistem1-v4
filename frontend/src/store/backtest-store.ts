import { create } from 'zustand';
import { api } from '../lib/api';

export interface BacktestMetrics {
  trades: number; wins: number; losses: number;
  totalPnl: number; totalPnlPct: number; winRate: number;
  avgPnl: number; avgWin: number; avgLoss: number;
  profitFactor: number; sharpe: number; maxDrawdown: number; calmar: number; expectancy: number;
}

export interface BacktestTrade {
  symbol: string; side: 'long' | 'short';
  entryMs: number; exitMs: number; entryPrice: number; exitPrice: number;
  pnl: number; pnlPercent: number; exitReason: string; score: number;
}

export interface BacktestResult {
  metrics: BacktestMetrics;
  equityCurve: Array<{ time: number; value: number }>;
  trades: BacktestTrade[];
  coverage: { totalSignals: number; evaluated: number; entered: number; skippedNoData: number; symbols: number; avgTfCoverage: number };
  config: any;
  accountName: string;
}

export interface OptimizerStatus {
  running: boolean; generation: number; evaluated: number; currentName: string;
  bestCalmar: number; populationSize: number; index: number; backtestDays: number;
}

export interface OptimizerResultRow {
  id: number; strategy_name: string; config_json: string;
  trades: number; wins: number; losses: number; total_pnl: number; win_rate: number;
  profit_factor: number; sharpe_estimate: number; max_drawdown: number; calmar: number; generation: number; tested_at: string;
  backtest_days?: number;
  deployed_account_id?: number | null;
  deployed_at?: string | null;
  live_account_id?: number | null;
  live_account_name?: string | null;
  live_bot_enabled?: number | null;
  live_running?: boolean | null;  // gercek runtime durumu (bot fiilen calisiyor mu)
  badge?: 'live' | 'stopped' | null;  // deploy_state tabanli rozet (CANLI/STOPPED)
  leanParity?: 'pass' | 'warn' | 'fail' | null;
  leanParityDetail?: { verdict: string; winRateRel?: number | null; tradeRel?: number | null; window?: string; checkedAt?: string } | null;
}

export interface OptimizerInsight { id: number; strategy_name: string; message: string; type: string; created_at: string }

export interface OptimizerStats {
  total: number; junk: number; robust: number; wfCount: number;
  bestRobFit: number | null; bestCalmar: number; junkPct: number;
}

export interface BacktestProgress { phase: string; done: number; total: number }

interface BacktestStore {
  result: BacktestResult | null;
  loading: boolean;
  error: string | null;
  progress: BacktestProgress | null;
  run: (accountId: number, startMs: number, endMs: number, signalSource?: string) => Promise<void>;

  optStatus: OptimizerStatus | null;
  optStats: OptimizerStats | null;
  optResults: OptimizerResultRow[];
  optInsights: OptimizerInsight[];
  optLog: string[];
  optUnique: boolean;
  setOptUnique: (v: boolean) => void;
  optOnlyYear: boolean;
  setOptOnlyYear: (v: boolean) => void;
  optHideJunk: boolean;
  setOptHideJunk: (v: boolean) => void;
  fetchOptimizer: () => Promise<void>;
  startOptimizer: () => Promise<void>;
  stopOptimizer: () => Promise<void>;
  applyConfig: (accountId: number, resultId: number) => Promise<{ success: boolean; name: string; started: boolean }>;
  deployConfig: (resultId: number, accountId?: number) => Promise<{ success: boolean; accountId: number; name: string; started: boolean }>;
  stopStrategy: (resultId: number) => Promise<{ success: boolean; stopped: number[] }>;
  fetchFreeAccounts: () => Promise<Array<{ id: number; name: string; engine: string; hasCredentials: boolean; running: boolean }>>;
  pushOptLog: (msg: string) => void;
}

// Eski (filtresi degismis) yanitlarin yenisini ezmemesi icin monoton istek sayaci (trading-store deseni)
let latestOptimizerRequest = 0;

export const useBacktestStore = create<BacktestStore>((set, get) => ({
  result: null,
  loading: false,
  error: null,
  progress: null,
  run: async (accountId, startMs, endMs, signalSource) => {
    set({ loading: true, error: null, result: null, progress: { phase: 'preload', done: 0, total: 0 } });
    try {
      const { jobId } = await api.post<{ jobId: string }>('/backtest/start', { accountId, startMs, endMs, signalSource: signalSource || undefined });
      // poll until done
      for (;;) {
        await new Promise((r) => setTimeout(r, 2000));
        const job = await api.get<{ status: string; progress: BacktestProgress; error: string | null; result: BacktestResult | null }>(`/backtest/job/${jobId}`);
        if (job.status === 'running') { set({ progress: job.progress }); continue; }
        if (job.status === 'error') { set({ loading: false, error: job.error || 'Backtest hatasi', progress: null }); return; }
        set({ result: job.result, loading: false, progress: null });
        return;
      }
    } catch (e: any) {
      set({ loading: false, error: e?.message || 'Backtest hatasi', progress: null });
    }
  },

  optStatus: null,
  optStats: null,
  optResults: [],
  optInsights: [],
  optLog: [],
  optUnique: true,
  setOptUnique: (v) => { set({ optUnique: v }); get().fetchOptimizer(); },
  optOnlyYear: false,
  setOptOnlyYear: (v) => { set({ optOnlyYear: v }); get().fetchOptimizer(); },
  optHideJunk: true,
  setOptHideJunk: (v) => { set({ optHideJunk: v }); get().fetchOptimizer(); },
  fetchOptimizer: async () => {
    const requestId = ++latestOptimizerRequest;
    try {
      const uniqueParam = get().optUnique ? '1' : '0';
      const yearParam = get().optOnlyYear ? '1' : '0';
      const junkParam = get().optHideJunk ? '1' : '0';
      const [status, results, insights, stats] = await Promise.all([
        api.get<OptimizerStatus>('/optimizer/status'),
        api.get<OptimizerResultRow[]>(`/optimizer/results?unique=${uniqueParam}&year=${yearParam}&junk=${junkParam}`),
        api.get<OptimizerInsight[]>('/optimizer/insights'),
        api.get<OptimizerStats>('/optimizer/stats'),
      ]);
      if (requestId !== latestOptimizerRequest) return; // bayat yanit, yenisini ezme
      set({ optStatus: status, optResults: results, optInsights: insights, optStats: stats });
    } catch { /* ignore */ }
  },
  startOptimizer: async () => { try { const s = await api.post<OptimizerStatus>('/optimizer/start'); set({ optStatus: s }); } catch { /* */ } },
  stopOptimizer: async () => { try { const s = await api.post<OptimizerStatus>('/optimizer/stop'); set({ optStatus: s }); } catch { /* */ } },
  applyConfig: async (accountId, resultId) => { return api.post<{ success: boolean; name: string; started: boolean }>('/optimizer/apply', { accountId, resultId }); },
  deployConfig: async (resultId, accountId) => { return api.post<{ success: boolean; accountId: number; name: string; started: boolean }>('/optimizer/deploy', { resultId, accountId }); },
  stopStrategy: async (resultId) => { return api.post<{ success: boolean; stopped: number[] }>('/optimizer/stop-strategy', { resultId }); },
  fetchFreeAccounts: async () => { return api.get<Array<{ id: number; name: string; engine: string; hasCredentials: boolean; running: boolean }>>('/optimizer/free-accounts'); },
  pushOptLog: (msg) => set((st) => ({ optLog: [...st.optLog.slice(-200), msg] })),
}));
