import type { Trade } from '../types'
import { formatUsd } from '../utils/format'

interface TradesTableProps {
  trades: Trade[]
}

export function TradesTable({ trades }: TradesTableProps) {
  if (!trades.length) {
    return (
      <div className="rounded-lg border border-[var(--tv-border)] bg-[var(--tv-panel)] p-6 text-center text-sm text-[var(--tv-muted)]">
        No trades in this range.
      </div>
    )
  }

  const recent = [...trades].reverse().slice(0, 50)

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--tv-border)] bg-[var(--tv-panel)]">
      <div className="border-b border-[var(--tv-border)] px-5 py-3">
        <h2 className="text-sm font-medium">List of trades</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-[var(--tv-muted)]">
            <tr className="border-b border-[var(--tv-border)]">
              <th className="px-4 py-2 font-normal">Entry</th>
              <th className="px-4 py-2 font-normal">Exit</th>
              <th className="px-4 py-2 font-normal">Side</th>
              <th className="px-4 py-2 font-normal">Qty</th>
              <th className="px-4 py-2 font-normal">Entry price</th>
              <th className="px-4 py-2 font-normal">Exit price</th>
              <th className="px-4 py-2 font-normal">P&L</th>
              <th className="px-4 py-2 font-normal">Reason</th>
            </tr>
          </thead>
          <tbody>
            {recent.map((trade, i) => {
              const positive = trade.pnlNet >= 0
              return (
                <tr
                  key={`${trade.entryTime}-${i}`}
                  className="border-b border-[var(--tv-border)] last:border-b-0"
                >
                  <td className="px-4 py-2 tabular-nums text-[var(--tv-muted)]">
                    {new Date(trade.entryTime).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 tabular-nums text-[var(--tv-muted)]">
                    {new Date(trade.exitTime).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 capitalize">{trade.side}</td>
                  <td className="px-4 py-2 tabular-nums">{trade.contracts}</td>
                  <td className="px-4 py-2 tabular-nums">{trade.entryPrice.toFixed(2)}</td>
                  <td className="px-4 py-2 tabular-nums">{trade.exitPrice.toFixed(2)}</td>
                  <td
                    className={`px-4 py-2 tabular-nums font-medium ${
                      positive ? 'text-[var(--tv-green)]' : 'text-[var(--tv-red)]'
                    }`}
                  >
                    {positive ? '+' : '-'}
                    {formatUsd(trade.pnlNet)}
                  </td>
                  <td className="px-4 py-2 text-[var(--tv-muted)]">{trade.exitReason}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
