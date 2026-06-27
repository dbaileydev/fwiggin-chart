export type DateRangeKey =
  | '7d'
  | '30d'
  | '90d'
  | 'this_year'
  | 'last_year'
  | 'all_time'

export interface BacktestSummary {
  totalPnl: number
  totalPnlPct: number
  maxDrawdownUsd: number
  maxDrawdownPct: number
  profitableTradesPct: number
  profitableTrades: number
  totalTrades: number
  profitFactor: number
  initialCapital: number
  endingEquity: number
}

export interface EquityPoint {
  time: string
  equity: number
}

export interface TradeBar {
  time: string
  pnl: number
  color: string
}

export interface Trade {
  side: string
  entryTime: string
  exitTime: string
  entryPrice: number
  exitPrice: number
  pnlNet: number
  exitReason: string
  contracts: number
}

export interface BacktestResult {
  strategyName: string
  pineVersion: number | null
  isStrategy: boolean
  range: {
    key: DateRangeKey
    label: string
    interval: string
    barCount: number
    start: string
    end: string
  }
  symbol: string
  summary: BacktestSummary
  equityCurve: EquityPoint[]
  tradeBars: TradeBar[]
  trades: Trade[]
  executionNote: string
}

export const DATE_RANGES: { key: DateRangeKey; label: string }[] = [
  { key: '7d', label: 'Last 7 days' },
  { key: '30d', label: 'Last 30 days' },
  { key: '90d', label: 'Last 90 days' },
  { key: 'this_year', label: 'This year' },
  { key: 'last_year', label: 'Last year' },
  { key: 'all_time', label: 'All time' },
]
