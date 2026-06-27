import { useCallback, useState } from 'react'
import { runBacktest } from './api/client'
import { DateRangePicker } from './components/DateRangePicker'
import { KeyStats } from './components/KeyStats'
import { PerformanceChart } from './components/PerformanceChart'
import { PineDropzone } from './components/PineDropzone'
import { TradesTable } from './components/TradesTable'
import type { BacktestResult, DateRangeKey } from './types'

const DEFAULT_PINE = `//@version=5
strategy("Session Levels", overlay=true,
     initial_capital=50000, currency=currency.USD,
     calc_on_every_tick=false, process_orders_on_close=true)
// Drop or paste your full Pine Script strategy here.
`

export default function App() {
  const [pineScript, setPineScript] = useState(DEFAULT_PINE)
  const [fileName, setFileName] = useState<string | null>(null)
  const [range, setRange] = useState<DateRangeKey>('90d')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<BacktestResult | null>(null)

  const handleScriptChange = useCallback((script: string, name: string | null) => {
    setPineScript(script)
    setFileName(name)
  }, [])

  const handleRun = useCallback(async () => {
    if (!pineScript.trim()) {
      setError('Paste or drop a Pine Script strategy first.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await runBacktest(pineScript, range)
      setResult(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Backtest failed')
    } finally {
      setLoading(false)
    }
  }, [pineScript, range])

  return (
    <div className="min-h-full bg-[var(--tv-bg)]">
      <header className="border-b border-[var(--tv-border)] bg-[var(--tv-panel)] px-6 py-4">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold text-[var(--tv-text)]">
              Strategy Backtester
            </h1>
            <p className="text-sm text-[var(--tv-muted)]">
              Drop Pine Script · run across date ranges · TradingView-style results
            </p>
          </div>
          {result && (
            <div className="text-right text-sm">
              <div className="font-medium text-[var(--tv-text)]">{result.strategyName}</div>
              <div className="text-[var(--tv-muted)]">
                {result.symbol} · {result.range.label} · {result.range.interval} ·{' '}
                {result.range.barCount.toLocaleString()} bars
              </div>
            </div>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-4 px-6 py-6">
        <div className="grid gap-4 lg:grid-cols-[1fr_auto] lg:items-start">
          <PineDropzone
            pineScript={pineScript}
            fileName={fileName}
            onScriptChange={handleScriptChange}
            disabled={loading}
          />
          <div className="flex w-full flex-col gap-3 lg:w-72">
            <DateRangePicker value={range} onChange={setRange} disabled={loading} />
            <button
              type="button"
              onClick={handleRun}
              disabled={loading}
              className="rounded-lg bg-[var(--tv-accent)] px-4 py-3 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {loading ? 'Running backtest…' : 'Run backtest'}
            </button>
            {error && (
              <div className="rounded-lg border border-[var(--tv-red)] bg-[#ef535015] px-3 py-2 text-sm text-[var(--tv-red)]">
                {error}
              </div>
            )}
          </div>
        </div>

        {result && (
          <>
            {result.executionNote && (
              <div className="rounded-lg border border-[#f7931a55] bg-[#f7931a12] px-4 py-3 text-sm text-[#f7931a]">
                {result.executionNote}
              </div>
            )}
            <KeyStats summary={result.summary} />
            <PerformanceChart result={result} />
            <TradesTable trades={result.trades} />
          </>
        )}

        {!result && !loading && (
          <div className="rounded-lg border border-dashed border-[var(--tv-border)] px-6 py-16 text-center">
            <p className="text-[var(--tv-muted)]">
              Drop your Pine Script strategy and pick a date range to see results.
            </p>
          </div>
        )}
      </main>
    </div>
  )
}
