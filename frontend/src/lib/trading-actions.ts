import { api } from './api';

interface CloseArgs {
  accountId: number;
  symbol: string;
  side: string;
}

export async function closePosition({ accountId, symbol, side }: CloseArgs): Promise<void> {
  await api.post('/trading/close', { accountId, symbol, side, reason: 'manual' });
}

interface OrderAccount {
  bot_leverage?: number;
  available_balance?: number;
  wallet_balance?: number;
  position_size_pct?: number;
  tp_percent?: number;
  sl_percent?: number;
}

interface OrderSignal {
  symbol: string;
  totalScore: number;
  rules: Array<{ key: string; score: number }>;
}

export function orderNotional(account: OrderAccount): number {
  const lev = account.bot_leverage || 2;
  const balance = account.available_balance ?? account.wallet_balance ?? 10000;
  const sizePct = (account.position_size_pct ?? 2) / 100;
  return balance * sizePct * lev;
}

export async function placeManualOrder(
  accountId: number,
  account: OrderAccount,
  signal: OrderSignal,
  side: 'long' | 'short',
): Promise<void> {
  const lev = account.bot_leverage || 2;
  await api.post('/trading/order', {
    accountId,
    symbol: signal.symbol,
    side,
    notional: orderNotional(account),
    leverage: lev,
    tpPercent: account.tp_percent ?? 5,
    slPercent: account.sl_percent ?? 3,
    signalScore: signal.totalScore,
    activeRules: signal.rules.filter((r) => r.score !== 0).map((r) => `${r.key}:${r.score}`).join(','),
    entryReason: 'manual',
  });
}
