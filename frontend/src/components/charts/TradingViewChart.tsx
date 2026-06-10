import { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, CrosshairMode, LineStyle, type IChartApi, type ISeriesApi, type IPriceLine } from 'lightweight-charts';
import { api } from '../../lib/api';

export interface ChartPosition {
  symbol: string;
  side: 'long' | 'short';
  entry_price: number;
  tp_price?: number | null;
  sl_price?: number | null;
}

interface KlineData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

function toHeikinAshi(candles: KlineData[]): KlineData[] {
  const ha: KlineData[] = [];
  for (let i = 0; i < candles.length; i++) {
    const c = candles[i];
    const prev = ha[i - 1];
    const haClose = (c.open + c.high + c.low + c.close) / 4;
    const haOpen = prev ? (prev.open + prev.close) / 2 : (c.open + c.close) / 2;
    ha.push({
      time: c.time, open: haOpen,
      high: Math.max(c.high, haOpen, haClose),
      low: Math.min(c.low, haOpen, haClose),
      close: haClose, volume: c.volume,
    });
  }
  return ha;
}

function calcRSI(candles: KlineData[], period = 14): (number | null)[] {
  const rsi: (number | null)[] = [];
  if (candles.length < period + 1) return candles.map(() => null);
  let avgGain = 0, avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const d = candles[i].close - candles[i - 1].close;
    if (d > 0) avgGain += d; else avgLoss += Math.abs(d);
  }
  avgGain /= period; avgLoss /= period;
  for (let i = 0; i < period; i++) rsi.push(null);
  rsi.push(avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss));
  for (let i = period + 1; i < candles.length; i++) {
    const d = candles[i].close - candles[i - 1].close;
    avgGain = (avgGain * (period - 1) + (d > 0 ? d : 0)) / period;
    avgLoss = (avgLoss * (period - 1) + (d < 0 ? Math.abs(d) : 0)) / period;
    rsi.push(avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss));
  }
  return rsi;
}

function calcStochRSI(candles: KlineData[], rsiPeriod = 14, stochPeriod = 14, kSmooth = 3, dSmooth = 3) {
  const rsiVals = calcRSI(candles, rsiPeriod);
  const stochRaw: (number | null)[] = [];
  for (let i = 0; i < rsiVals.length; i++) {
    if (i < rsiPeriod + stochPeriod - 1 || rsiVals[i] === null) { stochRaw.push(null); continue; }
    let min = Infinity, max = -Infinity;
    for (let j = i - stochPeriod + 1; j <= i; j++) {
      const v = rsiVals[j];
      if (v !== null) { min = Math.min(min, v); max = Math.max(max, v); }
    }
    stochRaw.push(max === min ? 50 : ((rsiVals[i]! - min) / (max - min)) * 100);
  }
  const k: (number | null)[] = [];
  for (let i = 0; i < stochRaw.length; i++) {
    if (stochRaw[i] === null || i < kSmooth - 1) { k.push(null); continue; }
    let sum = 0, cnt = 0;
    for (let j = i - kSmooth + 1; j <= i; j++) { if (stochRaw[j] !== null) { sum += stochRaw[j]!; cnt++; } }
    k.push(cnt > 0 ? sum / cnt : null);
  }
  const d: (number | null)[] = [];
  for (let i = 0; i < k.length; i++) {
    if (k[i] === null || i < dSmooth - 1) { d.push(null); continue; }
    let sum = 0, cnt = 0;
    for (let j = i - dSmooth + 1; j <= i; j++) { if (k[j] !== null) { sum += k[j]!; cnt++; } }
    d.push(cnt > 0 ? sum / cnt : null);
  }
  return { k, d };
}

function calcLinearRegression(candles: KlineData[], mult = 2) {
  const n = candles.length;
  if (n < 2) return { mid: [] as number[], upper: [] as number[], lower: [] as number[], pearsonR: 0 };
  let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0, sumY2 = 0;
  for (let i = 0; i < n; i++) {
    const y = candles[i].close;
    sumX += i; sumY += y; sumXY += i * y; sumX2 += i * i; sumY2 += y * y;
  }
  const slope = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX);
  const intercept = (sumY - slope * sumX) / n;
  const denom = (n * sumX2 - sumX * sumX) * (n * sumY2 - sumY * sumY);
  const pearsonR = denom > 0 ? (n * sumXY - sumX * sumY) / Math.sqrt(denom) : 0;
  let sumSqErr = 0;
  for (let i = 0; i < n; i++) sumSqErr += (candles[i].close - (intercept + slope * i)) ** 2;
  const stdErr = Math.sqrt(sumSqErr / n);
  const mid: number[] = [], upper: number[] = [], lower: number[] = [];
  for (let i = 0; i < n; i++) {
    const v = intercept + slope * i;
    mid.push(v); upper.push(v + mult * stdErr); lower.push(v - mult * stdErr);
  }
  return { mid, upper, lower, pearsonR };
}

