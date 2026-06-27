import type { Time } from 'lightweight-charts'

type TimedPoint = { time: Time; value: number }

/** lightweight-charts requires strictly ascending unique timestamps */
export function dedupeSeries(points: TimedPoint[]): TimedPoint[] {
  if (!points.length) return []

  const sorted = [...points].sort(
    (a, b) => (a.time as number) - (b.time as number),
  )

  const out: TimedPoint[] = []
  for (const point of sorted) {
    const prev = out[out.length - 1]
    if (prev && prev.time === point.time) {
      prev.value = point.value
    } else {
      out.push({ ...point })
    }
  }
  return out
}

type TradeBarPoint = { time: Time; value: number; color: string }

export function dedupeTradeBars(points: TradeBarPoint[]): TradeBarPoint[] {
  if (!points.length) return []

  const sorted = [...points].sort(
    (a, b) => (a.time as number) - (b.time as number),
  )

  const out: TradeBarPoint[] = []
  for (const point of sorted) {
    const prev = out[out.length - 1]
    if (prev && prev.time === point.time) {
      prev.value += point.value
      prev.color = prev.value >= 0 ? '#26a69a' : '#ef5350'
    } else {
      out.push({ ...point })
    }
  }
  return out
}
