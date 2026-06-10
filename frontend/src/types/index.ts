export interface Account {
  id: number;
  name: string;
  type: 'paper' | 'real' | 'demo';
  strategy: string;
  balance: number;
  initial_balance: number;
  leverage: number;
  color: string;
  is_default: number;
  is_active: number;
  engine: string;
  has_api_credentials: number;
  credentials_valid?: number | null;
  created_at: string;
  updated_at: string;
}

export interface BotConfig {
  id: number;
  account_id: number;
  long_min_score: number;
  short_min_score: number;
  leverage: number;
  max_positions: number;
  tp_percent: number;
  sl_percent: number;
  max_drawdown: number;
  max_drawdown_enabled: number;
  scan_interval: number;
  trailing_stop: number;
  trailing_percent: number;
  enabled_rules: string | null;
  rule_sources: string | null;
  signal_source: string;
  alert_freshness_minutes: number;
  alert_score_boost: number;
  position_size_pct: number;
}

export interface Trade {
  id: number;
  account_id: number;
  symbol: string;
  side: 'long' | 'short';
  size: number;
  entry_price: number;
  exit_price: number | null;
  leverage: number;
  pnl: number | null;
  pnl_percent: number | null;
  fee: number;
  status: 'open' | 'closed' | 'cancelled';
  active_rules: string | null;
  signal_score: number | null;
  entry_reason: string | null;
  exit_reason: string | null;
  opened_at: string;
  closed_at: string | null;
  duration_seconds: number | null;
  trigger_source?: string | null;
  trigger_stars?: number | null;
  min_score_used?: number | null;
  note?: string | null;
}

export interface Position {
  id: number;
  account_id: number;
  symbol: string;
  side: 'long' | 'short';
  size: number;
  entry_price: number;
  mark_price: number | null;
  leverage: number;
  unrealized_pnl: number;
  tp_price: number | null;
  sl_price: number | null;
  trailing_stop: number;
  trailing_highest: number | null;
  trailing_lowest: number | null;
  opened_at: string;
}

export interface PaperWallet {
  id: number;
  account_id: number;
  balance: number;
  initial_balance: number;
  total_pnl: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
}

export interface OrderParams {
  accountId: number;
  symbol: string;
  side: 'long' | 'short';
  size: number;
  leverage: number;
  tpPercent?: number;
  slPercent?: number;
  signalScore?: number;
  activeRules?: string;
  entryReason?: string;
}

export interface OrderResult {
  success: boolean;
  orderId?: number;
  tradeId?: number;
  fillPrice?: number;
  error?: string;
}

export interface CloseResult {
  success: boolean;
  pnl?: number;
  pnlPercent?: number;
  exitPrice?: number;
  error?: string;
}

export interface Balance {
  balance: number;
  equity: number;
  unrealizedPnl: number;
  availableBalance: number;
}

export interface Kline {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TickerData {
  symbol: string;
  lastPrice: number;
  price24hPcnt: number;
  highPrice24h: number;
  lowPrice24h: number;
  volume24h: number;
  turnover24h: number;
}

export interface EquitySnapshot {
  id: number;
  account_id: number;
  equity: number;
  balance: number;
  unrealized_pnl: number;
  drawdown: number;
  recorded_at: string;
}

export interface SignalResult {
  symbol: string;
  totalScore: number;
  side: 'long' | 'short' | 'neutral';
  rules: Array<{ key: string; name: string; score: number; side: string; detail: string }>;
  marketData: any;
  timestamp: string;
}

export interface ParsedAlert {
  symbol: string;
  direction: 'UP' | 'DOWN';
  signalType: string;
  sourceType: 'hammer' | '4s_sniper' | 'fr' | 'm1_a' | 'v3_a' | 'unknown';
  rsi: Record<string, number>;
  srsi: Record<string, number>;
  boostValue: number | null;
  price: number | null;
  previousPrice: number | null;
  fundingRate: number | null;
  previousFunding: number | null;
  timeRemaining: string | null;
  fundingChanged: number;
  stars: number;
  rawMessage: string;
  source: string;
}

export interface DelistWarning {
  id: number;
  exchange: string;
  symbol: string;
  market_type: string;
  delist_date: string;
  announcement_url: string | null;
  announcement_title: string | null;
  announcement_id: string;
  alert_level: string;
  has_open_position: number;
  notified_levels: string;
  created_at: string;
  updated_at: string;
}

export interface ListingsStats {
  total: number;
  byExchange: { binance: number; bybit: number };
  byLevel: Record<string, number>;
  withPositions: number;
}

export interface AccountWithDetails extends Account {
  long_min_score: number;
  short_min_score: number;
  bot_leverage: number;
  max_positions: number;
  tp_percent: number;
  sl_percent: number;
  max_drawdown: number;
  max_drawdown_enabled: number;
  scan_interval: number;
  trailing_stop: number;
  trailing_percent: number;
  enabled_rules: string | null;
  rule_sources: string | null;
  signal_source: string;
  alert_freshness_minutes: number;
  alert_score_boost: number;
  position_size_pct: number;
  wallet_balance: number;
  available_balance: number;
  account_equity: number;
  reserved_margin: number;
  open_unrealized_pnl: number;
  total_pnl: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
}
