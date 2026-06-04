/** Collapsible data table — glass panel at the map bottom. */
import { useState } from 'react'
import { useChatStore } from '../../store/chatStore'

export function DataTable() {
  const [open, setOpen] = useState(false)

  const currentGeoJSON = useChatStore(s => s.currentGeoJSON)
  const currentPlan    = useChatStore(s => s.currentPlan)
  const selectedRegion = useChatStore(s => s.selectedRegion)
  const selectRegion   = useChatStore(s => s.selectRegion)

  const meta = currentGeoJSON?.meta
  if (!meta) return null

  const rows = (currentGeoJSON?.features ?? [])
    .filter(f => f.properties.value != null)
    .map(f => ({
      name:     f.properties.statnaam,
      statcode: f.properties.statcode,
      gm_code:  ((f.properties as unknown) as Record<string, unknown>).gm_code as string ?? '',
      value:    f.properties.value as number,
      label:    f.properties.label,
      color:    f.properties.color,
    }))
    .sort((a, b) => b.value - a.value)

  const total   = currentGeoJSON?.features?.length ?? 0
  const noData  = total - rows.length
  const period  = meta.period ? ` · ${meta.period.replace('JJ00', '')}` : ''
  const measure = currentPlan?.measure_code?.replace(/_\d+$/, '').replace(/([A-Z])/g, ' $1').trim() ?? 'Value'

  return (
    <div className={[
      'glass border-t border-black/5 dark:border-white/5',
      'transition-all duration-300',
      open ? 'shadow-2xl shadow-black/20' : 'shadow-sm',
    ].join(' ')}>
      {/* Toggle handle */}
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center justify-between w-full px-4 py-2
                   text-xs font-medium text-slate-500 dark:text-slate-400
                   hover:text-slate-700 dark:hover:text-slate-200 transition-colors"
      >
        <span className="flex items-center gap-2">
          <svg className="w-3.5 h-3.5 text-brand-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h18M3 14h18M10 3v18" />
          </svg>
          <span>
            <span className="font-semibold text-slate-700 dark:text-slate-200">{rows.length}</span>
            <span className="text-slate-400 dark:text-slate-500"> regions{noData > 0 ? ` · ${noData} no data` : ''}{period}</span>
          </span>
        </span>
        <svg
          className={`w-4 h-4 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
        </svg>
      </button>

      {/* Table */}
      {open && (
        <div className="overflow-y-auto max-h-52 custom-scrollbar
                        border-t border-black/5 dark:border-white/5">
          <table className="w-full text-xs">
            <thead className="sticky top-0 glass z-10">
              <tr className="border-b border-black/5 dark:border-white/5">
                <th className="px-4 py-2 text-left text-slate-400 dark:text-slate-500 font-semibold w-8">#</th>
                <th className="px-4 py-2 text-left text-slate-400 dark:text-slate-500 font-semibold">Region</th>
                <th className="px-4 py-2 text-right text-slate-400 dark:text-slate-500 font-semibold">{measure}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => {
                const isSelected = selectedRegion?.statcode === row.statcode
                return (
                  <tr
                    key={row.name}
                    onClick={() => selectRegion(
                      isSelected ? null : { statcode: row.statcode, statnaam: row.name, gm_code: row.gm_code }
                    )}
                    className={[
                      'cursor-pointer transition-colors',
                      isSelected
                        ? 'bg-brand-50 dark:bg-brand-950/30'
                        : i % 2 === 0
                        ? 'hover:bg-black/3 dark:hover:bg-white/3'
                        : 'bg-black/1 dark:bg-white/1 hover:bg-black/3 dark:hover:bg-white/3',
                    ].join(' ')}
                  >
                    <td className="px-4 py-1.5 text-slate-300 dark:text-slate-600 tabular-nums">{i + 1}</td>
                    <td className="px-4 py-1.5 flex items-center gap-2">
                      <div className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: row.color }} />
                      <span className="text-slate-700 dark:text-slate-200 truncate max-w-[160px]">{row.name}</span>
                    </td>
                    <td className="px-4 py-1.5 text-right font-mono text-slate-600 dark:text-slate-300">
                      {row.label}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
