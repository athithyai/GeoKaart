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
      <div className="glass rounded-xl shadow-2xl shadow-black/30 px-3.5 py-2.5 min-w-[150px]">
        <p className="font-semibold text-sm text-slate-800 dark:text-slate-100 leading-tight">
          {statnaam}
        </p>
        <div className="mt-1.5 flex items-baseline justify-between gap-4">
          <span className="text-[10px] text-slate-400 dark:text-slate-500 truncate max-w-[90px]">
            {measureCode.replace(/_\d+$/, '')}
          </span>
          <span className="text-sm font-bold tabular-nums" style={{ color: '#00A1CD' }}>
            {label}
          </span>
        </div>
        {period && (
          <p className="text-[9px] text-slate-400 dark:text-slate-600 mt-1">{period}</p>
        )}
      </div>
    </div>
  )
}
