import { formatUsd, formatPercent } from '../../lib/formatters';
import type { WinRateBreakdown } from '../../lib/trade-categorize';

interface KpiData {
  netLiq: number;
  todayChange: number;
  unrealPnl: number;
  realPnl: number;
  netExposure: number;
  grossExposure: number;
  longPct: number;
  shortPct: number;
  sharpe: number;
  maxDd: number;
  winRate: number;
  totalTrades: number;
  avgR: number;
  fees24h: number;
  rebates: number;
  wrBreakdown?: WinRateBreakdown;
}

function cl(v: number) {
  return v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-ink-300';
}

function sign(v: number) {
  return v > 0 ? '+' : '';
}

export default function KpiStrip({ data }: { data: KpiData }) {
  return (
    <div className="grid grid-cols-6 border-b border-white/5 bg-ink-900 shrink-0">
      <div className="px-4 py-2.5 border-r border-white/5">
        <div className="text-[9px] tracking-widest text-ink-400 uppercase">Net Liq</div>
        <div className="num text-[20px] font-semibold text-ink-50">{formatUsd(data.netLiq)}</div>
        <div className={`num text-[10px] ${cl(data.todayChange)}`}>
          {sign(data.todayChange)}{formatUsd(data.todayChange)} today
        </div>
      </div>

      <div className="px-4 py-2.5 border-r border-white/5">
        <div className="text-[9px] tracking-widest text-ink-400 uppercase">Unreal P/L</div>
        <div className={`num text-[20px] font-semibold ${cl(data.unrealPnl)}`}>
          {sign(data.unrealPnl)}{formatUsd(data.unrealPnl)}
        </div>
        <div className={`num text-[10px] ${cl(data.realPnl)}`}>
          real {sign(data.realPnl)}{formatUsd(data.realPnl)}
        </div>
      </div>

      <div className="px-4 py-2.5 border-r border-white/5">
        <div className="text-[9px] tracking-widest text-ink-400 uppercase">Exposure</div>
        <div className="num text-[20px] font-semibold text-ink-50">
          {formatUsd(data.netExposure)}
          <span className="text-[10px] text-ink-400 ml-1">/ {formatUsd(data.grossExposure)}</span>
        </div>
        <div className="mt-1 flex h-1 w-full rounded-sm overflow-hidden bg-ink-700">
          <div className="bg-up" style={{ width: `${data.longPct}%` }} />
          <div className="bg-down" style={{ width: `${data.shortPct}%` }} />
        </div>
      </div>

      <div className="px-4 py-2.5 border-r border-white/5">
        <div className="text-[9px] tracking-widest text-ink-400 uppercase">Max DD</div>
        <div className={`num text-[20px] font-semibold ${
          data.maxDd >= 5 ? 'text-down' : data.maxDd >= 2 ? 'text-warn' : data.maxDd > 0 ? 'text-ink-200' : 'text-ink-500'
        }`}>
          {data.maxDd > 0 ? '-' : ''}{Math.abs(data.maxDd).toFixed(2)}%
        </div>
        <div className="num text-[10px] text-ink-500">peak &rarr; current</div>
      </div>

      <div className="px-4 py-2.5 border-r border-white/5">
        <div className="text-[9px] tracking-widest text-ink-400 uppercase">Win Rate</div>
        <div className="num text-[20px] font-semibold text-ink-50">{data.winRate.toFixed(1)}%</div>
        {data.wrBreakdown ? (
          <div className="num text-[10px] mt-0.5 flex gap-2 leading-tight">
            <span className="text-info">S {data.wrBreakdown.scalp.winRate.toFixed(0)}%<span className="text-ink-500">/{data.wrBreakdown.scalp.total}</span></span>
            <span className="text-purple-400">W {data.wrBreakdown.swing.winRate.toFixed(0)}%<span className="text-ink-500">/{data.wrBreakdown.swing.total}</span></span>
            <span className="text-amber-400">M {data.wrBreakdown.manual.winRate.toFixed(0)}%<span className="text-ink-500">/{data.wrBreakdown.manual.total}</span></span>
          </div>
        ) : (
          <div className="num text-[10px] text-ink-300">
            {data.totalTrades} trades / avg R {data.avgR.toFixed(2)}
          </div>
        )}
      </div>

      <div className="px-4 py-2.5">
        <div className="text-[9px] tracking-widest text-ink-400 uppercase">Fees 24H</div>
        <div className="num text-[20px] font-semibold text-down">{formatUsd(data.fees24h)}</div>
        <div className="num text-[10px] text-ink-400">
          {data.totalTrades} trades
        </div>
      </div>
    </div>
  );
}
