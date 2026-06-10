import { useEffect, useRef } from 'react';
import { createChart, type IChartApi, ColorType } from 'lightweight-charts';

interface DataPoint {
  time: string;
  value: number;
  color: string;
}

interface Props {
  data: DataPoint[];
  height?: number;
}

export default function PnLBarChart({ data, height = 200 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

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
      rightPriceScale: { borderColor: '#374151' },
      timeScale: { borderColor: '#374151' },
    });

    const series = chart.addHistogramSeries({
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    });

    if (data.length > 0) {
      const sorted = [...data].sort((a, b) => a.time.localeCompare(b.time));
      const deduped = sorted.filter((d, i) => i === 0 || d.time !== sorted[i - 1].time);
      series.setData(deduped as any);
    }

    chartRef.current = chart;

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
  }, [data, height]);

  return <div ref={containerRef} />;
}
