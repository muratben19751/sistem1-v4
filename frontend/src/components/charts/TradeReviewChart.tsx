import { useEffect, useMemo, useRef, useState } from 'react';
import { createChart, type IChartApi, type ISeriesApi, ColorType, LineStyle } from 'lightweight-charts';
import { api } from '../../lib/api';
import { parseServerDateMs } from '../../lib/formatters';
import { useCustomizationStore } from '../../store/customization-store';
import type { Kline } from '../../types';

interface Props {
  symbol: string;
  side: 'long' | 'short';
  entry_price: number;
  exit_price?: number | null;
  opened_at: string;
  closed_at?: string | null;
  tp_price?: number | null;
  sl_price?: number | null;
  height?: number;
}

const INTERVALS = [
  { value: '1', label: '1m', ms: 60_000 },
  { value: '5', label: '5m', ms: 300_000 },
  { value: '15', label: '15m', ms: 900_000 },
  { value: '60', label: '1H', ms: 3_600_000 },
  { value: '240', label: '4H', ms: 14_400_000 },
];
const INTERVAL_MS: Record<string, number> = Object.fromEntries(INTERVALS.map((i) => [i.value, i.ms]));

function autoInterval(durationMs: number): string {
  if (durationMs <= 30 * 60_000) return '1';
  if (durationMs <= 2 * 3_600_000) return '5';
  if (durationMs <= 12 * 3_600_000) return '15';
  if (durationMs <= 3 * 86_400_000) return '60';
  return '240';
}

export default function TradeReviewChart({ symbol, side, entry_price, exit_price, opened_at, closed_at, tp_price, sl_price, height = 420 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const { preferences } = useCustomizationStore();

  const openedMs = useMemo(() => parseServerDateMs(opened_at), [opened_at]);
  const closedMs = useMemo(() => (closed_at ? parseServerDateMs(closed_at) : Date.now()), [closed_at]);
  const defaultInterval = useMemo(() => autoInterval(Math.max(0, closedMs - openedMs)), [openedMs, closedMs]);

  const [interval, setIntervalState] = useState(defaultInterval);
  const [loading, setLoading] = useState(false);
  const [empty, setEmpty] = useState(false);

  useEffect(() => { setIntervalState(defaultInterval); }, [defaultInterval]);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: { background: { type: ColorType.Solid, color: '#111827' }, textColor: '#9CA3AF', fontSize: 11 },
      grid: { vertLines: { color: '#1F2937' }, horzLines: { color: '#1F2937' } },
      rightPriceScale: { borderColor: '#374151' },
      timeScale: { borderColor: '#374151', timeVisible: true, secondsVisible: false },
      crosshair: {
        horzLine: { color: '#4B5563', labelBackgroundColor: '#374151' },
        vertLine: { color: '#4B5563', labelBackgroundColor: '#374151' },
      },
    });
    chartRef.current = chart;
    const handleResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [height]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !symbol) return;
    if (!Number.isFinite(openedMs) || !Number.isFinite(closedMs)) {
      setLoading(false);
      setEmpty(true);
      return;
    }
    let cancelled = false;

    const itvMs = INTERVAL_MS[interval] ?? 300_000;
    const pad = 50 * itvMs;
    const start = Math.max(0, Math.floor(openedMs - pad));
    const end = Math.floor(closedMs + pad);

    setLoading(true);
    setEmpty(false);

    api.get<Kline[]>(`/scanner/klines/${symbol}?interval=${interval}&start=${start}&end=${end}`)
      .then((klines) => {
        if (cancelled || chartRef.current !== chart) return;
        if (seriesRef.current) { try { chart.removeSeries(seriesRef.current); } catch {} seriesRef.current = null; }
        if (!klines || klines.length === 0) { setEmpty(true); return; }

        const candleSeries = chart.addCandlestickSeries({
          upColor: preferences.candleUpColor,
          downColor: preferences.candleDownColor,
          borderUpColor: preferences.candleUpColor,
          borderDownColor: preferences.candleDownColor,
          wickUpColor: preferences.candleUpColor,
          wickDownColor: preferences.candleDownColor,
        });
        seriesRef.current = candleSeries;
        candleSeries.setData(klines.map((k) => ({ time: k.time as any, open: k.open, high: k.high, low: k.low, close: k.close })));

        const entryTime = Math.floor(openedMs / 1000);
        const markers: Array<{ time: any; position: 'aboveBar' | 'belowBar'; color: string; shape: 'arrowUp' | 'arrowDown' | 'circle'; text: string }> = [
          {
            time: entryTime,
            position: side === 'long' ? 'belowBar' : 'aboveBar',
            color: side === 'long' ? '#22C55E' : '#EF4444',
            shape: side === 'long' ? 'arrowUp' : 'arrowDown',
            text: `GIRIS ${side.toUpperCase()} @${entry_price}`,
          },
        ];
        if (exit_price != null && Number.isFinite(exit_price) && closed_at) {
          markers.push({
            time: Math.floor(closedMs / 1000),
            position: side === 'long' ? 'aboveBar' : 'belowBar',
            color: '#F59E0B',
            shape: 'circle',
            text: `CIKIS @${exit_price}`,
          });
        }
        markers.sort((a, b) => (a.time as number) - (b.time as number));
        candleSeries.setMarkers(markers as any);

        candleSeries.createPriceLine({ price: entry_price, color: side === 'long' ? '#22C55E' : '#EF4444', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'Giris' });
        if (exit_price != null && Number.isFinite(exit_price)) candleSeries.createPriceLine({ price: exit_price, color: '#F59E0B', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'Cikis' });
        if (tp_price != null && Number.isFinite(tp_price)) candleSeries.createPriceLine({ price: tp_price, color: '#10B981', lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: 'TP' });
        if (sl_price != null && Number.isFinite(sl_price)) candleSeries.createPriceLine({ price: sl_price, color: '#EF4444', lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: 'SL' });

        chart.timeScale().fitContent();
      })
      .catch(() => { if (!cancelled) setEmpty(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [symbol, interval, openedMs, closedMs, entry_price, exit_price, closed_at, side, tp_price, sl_price, preferences.candleUpColor, preferences.candleDownColor]);

  return (
    <div>
      <div className="flex items-center gap-1 mb-2">
        {INTERVALS.map((itv) => (
          <button
            key={itv.value}
            onClick={() => setIntervalState(itv.value)}
            className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
              interval === itv.value ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'
            }`}
          >
            {itv.label}
          </button>
        ))}
        {loading && <span className="text-xs text-gray-500 ml-2">Yukleniyor...</span>}
        {!loading && empty && <span className="text-xs text-down ml-2">Grafik verisi bulunamadi</span>}
      </div>
      <div ref={containerRef} className="rounded border border-gray-800" />
    </div>
  );
}
