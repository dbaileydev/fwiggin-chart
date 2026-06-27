import type { BacktestSummary } from '../types'
import { formatPct, formatUsd } from '../utils/format'

interface KeyStatsProps {
  summary: BacktestSummary
}

function StatCard({
  label,
  primary,
  secondary,
  positive,
}: {
  label: string
  primary: string
  secondary?: string
  positive?: boolean | null
}) {
  const color =
    positive === true
      ? 'text-[var(--tv-green)]'
      : positive === false
        ? 'text-[var(--tv-red)]'
        : 'text-[var(--tv-text)]'

  return (
    <div className="min-w-0 flex-1 border-r border-[var(--tv-border)] px-5 py-4 last:border-r-0">
      <div className="mb-2 text-xs text-[var(--tv-muted)]">{label}</div>
      <div className={`text-xl font-medium tabular-nums ${color}`}>{primary}</div>
      {secondary && (
        <div className={`mt-0.5 text-sm tabular-nums ${color}`}>{secondary}</div>
      )}
    </div>
  )
}

export function KeyStats({ summary }: KeyStatsProps) {
  const pnlPositive = summary.totalPnl >= 0

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--tv-border)] bg-[var(--tv-panel)]">
      <div className="border-b border-[var(--tv-border)] px-5 py-3">
        <h2 className="text-sm font-medium text-[var(--tv-text)]">Key stats</h2>
      </div>
      <div className="flex flex-wrap divide-x-0 md:flex-nowrap">
        <StatCard
          label="Total P&L"
          primary={`${pnlPositive ? '+' : '-'}${formatUsd(summary.totalPnl)} USD`}
          secondary={formatPct(summary.totalPnlPct, true)}
          positive={pnlPositive}
        />
        <StatCard
          label="Max drawdown"
          primary={`${formatUsd(summary.maxDrawdownUsd)} USD`}
          secondary={formatPct(summary.maxDrawdownPct)}
        />
        <StatCard
          label="Profitable trades"
          primary={formatPct(summary.profitableTradesPct)}
          secondary={`${summary.profitableTrades}/${summary.totalTrades}`}
        />
        <StatCard
          label="Profit factor"
          primary={summary.profitFactor.toFixed(3)}
        />
      </div>
    </div>
  )
}
