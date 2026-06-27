import type { DateRangeKey } from '../types'
import { DATE_RANGES } from '../types'

interface DateRangePickerProps {
  value: DateRangeKey
  onChange: (range: DateRangeKey) => void
  disabled?: boolean
}

export function DateRangePicker({ value, onChange, disabled }: DateRangePickerProps) {
  return (
    <div className="flex flex-wrap gap-1 rounded-lg border border-[var(--tv-border)] bg-[var(--tv-panel)] p-1">
      {DATE_RANGES.map((range) => {
        const active = range.key === value
        return (
          <button
            key={range.key}
            type="button"
            disabled={disabled}
            onClick={() => onChange(range.key)}
            className={[
              'rounded px-3 py-1.5 text-sm transition-colors disabled:opacity-50',
              active
                ? 'bg-[var(--tv-accent)] text-white'
                : 'text-[var(--tv-muted)] hover:bg-[#ffffff0d] hover:text-[var(--tv-text)]',
            ].join(' ')}
          >
            {range.label}
          </button>
        )
      })}
    </div>
  )
}
