/** Collapsible data table panel — shows sorted regions with CBS values. */
import { useState } from 'react'
import { useChatStore } from '../../store/chatStore'

export function DataTable() {
  const [open, setOpen] = useState(false)

  const currentGeoJSON = useChatStore(s => s.currentGeoJSON)
  const currentPlan    = useChatStore(s => s.currentPlan)
  const selectedRegion = useChatStore(s => s.selectedRegion)
  const selectRegion   = useChatStore(s => s.selectRegion)

  const meta = currentGeoJSON?.meta
  if (!meta) return null   // boundary-only mode — no values to show

  const rows = (currentGeoJSON?.features ?? [])
    .filter(f => f.properties.value != null)
    .map(f => ({
      name:     f.properties.statnaam,
      statcode: f.properties.statcode,
      gm_code:  (f.properties as any).gm_code ?? '',
      value:    f.properties.value as number,
      label:    f.properties.label,
    }))
    .sort((a, b) => b.value - a.value)

  const total   = currentGeoJSON?.features?.length ?? 0
  const noData  = total - rows.length
  const period  = meta.period ? ` · ${meta.period.replace('JJ00', '')}` : ''

  return (
    <div className="flex flex-col shrink-0 border-t border-gray-200 dark:border-gray-700
                    bg-white dark:bg-gray-800"
    >
      {/* Toggle handle */}
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center justify-between w-full px-4 py-2 shrink-0
                   text-xs font-medium text-gray-600 dark:text-gray-400
                   hover:bg-gray-50 dark:hover:bg-gray-750 transition-colors"
      >
        <span className="flex items-center gap-2">
          <svg className="w-3.5 h-3.5 text-brand-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M3 10h18M3 14h18M10 3v18" />
          </svg>
          Datatabel — {rows.length} regio's{noData > 0 ? ` (${noData} geen data)` : ''}{period}
        </span>
        <svg
          className={`w-4 h-4 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
        </svg>
      </button>

      {/* Table */}
      {open && <div className="overflow-y-auto max-h-60 bg-white dark:bg-gray-800
                      border-t border-gray-100 dark:border-gray-700 custom-scrollbar">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-gray-50 dark:bg-gray-900 z-10">
            <tr className="border-b border-gray-200 dark:border-gray-700">
              <th className="px-3 py-2 text-left text-gray-500 dark:text-gray-400 font-semibold w-8">#</th>
              <th className="px-3 py-2 text-left text-gray-500 dark:text-gray-400 font-semibold">
                Regio
              </th>
              <th className="px-3 py-2 text-right text-gray-500 dark:text-gray-400 font-semibold">
                {currentPlan?.measure_code?.replace(/_\d+$/, '').replace(/([A-Z])/g, ' $1').trim() ?? 'Waarde'}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr
                key={row.name}
                onClick={() => selectRegion(
                  selectedRegion?.statcode === row.statcode ? null
                  : { statcode: row.statcode, statnaam: row.name, gm_code: row.gm_code }
                )}
                className={[
                  'cursor-pointer transition-colors',
                  selectedRegion?.statcode === row.statcode
                    ? 'bg-brand-50 dark:bg-brand-950'
                    : i % 2 === 0 ? 'bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-750'
                                  : 'bg-gray-50/70 dark:bg-gray-850 hover:bg-gray-100 dark:hover:bg-gray-750',
                ].join(' ')}
              >
                <td className="px-3 py-1.5 text-gray-400 dark:text-gray-600 tabular-nums">{i + 1}</td>
                <td className="px-3 py-1.5 text-gray-800 dark:text-gray-200 max-w-[180px] truncate">
                  {row.name}
                </td>
                <td className="px-3 py-1.5 text-right font-mono text-gray-700 dark:text-gray-300">
                  {row.label}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>}
    </div>
  )
}