function findDivergences(candles: KlineData[], rsiValues: (number | null)[], lookback = 5) {
  const markers: { time: any; position: string; color: string; shape: string; text: string }[] = [];
  const rsiLines: { type: string; points: { time: any; value: number }[] }[] = [];
  const priceLines: { type: string; points: { time: any; value: number }[] }[] = [];
  const n = candles.length;
  const priceLows: number[] = [];
  const priceHighs: number[] = [];

  for (let i = lookback; i < n - lookback; i++) {
    if (rsiValues[i] === null) continue;
    let isLow = true, isHigh = true;
    for (let j = i - lookback; j <= i + lookback; j++) {
      if (j === i) continue;
      if (candles[j].low <= candles[i].low) isLow = false;
      if (candles[j].high >= candles[i].high) isHigh = false;
    }
    if (isLow) priceLows.push(i);
    if (isHigh) priceHighs.push(i);
  }

  const t = (idx: number) => candles[idx].time as any;

  for (let i = 1; i < priceLows.length; i++) {
    const curr = priceLows[i], prev = priceLows[i - 1];
    if (curr - prev > 60) continue;
    if (rsiValues[curr] === null || rsiValues[prev] === null) continue;
    if (candles[curr].low < candles[prev].low && rsiValues[curr]! > rsiValues[prev]!) {
      markers.push({ time: t(curr), position: 'belowBar', color: '#0ecb81', shape: 'arrowUp', text: 'Bull' });
      rsiLines.push({ type: 'bull', points: [{ time: t(prev), value: rsiValues[prev]! }, { time: t(curr), value: rsiValues[curr]! }] });
      priceLines.push({ type: 'bull', points: [{ time: t(prev), value: candles[prev].low }, { time: t(curr), value: candles[curr].low }] });
    }
  }

  for (let i = 1; i < priceHighs.length; i++) {
    const curr = priceHighs[i], prev = priceHighs[i - 1];
    if (curr - prev > 60) continue;
    if (rsiValues[curr] === null || rsiValues[prev] === null) continue;
    if (candles[curr].high > candles[prev].high && rsiValues[curr]! < rsiValues[prev]!) {
      markers.push({ time: t(curr), position: 'aboveBar', color: '#f6465d', shape: 'arrowDown', text: 'Bear' });
      rsiLines.push({ type: 'bear', points: [{ time: t(prev), value: rsiValues[prev]! }, { time: t(curr), value: rsiValues[curr]! }] });
      priceLines.push({ type: 'bear', points: [{ time: t(prev), value: candles[prev].high }, { time: t(curr), value: candles[curr].high }] });
    }
  }

  markers.sort((a, b) => (a.time as number) - (b.time as number));
  return { markers, rsiLines, priceLines };
}

function ema(source: number[], period: number): (number | null)[] {
  const result: (number | null)[] = new Array(source.length).fill(null);
  const alpha = 2 / (period + 1);
  let prev: number | null = null;
  for (let i = 0; i < source.length; i++) {
    if (source[i] === null || isNaN(source[i])) { result[i] = prev; continue; }
    prev = prev === null ? source[i] : alpha * source[i] + (1 - alpha) * prev;
    result[i] = prev;
  }
  return result;
}

function sma(source: (number | null)[], period: number): (number | null)[] {
  const result: (number | null)[] = new Array(source.length).fill(null);
  for (let i = period - 1; i < source.length; i++) {
    let sum = 0, valid = true;
    for (let j = i - period + 1; j <= i; j++) {
      if (source[j] === null || source[j] === undefined) { valid = false; break; }
      sum += source[j]!;
    }
    if (valid) result[i] = sum / period;
  }
  return result;
}

