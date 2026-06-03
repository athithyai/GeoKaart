/** Choropleth color legend. */

import type { ChoroplethMeta } from '../../types'

interface Props {
  meta: ChoroplethMeta
  measureCode: string
}

function formatBreak(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(0)}k`
  if (v !== Math.round(v)) return v.toFixed(1)
  return v.toFixed(0)
}

export function MapLegend({ meta, measureCode }: Props) {
  const { breaks, colors, null_color, n_matched, n_total } = meta
  const n = colors.length

  return (
    <div className="absolute bottom-8 right-4 z-10 bg-white/95 dark:bg-gray-900/95
                    backdrop-blur-sm rounded-xl shadow-lg border border-gray-200
                    dark:border-gray-700 p-3 min-w-[160px] animate-fade-in">
      {/* Title */}
      <p className="font-display text-xs font-medium mb-2 truncate max-w-[150px]" style={{ color: '#271D6C' }}>
        {measureCode}
      </p>

      {/* Color scale */}
      <div className="space-y-1">
        {colors.map((color, i) => {
          const lo = breaks[i] ?? 0
          const hi = breaks[i + 1] ?? breaks[i]
          const isLast = i === n - 1
          return (
            <div key={i} className="flex items-center gap-2">
              <div
                className="w-4 h-3 rounded-sm shrink-0"
                style={{ backgroundColor: color }}
              />
              <span className="text-[11px] text-gray-600 dark:text-gray-400 tabular-nums">
                {formatBreak(lo)}{isLast ? '+' : ` – ${formatBreak(hi)}`}
              </span>
            </div>
          )
        })}

        {/* No data */}
        <div className="flex items-center gap-2 mt-0.5 pt-0.5 border-t border-gray-100 dark:border-gray-800">
          <div className="w-4 h-3 rounded-sm shrink-0" style={{ backgroundColor: null_color }} />
          <span className="text-[11px] text-gray-400 dark:text-gray-500">No data</span>
        </div>
      </div>

      {/* Match stats */}
      <p className="text-[10px] text-gray-400 dark:text-gray-600 mt-2">
        {n_matched} / {n_total} regions
      </p>
    </div>
  )
}
