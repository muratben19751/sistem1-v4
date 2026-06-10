import { useState, useMemo } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { formatUsd, parseServerDateMs } from '../../lib/formatters';

interface Trade {
  id: number;
  pnl: number | null;
  closed_at: string | null;
  opened_at: string;
}

interface Props {
  trades: Trade[];
  onDayClick?: (date: string, trades: Trade[]) => void;
  selectedDate?: string | null;
}

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

// Europe/Istanbul gunune gore YYYY-MM-DD anahtari (Journal ile ayni yaklasim)
const IST_DAY_FMT = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Istanbul' });

function toLocalDateKey(date: Date): string {
  return IST_DAY_FMT.format(date);
}

// Backend UTC zaman damgasini ('Z' ekleyerek) parse edip Istanbul gunune yerlestir
function tradeDayKey(raw: string): string {
  const ms = parseServerDateMs(raw);
  return Number.isFinite(ms) ? IST_DAY_FMT.format(new Date(ms)) : 'unknown';
}

export default function PnLCalendar({ trades, onDayClick, selectedDate }: Props) {
  const [viewDate, setViewDate] = useState(() => new Date());

  const year = viewDate.getFullYear();
  const month = viewDate.getMonth();

  const dayMap = useMemo(() => {
    const map: Record<string, { pnl: number; count: number; trades: Trade[] }> = {};
    for (const t of trades) {
      const d = tradeDayKey(t.closed_at || t.opened_at);
      if (!map[d]) map[d] = { pnl: 0, count: 0, trades: [] };
      map[d].pnl += t.pnl || 0;
      map[d].count++;
      map[d].trades.push(t);
    }
    return map;
  }, [trades]);

  const allPnls = Object.values(dayMap).map((d) => Math.abs(d.pnl));
  const maxAbs = Math.max(...allPnls, 1);

  const firstDay = new Date(year, month, 1);
  const lastDay = new Date(year, month + 1, 0);
  const startOffset = (firstDay.getDay() + 6) % 7;

  const weeks: (number | null)[][] = [];
  let week: (number | null)[] = Array(startOffset).fill(null);
  for (let d = 1; d <= lastDay.getDate(); d++) {
    week.push(d);
    if (week.length === 7) {
      weeks.push(week);
      week = [];
    }
  }
  if (week.length > 0) {
    while (week.length < 7) week.push(null);
    weeks.push(week);
  }

  const prev = () => setViewDate(new Date(year, month - 1, 1));
  const next = () => setViewDate(new Date(year, month + 1, 1));

  const monthLabel = viewDate.toLocaleString('en', { month: 'short', year: 'numeric' }).toUpperCase();

  const monthPnl = Object.entries(dayMap)
    .filter(([k]) => k.startsWith(`${year}-${String(month + 1).padStart(2, '0')}`))
    .reduce((s, [, v]) => s + v.pnl, 0);

  const monthTrades = Object.entries(dayMap)
    .filter(([k]) => k.startsWith(`${year}-${String(month + 1).padStart(2, '0')}`))
    .reduce((s, [, v]) => s + v.count, 0);

  function getCellBg(pnl: number): string {
    const ratio = Math.min(Math.abs(pnl) / maxAbs, 1);
    if (pnl > 0) {
      if (ratio > 0.6) return 'bg-green-600/80';
      if (ratio > 0.25) return 'bg-green-700/50';
      return 'bg-green-800/30';
    }
    if (ratio > 0.6) return 'bg-red-600/80';
    if (ratio > 0.25) return 'bg-red-700/50';
    return 'bg-red-800/30';
  }

  return (
    <div>
      <div className="flex items-center justify-between px-3 py-1.5">
        <button onClick={prev} className="text-ink-400 hover:text-ink-100 transition-colors p-1">
          <ChevronLeft size={14} />
        </button>
        <div className="flex items-center gap-3">
          <span className="text-[10px] tracking-[0.2em] text-ink-200 font-medium">{monthLabel}</span>
          <span className={`text-[10px] num font-medium ${monthPnl >= 0 ? 'text-up' : 'text-down'}`}>
            {formatUsd(monthPnl)}
          </span>
          <span className="text-[9px] text-ink-500 num">{monthTrades}t</span>
        </div>
        <button onClick={next} className="text-ink-400 hover:text-ink-100 transition-colors p-1">
          <ChevronRight size={14} />
        </button>
      </div>

      <table className="w-full border-collapse">
        <thead>
          <tr>
            {WEEKDAYS.map((d) => (
              <th key={d} className="text-[8px] text-ink-500 font-normal py-1 text-center w-[14.28%]">{d}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {weeks.map((w, wi) => (
            <tr key={wi}>
              {w.map((day, di) => {
                if (day === null) return <td key={di} className="p-0.5" />;
                const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
                const info = dayMap[dateStr];
                const isSelected = selectedDate === dateStr;
                const isToday = dateStr === toLocalDateKey(new Date());

                return (
                  <td key={di} className="p-0.5">
                    <div
                      onClick={() => info && info.count > 0 && onDayClick?.(dateStr, info.trades)}
                      className={`relative rounded h-10 flex flex-col items-center justify-center transition-all ${
                        info && info.count > 0
                          ? `${getCellBg(info.pnl)} cursor-pointer hover:ring-1 hover:ring-white/30`
                          : 'bg-ink-800/30'
                      } ${isSelected ? 'ring-2 ring-white/60' : ''}`}
                    >
                      <span className={`text-[9px] ${isToday ? 'text-accent font-bold' : info && info.count > 0 ? 'text-ink-200' : 'text-ink-600'}`}>
                        {day}
                      </span>
                      {info && info.count > 0 && (
                        <>
                          <span className={`text-[8px] num font-medium leading-none ${info.pnl >= 0 ? 'text-green-300' : 'text-red-300'}`}>
                            {info.pnl >= 0 ? '+' : ''}{info.pnl.toFixed(0)}
                          </span>
                          <span className="text-[7px] text-ink-500 num leading-none">{info.count}t</span>
                        </>
                      )}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