function calcWaveTrend(candles: KlineData[], n1 = 10, n2 = 21): { wt1: (number | null)[]; wt2: (number | null)[] } {
  const len = candles.length;
  const hlc3 = candles.map((c) => (c.high + c.low + c.close) / 3);
  const esaArr = ema(hlc3, n1);
  const absDiff = hlc3.map((v, i) => esaArr[i] !== null ? Math.abs(v - esaArr[i]!) : 0);
  const d = ema(absDiff, n1);
  const ci = hlc3.map((v, i) =>
    esaArr[i] !== null && d[i] !== null && d[i] !== 0 ? (v - esaArr[i]!) / (0.015 * d[i]!) : 0
  );
  const wt1 = ema(ci, n2);
  const wt2 = sma(wt1, 4);
  return { wt1, wt2 };
}

function calcNadarayaWatsonEnvelope(candles: KlineData[], bandwidth = 8, multiplier = 3.0) {
  const closes = candles.map((c) => c.close);
  const n = closes.length;
  if (n < 30) return { mid: [] as number[], upper: [] as number[], lower: [] as number[] };

  const yHat: number[] = [];
  for (let i = 0; i < n; i++) {
    let wSum = 0, vSum = 0;
    for (let j = 0; j < n; j++) {
      const d = (i - j) / bandwidth;
      const w = Math.exp(-0.5 * d * d);
      wSum += w;
      vSum += w * closes[j];
    }
    yHat.push(wSum > 1e-10 ? vSum / wSum : closes[i]);
  }

  let resSq = 0;
  for (let i = 0; i < n; i++) resSq += (closes[i] - yHat[i]) ** 2;
  const std = Math.sqrt(resSq / n);

  const mid: number[] = [], upper: number[] = [], lower: number[] = [];
  for (let i = 0; i < n; i++) {
    mid.push(yHat[i]);
    upper.push(yHat[i] + multiplier * std);
    lower.push(yHat[i] - multiplier * std);
  }
  return { mid, upper, lower };
}

function calcUTBotAlert(candles: KlineData[], atrPeriod = 10, keyValue = 1) {
  const n = candles.length;
  if (n < atrPeriod + 1) return { trailStop: [] as (number | null)[], buySignals: [] as number[], sellSignals: [] as number[] };

  const tr: number[] = [0];
  for (let i = 1; i < n; i++) {
    tr.push(Math.max(
      candles[i].high - candles[i].low,
      Math.abs(candles[i].high - candles[i - 1].close),
      Math.abs(candles[i].low - candles[i - 1].close)
    ));
  }

  const atr: (number | null)[] = new Array(n).fill(null);
  let sum = 0;
  for (let i = 1; i <= atrPeriod; i++) sum += tr[i];
  atr[atrPeriod] = sum / atrPeriod;
  for (let i = atrPeriod + 1; i < n; i++) {
    atr[i] = (atr[i - 1]! * (atrPeriod - 1) + tr[i]) / atrPeriod;
  }

  const trailStop: (number | null)[] = new Array(n).fill(null);
  const buySignals: number[] = [];
  const sellSignals: number[] = [];

  let prevTrail = 0;
  let prevClose = candles[atrPeriod].close;

  for (let i = atrPeriod; i < n; i++) {
    const nLoss = atr[i]! * keyValue;
    const close = candles[i].close;

    let trail: number;
    if (close > prevTrail && prevClose > prevTrail) {
      trail = Math.max(prevTrail, close - nLoss);
    } else if (close < prevTrail && prevClose < prevTrail) {
      trail = Math.min(prevTrail, close + nLoss);
    } else if (close > prevTrail) {
      trail = close - nLoss;
    } else {
      trail = close + nLoss;
    }

    if (prevClose <= prevTrail && close > trail) buySignals.push(i);
    if (prevClose >= prevTrail && close < trail) sellSignals.push(i);

    trailStop[i] = trail;
    prevTrail = trail;
    prevClose = close;
  }

  return { trailStop, buySignals, sellSignals };
}

const intervalMs: Record<string, number> = {
  '1': 60_000, '3': 180_000, '5': 300_000, '15': 900_000, '30': 1_800_000,
  '60': 3_600_000, '120': 7_200_000, '240': 14_400_000,
};

