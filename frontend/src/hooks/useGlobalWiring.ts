import { useEffect } from 'react';
import { useAccountStore } from '../store/account-store';
import { useUiStore } from '../store/ui-store';
import { useTickerStore } from '../store/ticker-store';
import { usePositionStore } from '../store/position-store';
import { useRuleLabelsStore } from '../store/rule-labels-store';
import { wsClient } from '../lib/ws';
import { api } from '../lib/api';

export function useGlobalWiring() {
  const fetchAccounts = useAccountStore((s) => s.fetchAccounts);
  const { addBotLog, setWsLatency, setExchangeStatus } = useUiStore();
  const fetchTickers = useTickerStore((s) => s.fetchTickers);

  useEffect(() => {
    fetchAccounts();
    useRuleLabelsStore.getState().fetch();
    wsClient.connect();

    const refreshTickers = () => {
      fetchTickers().then(() => setExchangeStatus('ok')).catch(() => setExchangeStatus('error'));
      api.get<Record<string, number>>('/market/prices')
        .then((prices) => usePositionStore.getState().syncPrices((sym) => prices[sym]))
        .catch(() => {});
    };
    refreshTickers();
    const tickerInterval = setInterval(refreshTickers, 10000);

    const unsubs = [
      wsClient.on('bot:log', (data) => addBotLog(data)),
      wsClient.on('bot:started', () => fetchAccounts()),
      wsClient.on('bot:stopped', () => fetchAccounts()),
      wsClient.on('position:closed', () => fetchAccounts()),
      wsClient.on('order:filled', () => fetchAccounts()),
      wsClient.on('position:updated', (data) => {
        usePositionStore.getState().updatePosition(
          data.symbol,
          { size: data.size, mark_price: data.markPrice, unrealized_pnl: data.unrealizedPnl },
          data.side,
          data.accountId,
        );
      }),
      wsClient.on('latency', (ms) => setWsLatency(ms)),
      wsClient.on('risk:circuit_breaker', (data) => {
        if (typeof data?.accountId !== 'number') return;
        useUiStore.getState().pushCircuitBreaker({
          accountId: data.accountId,
          drawdown: Number(data.drawdown) || 0,
          triggeredAt: new Date().toISOString(),
        });
      }),
    ];

    return () => {
      clearInterval(tickerInterval);
      unsubs.forEach((fn) => fn());
      wsClient.disconnect();
    };
  }, [fetchAccounts, addBotLog, setWsLatency, setExchangeStatus, fetchTickers]);
}
