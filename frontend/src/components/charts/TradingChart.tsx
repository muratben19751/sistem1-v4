import { useEffect, useRef, useState } from 'react';
import { createChart, type IChartApi, type ISeriesApi, ColorType } from 'lightweight-charts';
import { api } from '../../lib/api';
import { useCustomizationStore } from '../../store/customization-store';
import type { Kline } from '../../types';

interface TradeMarker {
  time: number;
  position: 'aboveBar' | 'belowBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown' | 'circle';
  text: string;
}

interface Props {
  symbol: string;
  interval?: string;
  height?: number;
  trades?: Array<{
    side: string;
    entry_price: number;
    exit_price?: number | null;
    opened_at: string;
    closed_at?: string | null;
  }>;
}

const INTERVALS = [
  { value: '1', label: '1m' },
  { value: '5', label: '5m' },
  { value: '15', label: '15m' },
  { value: '60', label: '1H' },
  { value: '240', label: '4H' },
  { value: 'D', label: '1D' },
];

export default function TradingChart({ symbol, interval: defaultInterval, height = 500, trades }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const rsiContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const rsiChartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<any>[]>([]);
  const rsiSeriesRef = useRef<ISeriesApi<any>[]>([]);
  const { preferences } = useCustomizationStore();
  const [interval, setInterval] = useState(defaultInterval || preferences.defaultTimeframe || '5');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!containerRef.current || !rsiContainerRef.current) return;

    const mainChart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: height - 150,
      layout: {
        background: { type: ColorType.Solid, color: '#111827' },
        textColor: '#9CA3AF',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: '#1F2937' },
        horzLines: { color: '#1F2937' },
      },
      rightPriceScale: { borderColor: '#374151' },
      timeScale: { borderColor: '#374151', timeVisible: true, secondsVisible: false },
      crosshair: {
        horzLine: { color: '#4B5563', labelBackgroundColor: '#374151' },
        vertLine: { color: '#4B5563', labelBackgroundColor: '#374151' },
      },
    });

    const rsiChart = createChart(rsiContainerRef.current, {
      width: rsiContainerRef.current.clientWidth,
      height: 120,
      layout: {
        background: { type: ColorType.Solid, color: '#111827' },
        textColor: '#9CA3AF',
        fontSize: 10,
      },
      grid: {
        vertLines: { color: '#1F2937' },
        horzLines: { color: '#1F2937' },
      },
      rightPriceScale: { borderColor: '#374151' },
      timeScale: { borderColor: '#374151', timeVisible: true, secondsVisible: false, visible: true },
    });

    mainChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) rsiChart.timeScale().setVisibleLogicalRange(range);
    });
    rsiChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) mainChart.timeScale().setVisibleLogicalRange(range);
    });

    chartRef.current = mainChart;
    rsiChartRef.current = rsiChart;

    const handleResize = () => {
      if (containerRef.current) mainChart.applyOptions({ width: containerRef.current.clientWidth });
      if (rsiContainerRef.current) rsiChart.applyOptions({ width: rsiContainerRef.current.clientWidth });
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      mainChart.remove();
      rsiChart.remove();
    };
  }, [height]);

  useEffect(() => {
    if (!chartRef.current || !rsiChartRef.current || !symbol) return;

    const mainChart = chartRef.current;
    const rsiChart = rsiChartRef.current;
    let cancelled = false; // unmount/yeniden kosumdan sonra kaldirilmis chart'a dokunma

    setLoading(true);

    api.get<Kline[]>(`/scanner/klines/${symbol}?interval=${interval}&limit=200`)
      .then((klines) => {
        if (cancelled || chartRef.current !== mainChart) return;
        for (const s of seriesRef.current) { try { mainChart.removeSeries(s); } catch {} }
        seriesRef.current = [];

        const candleSeries = mainChart.addCandlestickSeries({
          upColor: preferences.candleUpColor,
          downColor: preferences.candleDownColor,
          borderUpColor: preferences.candleUpColor,
          borderDownColor: preferences.candleDownColor,
          wickUpColor: preferences.candleUpColor,
          wickDownColor: preferences.candleDownColor,
        });

        seriesRef.current.push(candleSeries);
        candleSeries.setData(klines.map((k) => ({
          time: k.time as any,
          open: k.open,
          high: k.high,
          low: k.low,
          close: k.close,
        })));

        if (preferences.showVolume) {
          const volumeSeries = mainChart.addHistogramSeries({
            priceFormat: { type: 'volume' },
            priceScaleId: 'volume',
          });
          mainChart.priceScale('volume').applyOptions({
            scaleMargins: { top: 0.85, bottom: 0 },
          });
          volumeSeries.setData(klines.map((k) => ({
            time: k.time as any,
            value: k.volume,
            color: k.close >= k.open ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)',
          })));
          seriesRef.current.push(volumeSeries);
        }

        if (trades && (preferences.showEntryMarkers || preferences.showExitMarkers)) {
          const markers: TradeMarker[] = [];
          for (const t of trades) {
            if (preferences.showEntryMarkers) {
              const entryTime = Math.floor(new Date(t.opened_at).getTime() / 1000);
              markers.push({
                time: entryTime,
                position: t.side === 'long' ? 'belowBar' : 'aboveBar',
                color: t.side === 'long' ? '#22C55E' : '#EF4444',
                shape: t.side === 'long' ? 'arrowUp' : 'arrowDown',
                text: `${t.side.toUpperCase()} @${t.entry_price.toFixed(2)}`,
              });
            }
            if (preferences.showExitMarkers && t.exit_price && t.closed_at) {
              const exitTime = Math.floor(new Date(t.closed_at).getTime() / 1000);
              markers.push({
                time: exitTime,
                position: t.side === 'long' ? 'aboveBar' : 'belowBar',
                color: '#F59E0B',
                shape: 'circle',
                text: `EXIT @${t.exit_price.toFixed(2)}`,
              });
            }
          }
          if (markers.length > 0) {
            markers.sort((a, b) => a.time - b.time);
            candleSeries.setMarkers(markers as any);
          }
        }

        if (preferences.showRsi && klines.length > 14) {
          for (const s of rsiSeriesRef.current) { try { rsiChart.removeSeries(s); } catch {} }
          rsiSeriesRef.current = [];

          const closes = klines.map((k) => k.close);
          const rsiValues = calcRSIArray(closes, 14);

          const rsiSeries = rsiChart.addLineSeries({
            color: '#A855F7',
            lineWidth: 1,
            priceScaleId: 'rsi',
          });

          rsiChart.priceScale('rsi').applyOptions({
            autoScale: false,
            scaleMargins: { top: 0.05, bottom: 0.05 },
          });

          const rsiData = rsiValues.map((v, i) => ({
            time: klines[klines.length - rsiValues.length + i].time as any,
            value: v,
          }));
          rsiSeries.setData(rsiData);
          rsiSeriesRef.current.push(rsiSeries);

          const ob = rsiChart.addLineSeries({ color: 'rgba(239,68,68,0.3)', lineWidth: 1, priceScaleId: 'rsi', lastValueVisible: false, priceLineVisible: false });
          const os = rsiChart.addLineSeries({ color: 'rgba(34,197,94,0.3)', lineWidth: 1, priceScaleId: 'rsi', lastValueVisible: false, priceLineVisible: false });
          ob.setData(rsiData.map((d) => ({ time: d.time, value: 70 })));
          os.setData(rsiData.map((d) => ({ time: d.time, value: 30 })));
          rsiSeriesRef.current.push(ob, os);
        }

        mainChart.timeScale().fitContent();
        rsiChart.timeScale().fitContent();
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [symbol, interval, preferences.candleUpColor, preferences.candleDownColor, preferences.showVolume, preferences.showRsi, preferences.showEntryMarkers, preferences.showExitMarkers, trades]);

  return (
    <div>
      <div className="flex items-center gap-1 mb-2">
        {INTERVALS.map((itv) => (
          <button
            key={itv.value}
            onClick={() => setInterval(itv.value)}
            className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
              interval === itv.value
                ? 'bg-blue-600 text-white'
                : 'bg-gray-800 text-gray-400 hover:text-white'
            }`}
          >
            {itv.label}
          </button>
        ))}
        {loading && <span className="text-xs text-gray-500 ml-2">Yukleniyor...</span>}
      </div>
      <div ref={containerRef} className="rounded-t border border-b-0 border-gray-800" />
      <div ref={rsiContainerRef} className="rounded-b border border-gray-800" />
    </div>
  );
}

function calcRSIArray(closes: number[], period: number): number[] {
  const result: number[] = [];
  if (closes.length < period + 1) return result;

  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const diff = closes[i] - closes[i - 1];
    if (diff > 0) avgGain += diff;
    else avgLoss -= diff;
  }
  avgGain /= period;
  avgLoss /= period;

  result.push(avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss));

  for (let i = period + 1; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    const gain = diff > 0 ? diff : 0;
    const loss = diff < 0 ? -diff : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    result.push(avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss));
  }

  return result;
}