export default function TradingViewChart({ symbol, interval, chartType = 'heikinashi', positions = [] }: { symbol: string; interval: string; chartType?: 'heikinashi' | 'bar'; positions?: ChartPosition[] }) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const mainRef = useRef<HTMLDivElement>(null);
  const rsiRef = useRef<HTMLDivElement>(null);
  const stochRef = useRef<HTMLDivElement>(null);
  const wtRef = useRef<HTMLDivElement>(null);

  const mainChartRef = useRef<IChartApi | null>(null);
  const rsiChartRef = useRef<IChartApi | null>(null);
  const stochChartRef = useRef<IChartApi | null>(null);
  const wtChartRef = useRef<IChartApi | null>(null);

  const candlesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const lrMidRef = useRef<ISeriesApi<'Line'> | null>(null);
  const lrUpperRef = useRef<ISeriesApi<'Line'> | null>(null);
  const lrLowerRef = useRef<ISeriesApi<'Line'> | null>(null);

  const nwMidRef = useRef<ISeriesApi<'Line'> | null>(null);
  const nwUpperRef = useRef<ISeriesApi<'Line'> | null>(null);
  const nwLowerRef = useRef<ISeriesApi<'Line'> | null>(null);

  const utBotRef = useRef<ISeriesApi<'Line'> | null>(null);

  const rsiLineRef = useRef<ISeriesApi<'Line'> | null>(null);
  const rsi80Ref = useRef<ISeriesApi<'Line'> | null>(null);
  const rsi50Ref = useRef<ISeriesApi<'Line'> | null>(null);
  const rsi20Ref = useRef<ISeriesApi<'Line'> | null>(null);

  const stochKRef = useRef<ISeriesApi<'Line'> | null>(null);
  const stochDRef = useRef<ISeriesApi<'Line'> | null>(null);
  const stoch80Ref = useRef<ISeriesApi<'Line'> | null>(null);
  const stoch20Ref = useRef<ISeriesApi<'Line'> | null>(null);

  const wt1Ref = useRef<ISeriesApi<'Line'> | null>(null);
  const wt2Ref = useRef<ISeriesApi<'Line'> | null>(null);
  const wt60Ref = useRef<ISeriesApi<'Line'> | null>(null);
  const wtN60Ref = useRef<ISeriesApi<'Line'> | null>(null);
  const wt0Ref = useRef<ISeriesApi<'Line'> | null>(null);

  const rsiDivLinesRef = useRef<ISeriesApi<'Line'>[]>([]);
  const priceDivLinesRef = useRef<ISeriesApi<'Line'>[]>([]);
  const positionLinesRef = useRef<IPriceLine[]>([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [pearsonR, setPearsonR] = useState<number | null>(null);

  useEffect(() => {
    if (!mainRef.current || !rsiRef.current || !stochRef.current || !wtRef.current) return;

    const bg = { type: ColorType.Solid as const, color: '#0b0e11' };
    const grid = { vertLines: { color: 'rgba(42,46,57,0.3)' }, horzLines: { color: 'rgba(42,46,57,0.3)' } };
    const tsBase = { borderColor: '#2a2e39', timeVisible: true, secondsVisible: false, rightOffset: 5 };

    const mainChart = createChart(mainRef.current, {
      layout: { background: bg, textColor: '#848e9c', fontSize: 10 },
      grid, crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#2a2e39', scaleMargins: { top: 0.05, bottom: 0.25 } },
      timeScale: { ...tsBase, visible: false },
      handleScroll: { vertTouchDrag: false },
    });
    mainChartRef.current = mainChart;

    candlesRef.current = mainChart.addCandlestickSeries({
      upColor: '#0ecb81', downColor: '#f6465d',
      borderUpColor: '#0ecb81', borderDownColor: '#f6465d',
      wickUpColor: '#0ecb81', wickDownColor: '#f6465d',
    });
    volumeRef.current = mainChart.addHistogramSeries({
      priceFormat: { type: 'volume' }, priceScaleId: 'volume',
    });
    mainChart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 }, visible: false });

    lrMidRef.current = mainChart.addLineSeries({ color: '#e91e63', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });
    lrUpperRef.current = mainChart.addLineSeries({ color: 'rgba(33,150,243,0.6)', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    lrLowerRef.current = mainChart.addLineSeries({ color: 'rgba(33,150,243,0.6)', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });

    nwMidRef.current = mainChart.addLineSeries({ color: 'rgba(255,183,77,0.9)', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    nwUpperRef.current = mainChart.addLineSeries({ color: 'rgba(255,183,77,0.4)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });
    nwLowerRef.current = mainChart.addLineSeries({ color: 'rgba(255,183,77,0.4)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });

    utBotRef.current = mainChart.addLineSeries({ color: '#ffeb3b', lineWidth: 1, lineStyle: 0, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });

    const rsiChart = createChart(rsiRef.current, {
      layout: { background: bg, textColor: '#848e9c', fontSize: 10 },
      grid, crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#2a2e39', scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { ...tsBase, visible: false },
    });
    rsiChartRef.current = rsiChart;

    rsiLineRef.current = rsiChart.addLineSeries({ color: '#b39ddb', lineWidth: 1 });
    rsi80Ref.current = rsiChart.addLineSeries({ color: 'rgba(246,70,93,0.5)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    rsi50Ref.current = rsiChart.addLineSeries({ color: 'rgba(255,255,255,0.15)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    rsi20Ref.current = rsiChart.addLineSeries({ color: 'rgba(14,203,129,0.5)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });

    const stochChart = createChart(stochRef.current, {
      layout: { background: bg, textColor: '#848e9c', fontSize: 10 },
      grid, crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#2a2e39', scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { ...tsBase, visible: false },
    });
    stochChartRef.current = stochChart;

    stochKRef.current = stochChart.addLineSeries({ color: '#2196f3', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    stochDRef.current = stochChart.addLineSeries({ color: '#ff9800', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    stoch80Ref.current = stochChart.addLineSeries({ color: 'rgba(246,70,93,0.5)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    stoch20Ref.current = stochChart.addLineSeries({ color: 'rgba(14,203,129,0.5)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });

    const wtChart = createChart(wtRef.current, {
      layout: { background: bg, textColor: '#848e9c', fontSize: 10 },
      grid, crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#2a2e39', scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { ...tsBase, visible: true },
    });
    wtChartRef.current = wtChart;

    wt1Ref.current = wtChart.addLineSeries({ color: '#26a69a', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    wt2Ref.current = wtChart.addLineSeries({ color: '#ef5350', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    wt60Ref.current = wtChart.addLineSeries({ color: 'rgba(246,70,93,0.4)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    wtN60Ref.current = wtChart.addLineSeries({ color: 'rgba(14,203,129,0.4)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    wt0Ref.current = wtChart.addLineSeries({ color: 'rgba(255,255,255,0.15)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });

    const syncFrom = (source: IChartApi, targets: (IChartApi | null)[]) => {
      source.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (range) targets.forEach((t) => t?.timeScale().setVisibleLogicalRange(range));
      });
    };
    syncFrom(mainChart, [rsiChart, stochChart, wtChart]);
    syncFrom(rsiChart, [mainChart, stochChart, wtChart]);
    syncFrom(stochChart, [mainChart, rsiChart, wtChart]);
    syncFrom(wtChart, [mainChart, rsiChart, stochChart]);

    const resize = () => {
      if (!wrapperRef.current) return;
      const w = wrapperRef.current.clientWidth;
      const h = wrapperRef.current.clientHeight;
      if (w === 0 || h === 0) return;
      const mainH = Math.floor(h * 0.52);
      const rsiH = Math.floor(h * 0.16);
      const stochH = Math.floor(h * 0.16);
      const wtH = h - mainH - rsiH - stochH;
      mainChart.applyOptions({ width: w, height: mainH });
      rsiChart.applyOptions({ width: w, height: rsiH });
      stochChart.applyOptions({ width: w, height: stochH });
      wtChart.applyOptions({ width: w, height: wtH });
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(wrapperRef.current!);

    return () => {
      ro.disconnect();
      mainChart.remove(); rsiChart.remove(); stochChart.remove(); wtChart.remove();
      mainChartRef.current = null; rsiChartRef.current = null; stochChartRef.current = null; wtChartRef.current = null;
      candlesRef.current = null; volumeRef.current = null;
      lrMidRef.current = null; lrUpperRef.current = null; lrLowerRef.current = null;
      nwMidRef.current = null; nwUpperRef.current = null; nwLowerRef.current = null;
      utBotRef.current = null;
      rsiLineRef.current = null; rsi80Ref.current = null; rsi50Ref.current = null; rsi20Ref.current = null;
      stochKRef.current = null; stochDRef.current = null; stoch80Ref.current = null; stoch20Ref.current = null;
      wt1Ref.current = null; wt2Ref.current = null; wt60Ref.current = null; wtN60Ref.current = null; wt0Ref.current = null;
      rsiDivLinesRef.current = [];
      priceDivLinesRef.current = [];
      positionLinesRef.current = [];
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true); setError('');
      try {
        const raw = await api.get<KlineData[]>(`/scanner/klines/${symbol}?interval=${interval}&limit=50`);
        if (cancelled) return;
        if (!raw?.length) { setError('No data'); setLoading(false); return; }

        const candles = chartType === 'heikinashi' ? toHeikinAshi(raw) : raw;

        candlesRef.current?.setData(candles.map((c) => ({
          time: c.time as any, open: c.open, high: c.high, low: c.low, close: c.close,
        })));

        volumeRef.current?.setData(raw.map((c) => ({
          time: c.time as any, value: c.volume,
          color: c.close >= c.open ? 'rgba(14,203,129,0.3)' : 'rgba(246,70,93,0.3)',
        })));

        const lr = calcLinearRegression(raw, 2);
        setPearsonR(lr.pearsonR);
        if (lr.mid.length >= 2) {
          const t0 = raw[0].time as any;
          const t1 = raw[raw.length - 1].time as any;
          lrMidRef.current?.setData([{ time: t0, value: lr.mid[0] }, { time: t1, value: lr.mid[lr.mid.length - 1] }]);
          lrUpperRef.current?.setData([{ time: t0, value: lr.upper[0] }, { time: t1, value: lr.upper[lr.upper.length - 1] }]);
          lrLowerRef.current?.setData([{ time: t0, value: lr.lower[0] }, { time: t1, value: lr.lower[lr.lower.length - 1] }]);
        }

        const nw = calcNadarayaWatsonEnvelope(raw, 8, 3.0);
        if (nw.mid.length > 0) {
          const nwData = (arr: number[]) => arr.map((v, i) => ({ time: raw[i].time as any, value: v }));
          nwMidRef.current?.setData(nwData(nw.mid));
          nwUpperRef.current?.setData(nwData(nw.upper));
          nwLowerRef.current?.setData(nwData(nw.lower));
        }

        const utBot = calcUTBotAlert(raw, 10, 1);
        if (utBot.trailStop.length > 0) {
          const utData = utBot.trailStop
            .map((v, i) => v !== null ? { time: raw[i].time as any, value: v, color: raw[i].close > v ? '#0ecb81' : '#f6465d' } : null)
            .filter(Boolean) as any[];
          utBotRef.current?.setData(utData);
        }

        const utMarkers: any[] = [];
        for (const idx of utBot.buySignals) {
          utMarkers.push({ time: raw[idx].time as any, position: 'belowBar', color: '#0ecb81', shape: 'arrowUp', text: 'BUY' });
        }
        for (const idx of utBot.sellSignals) {
          utMarkers.push({ time: raw[idx].time as any, position: 'aboveBar', color: '#f6465d', shape: 'arrowDown', text: 'SELL' });
        }
        utMarkers.sort((a: any, b: any) => (a.time as number) - (b.time as number));

        const rsiVals = calcRSI(raw, 14);
        const filtered = (vals: (number | null)[]) =>
          vals.map((v, i) => v !== null ? { time: raw[i].time as any, value: v } : null).filter(Boolean) as any[];
        rsiLineRef.current?.setData(filtered(rsiVals));
        const times = raw.map((c) => ({ time: c.time as any }));
        rsi80Ref.current?.setData(times.map((p) => ({ ...p, value: 80 })));
        rsi50Ref.current?.setData(times.map((p) => ({ ...p, value: 50 })));
        rsi20Ref.current?.setData(times.map((p) => ({ ...p, value: 20 })));

        const divResult = findDivergences(raw, rsiVals, 5);

        if (candlesRef.current) {
          const allMarkers = [...divResult.markers, ...utMarkers].sort((a: any, b: any) => (a.time as number) - (b.time as number));
          candlesRef.current.setMarkers(allMarkers as any[]);
        }

        if (rsiChartRef.current) {
          for (const s of rsiDivLinesRef.current) {
            try { rsiChartRef.current.removeSeries(s); } catch {}
          }
          rsiDivLinesRef.current = [];
          for (const line of divResult.rsiLines) {
            const color = line.type === 'bull' ? '#0ecb81' : '#f6465d';
            const series = rsiChartRef.current.addLineSeries({
              color, lineWidth: 2, lineStyle: 0,
              priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
            });
            series.setData(line.points);
            rsiDivLinesRef.current.push(series);
          }
        }

        if (mainChartRef.current) {
          for (const s of priceDivLinesRef.current) {
            try { mainChartRef.current.removeSeries(s); } catch {}
          }
          priceDivLinesRef.current = [];
          for (const line of divResult.priceLines) {
            const color = line.type === 'bull' ? '#0ecb81' : '#f6465d';
            const series = mainChartRef.current.addLineSeries({
              color, lineWidth: 2, lineStyle: 0,
              priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
            });
            series.setData(line.points);
            priceDivLinesRef.current.push(series);
          }
        }

        const stoch = calcStochRSI(raw);
        stochKRef.current?.setData(filtered(stoch.k));
        stochDRef.current?.setData(filtered(stoch.d));
        stoch80Ref.current?.setData(times.map((p) => ({ ...p, value: 80 })));
        stoch20Ref.current?.setData(times.map((p) => ({ ...p, value: 20 })));

        const wt = calcWaveTrend(raw);
        wt1Ref.current?.setData(filtered(wt.wt1));
        wt2Ref.current?.setData(filtered(wt.wt2));
        wt60Ref.current?.setData(times.map((p) => ({ ...p, value: 60 })));
        wtN60Ref.current?.setData(times.map((p) => ({ ...p, value: -60 })));
        wt0Ref.current?.setData(times.map((p) => ({ ...p, value: 0 })));

        mainChartRef.current?.timeScale().fitContent();
        rsiChartRef.current?.timeScale().fitContent();
        stochChartRef.current?.timeScale().fitContent();
        wtChartRef.current?.timeScale().fitContent();
        setLoading(false);
      } catch (e: any) {
        if (!cancelled) { setError(e.message || 'Error'); setLoading(false); }
      }
    }

    load();
    const ms = intervalMs[interval] || 60_000;
    const timer = window.setInterval(load, Math.max(ms, 15_000));
    return () => { cancelled = true; clearInterval(timer); };
  }, [symbol, interval]);

  useEffect(() => {
    const series = candlesRef.current;
    if (!series) return;
    for (const pl of positionLinesRef.current) {
      try { series.removePriceLine(pl); } catch {}
    }
    positionLinesRef.current = [];
    const symPositions = positions.filter((p) => p.symbol === symbol);
    for (const p of symPositions) {
      const sideTag = p.side === 'long' ? 'L' : 'S';
      positionLinesRef.current.push(series.createPriceLine({
        price: p.entry_price,
        color: '#e0e0e0',
        lineWidth: 1,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: `${sideTag} ENTRY`,
      }));
      if (p.tp_price) {
        positionLinesRef.current.push(series.createPriceLine({
          price: p.tp_price,
          color: '#0ecb81',
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `${sideTag} TP`,
        }));
      }
      if (p.sl_price) {
        positionLinesRef.current.push(series.createPriceLine({
          price: p.sl_price,
          color: '#f6465d',
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `${sideTag} SL`,
        }));
      }
    }
  }, [positions, symbol]);

  return (
    <div ref={wrapperRef} className="relative w-full h-full flex flex-col">
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center z-10 bg-[#0b0e11]/80">
          <span className="text-gray-500 text-xs animate-pulse">Loading...</span>
        </div>
      )}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center z-10 bg-[#0b0e11]/80">
          <span className="text-red-400 text-xs">{error}</span>
        </div>
      )}
      {pearsonR !== null && (
        <div className="absolute top-1 left-12 z-20 text-[10px] font-mono pointer-events-none flex gap-3">
          <span className="text-[#e91e63]">R: {pearsonR.toFixed(4)}</span>
          <span className="text-[#ffb74d]">NW Envelope</span>
          <span className="text-[#ffeb3b]">UT Bot</span>
        </div>
      )}
      <div ref={mainRef} />
      <div className="relative">
        <span className="absolute top-0 left-1 z-10 text-[9px] text-[#b39ddb] pointer-events-none">RSI</span>
        <div ref={rsiRef} />
      </div>
      <div className="relative">
        <span className="absolute top-0 left-1 z-10 text-[9px] text-[#2196f3] pointer-events-none">StochRSI</span>
        <div ref={stochRef} />
      </div>
      <div className="relative">
        <span className="absolute top-0 left-1 z-10 text-[9px] text-[#26a69a] pointer-events-none">WT Cross</span>
        <div ref={wtRef} />
      </div>
    </div>
  );
}
