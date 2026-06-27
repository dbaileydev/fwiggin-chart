export function formatUsd(value: number, signed = false): string {
  const abs = Math.abs(value)
  const formatted = abs.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
  if (signed) {
    const prefix = value >= 0 ? '+' : '-'
    return `${prefix}${formatted}`
  }
  return formatted
}

export function formatPct(value: number, signed = false): string {
  const prefix = signed && value >= 0 ? '+' : ''
  return `${prefix}${value.toFixed(2)}%`
}
