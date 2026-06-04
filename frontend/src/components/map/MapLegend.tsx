/** Choropleth legend — floats bottom-right on the map. */

import type { ChoroplethMeta } from '../../types'

interface Props {
  meta: ChoroplethMeta
  measureCode: string
}

function fmt(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (Math.abs(v) >= 1_000)     return `${(v / 1_000).toFixed(0)}k`
  if (v !== Math.round(v))       return v.toFixed(1)
  return v.toFixed(0)
}

/** Pretty-print a CBS column name. */
function pretty(code: string): string {
  return code
    .replace(/_\d+$/, '')
    .replace(/([A-Z])/g, ' $1')
    .replace(/^Gemiddeld(e?)/, 'Avg.')
    .replace(/^Aantal/, '')
    .trim()
}

export function MapLegend({ meta, measureCode }: Props) {
  const { breaks, colors, null_color, n_matched, n_total } = meta
  const n = colors.length

  return (
    <div className="absolute bottom-8 right-3 z-10 glass rounded-xl shadow-lg p-3 min-w-[150px]
                    animate-[fadeIn_0.2s_ease-out]">
      <p className="text-[11px] font-semibold text-slate-700 dark:text-slate-200 mb-2 truncate max-w-[140px]">
        {pretty(measureCode)}
      </p>

      <div className="space-y-1">
        {colors.map((color, i) => {
          const lo  = breaks[i] ?? 0
          const hi  = breaks[i + 1] ?? breaks[i]
          const last = i === n - 1
          return (
            <div key={i} className="flex items-center gap-2">
              <div className="w-3.5 h-2.5 rounded-sm shrink-0 shadow-sm" style={{ backgroundColor: color }} />
              <span className="text-[10px] text-slate-500 dark:text-slate-400 tabular-nums">
                {fmt(lo)}{last ? '+' : `–${fmt(hi)}`}
              </span>
            </div>
          )
        })}
        <div className="flex items-center gap-2 pt-1 border-t border-black/5 dark:border-white/5">
          <div className="w-3.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: null_color }} />
          <span className="text-[10px] text-slate-400 dark:text-slate-500">No data</span>
        </div>
      </div>

      <p className="text-[9px] text-slate-400 dark:text-slate-600 mt-2 pt-1
                    border-t border-black/5 dark:border-white/5">
        {n_matched}/{n_total} regions
      </p>
    </div>
  )
}
