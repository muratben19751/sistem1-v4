import { useEffect, useRef } from 'react';
import { createChart, type IChartApi, type ISeriesApi, ColorType } from 'lightweight-charts';

interface DataPoint {
  time: string;
  value: number;
}

interface Props {
  data: DataPoint[];
  height?: number;
}

export default function EquityCurve({ data, height = 250 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Area'> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#9CA3AF',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: '#1F2937' },
        horzLines: { color: '#1F2937' },
      },
      rightPriceScale: {
        borderColor: '#374151',
      },
      timeScale: {
        borderColor: '#374151',
        timeVisible: true,
      },
      crosshair: {
        horzLine: { color: '#4B5563' },
        vertLine: { color: '#4B5563' },
      },
    });

    const series = chart.addAreaSeries({
      lineColor: '#3B82F6',
      topColor: 'rgba(59, 130, 246, 0.3)',
      bottomColor: 'rgba(59, 130, 246, 0.0)',
      lineWidth: 2,
    });

    chartRef.current = chart;
    seriesRef.current = series;

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [height]);

  useEffect(() => {
    if (seriesRef.current && data.length > 0) {
      const sorted = [...data].sort((a, b) => a.time.localeCompare(b.time));
      const deduped = sorted.filter((d, i) => i === 0 || d.time !== sorted[i - 1].time);
      seriesRef.current.setData(deduped as any);
    }
  }, [data]);

  return <div ref={containerRef} />;
}
