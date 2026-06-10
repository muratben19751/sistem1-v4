import { useState } from 'react';
import { useAccountStore } from '../../store/account-store';
import { usePositionStore } from '../../store/position-store';
import { formatUsd, formatPercent, formatPrice } from '../../lib/formatters';
import { positionMargin, positionPnlPercent, slDistancePct, slDistanceTone } from '../../lib/position-math';
import { closePosition } from '../../lib/trading-actions';

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
  sl_price: number | null;
  tp_price: number | null;
}

export default function PositionCard({ p }: { p: Position }) {
  const { accounts } = useAccountStore();
  const removePosition = usePositionStore((s) => s.removePosition);
  const [closing, setClosing] = useState(false);
  const [confirm, setConfirm] = useState(false);

  const acc = accounts.find((a) => a.id === p.account_id);
  const pnl = p.unrealized_pnl || 0;
  const pnlPct = positionPnlPercent(p);
  const isLong = p.side === 'long';
  const up = pnl >= 0;
  const dist = slDistancePct(p);

  const handleClose = async () => {
    setClosing(true);
    try {
      await closePosition({ accountId: p.account_id, symbol: p.symbol, side: p.side });
      removePosition(p.symbol, p.side, p.account_id);
    } catch {
      setClosing(false);
      setConfirm(false);
    }
  };

  return (
    <div className={`rounded-md border bg-ink-850 px-3 py-2.5 ${up ? 'border-white/5' : 'border-down/20 bg-down/[0.04]'}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`inline-block w-1 h-9 rounded-full ${isLong ? 'bg-up' : 'bg-down'}`} />
          <div className="min-w-0">
            <div className="text-base font-semibold text-ink-50 truncate">{p.symbol}</div>
            <div className="text-[11px] text-ink-400 flex items-center gap-1.5">
              <span className={isLong ? 'text-up' : 'text-down'}>{p.side.toUpperCase()}</span>
              <span>·</span>
              <span>{p.leverage}x</span>
              {acc && (
                <>
                  <span>·</span>
                  <span className="inline-flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: acc.color || '#888' }} />
                    {acc.name}
                  </span>
                </>
              )}
            </div>
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className={`text-base font-semibold num ${up ? 'text-up' : 'text-down'}`}>
            {up ? '+' : ''}{formatUsd(pnl)}
          </div>
          <div className={`text-xs num ${up ? 'text-up' : 'text-down'}`}>{formatPercent(pnlPct)}</div>
        </div>
      </div>

      <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
        <div>
          <div className="text-ink-500">Giriş</div>
          <div className="text-ink-200 num">{formatPrice(p.entry_price)}</div>
        </div>
        <div>
          <div className="text-ink-500">Mark</div>
          <div className="text-ink-200 num">{p.mark_price ? formatPrice(p.mark_price) : '-'}</div>
        </div>
        <div>
          <div className="text-ink-500">Margin</div>
          <div className="text-ink-200 num">{formatUsd(positionMargin(p))}</div>
        </div>
      </div>

      <div className="mt-2.5 flex items-center justify-between">
        <div className="text-[11px]">
          <span className="text-ink-500">SL mesafe </span>
          {dist === null ? (
            <span className="text-ink-500 num">--</span>
          ) : (
            <span className={`num ${slDistanceTone(dist)}`}>{dist > 0 ? '-' : '+'}{Math.abs(dist).toFixed(2)}%</span>
          )}
        </div>
        {confirm ? (
          <div className="flex items-center gap-2">
            <button
              onClick={() => setConfirm(false)}
              disabled={closing}
              className="text-xs text-ink-400 px-3 min-h-[36px]"
            >
              Vazgeç
            </button>
            <button
              onClick={handleClose}
              disabled={closing}
              className="text-xs font-medium text-down border border-down/40 bg-down/15 rounded px-3 min-h-[36px] disabled:opacity-50"
            >
              {closing ? 'Kapanıyor...' : 'Onayla'}
            </button>
          </div>
        ) : (
          <button
            onClick={() => setConfirm(true)}
            className="text-xs font-medium text-ink-200 border border-white/10 rounded px-4 min-h-[36px] active:bg-white/5"
          >
            Kapat
          </button>
        )}
      </div>
    </div>
  );
}
