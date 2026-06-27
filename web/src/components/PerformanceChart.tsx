import { useEffect, useRef } from 'react'
import {
  ColorType,
  createChart,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from 'lightweight-charts'
import type { BacktestResult } from '../types'
import { dedupeSeries, dedupeTradeBars } from '../utils/chartData'

interface PerformanceChartProps {
  result: BacktestResult
}

function toUnix(iso: string): Time {
  return Math.floor(new Date(iso).getTime() / 1000) as Time
}

export function PerformanceChart({ result }: PerformanceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const lineRef = useRef<ISeriesApi<'Line'> | null>(null)
  const histRef = useRef<ISeriesApi<'Histogram'> | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#1e222d' },
        textColor: '#787b86',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: '#2a2e39' },
        horzLines: { color: '#2a2e39' },
      },
      rightPriceScale: {
        borderColor: '#2a2e39',
      },
      timeScale: {
        borderColor: '#2a2e39',
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        vertLine: { color: '#787b86', width: 1, style: 2 },
        horzLine: { color: '#787b86', width: 1, style: 2 },
      },
    })

    const lineSeries = chart.addSeries(LineSeries, {
      color: '#26a69a',
      lineWidth: 2,
      priceLineVisible: true,
      lastValueVisible: true,
      crosshairMarkerRadius: 4,
    })

    const histSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      priceScaleId: 'trades',
    })

    chart.priceScale('trades').applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
      visible: false,
    })

    chartRef.current = chart
    lineRef.current = lineSeries
    histRef.current = histSeries

    const observer = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect
      chart.applyOptions({ width, height })
    })
    observer.observe(containerRef.current)

    return () => {
      observer.disconnect()
      chart.remove()
      chartRef.current = null
      lineRef.current = null
      histRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!lineRef.current || !histRef.current) return

    const initial = result.summary.initialCapital
    const equityData = dedupeSeries(
      result.equityCurve.map((p) => ({
        time: toUnix(p.time),
        value: p.equity - initial,
      })),
    )

    const tradeData = dedupeTradeBars(
      result.tradeBars.map((t) => ({
        time: toUnix(t.time),
        value: t.pnl,
        color: t.color,
      })),
    )

    lineRef.current.setData(equityData)
    histRef.current.setData(tradeData)
    chartRef.current?.timeScale().fitContent()
  }, [result])

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--tv-border)] bg-[var(--tv-panel)]">
      <div className="flex border-b border-[var(--tv-border)]">
        <div className="w-44 shrink-0 border-r border-[var(--tv-border)] p-3">
          <div className="space-y-2 text-sm">
            <div className="rounded bg-[#ffffff0d] px-2 py-1.5 text-[var(--tv-text)]">
              Cumulative P&L
            </div>
            <div className="px-2 py-1.5 text-[var(--tv-muted)]">Buy and hold</div>
            <div className="px-2 py-1.5 text-[var(--tv-muted)]">Trades excursions</div>
            <div className="px-2 py-1.5 text-[var(--tv-muted)]">Run-ups and drawdowns</div>
          </div>
        </div>
        <div className="min-w-0 flex-1">
          <div className="border-b border-[var(--tv-border)] px-4 py-2 text-sm text-[var(--tv-muted)]">
            Performance
          </div>
          <div ref={containerRef} className="h-[360px] w-full" />
        </div>
      </div>
    </div>
  )
}
