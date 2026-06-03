/** Floating tooltip shown on feature hover. */

interface Props {
  x: number
  y: number
  statnaam: string
  value: number | null
  label: string
  measureCode: string
  period: string
}

export function MapTooltip({ x, y, statnaam, label, measureCode, period }: Props) {
  return (
    <div
      className="pointer-events-none absolute z-20 animate-fade-in"
      style={{ left: x + 12, top: y - 8, transform: 'translateY(-100%)' }}
    >
      <div className="bg-white dark:bg-gray-900 rounded-xl shadow-xl border
                      border-gray-200 dark:border-gray-700 px-3 py-2.5 min-w-[140px]">
        <p className="font-semibold text-sm text-gray-900 dark:text-gray-100 leading-tight">
          {statnaam}
        </p>
        <div className="mt-1.5 flex items-baseline justify-between gap-3">
          <span className="text-xs text-gray-500 dark:text-gray-400 truncate max-w-[90px]">
            {measureCode}
          </span>
          <span className="text-sm font-bold text-brand-600 dark:text-brand-400 tabular-nums">
            {label}
          </span>
        </div>
        {period && (
          <p className="text-[10px] text-gray-400 dark:text-gray-600 mt-1">{period}</p>
        )}
      </div>
    </div>
  )
}
