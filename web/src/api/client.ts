import type { BacktestResult, DateRangeKey } from '../types'

export async function runBacktest(
  pineScript: string,
  range: DateRangeKey,
  symbol = 'NQ=F',
): Promise<BacktestResult> {
  const res = await fetch('/api/backtest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pineScript, range, symbol }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(typeof err.detail === 'string' ? err.detail : 'Backtest failed')
  }
  return res.json()
}

export async function uploadPineFile(
  file: File,
  range: DateRangeKey,
  symbol = 'NQ=F',
): Promise<BacktestResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('range', range)
  form.append('symbol', symbol)

  const res = await fetch('/api/backtest/upload', {
    method: 'POST',
    body: form,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(typeof err.detail === 'string' ? err.detail : 'Upload failed')
  }
  return res.json()
}
