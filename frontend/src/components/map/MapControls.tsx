/** Layer toggle panel — floats top-right on the map. */

import { useChatStore } from '../../store/chatStore'
import type { GeographyLevel } from '../../types'

interface LayerDef {
  value: GeographyLevel
  label: string
  sublabel: string
  icon: string
}

const LAYERS: LayerDef[] = [
  { value: 'gemeente', label: 'Gemeente',    sublabel: '342 municipalities', icon: '▦' },
  { value: 'wijk',     label: 'Wijk',        sublabel: '3.4k districts',     icon: '▤' },
  { value: 'buurt',    label: 'Buurt',       sublabel: '14k neighbourhoods', icon: '▣' },
]

export function MapControls() {
  const currentPlan    = useChatStore(s => s.currentPlan)
  const selectedRegion = useChatStore(s => s.selectedRegion)
  const isLayerLoading = useChatStore(s => s.isLayerLoading)
  const switchLayer    = useChatStore(s => s.switchLayer)
  const selectRegion   = useChatStore(s => s.selectRegion)

  const activeLevel = currentPlan?.geography_level ?? 'gemeente'

  return (
    <div className="absolute top-3 right-3 z-10 flex flex-col gap-2 pointer-events-auto">

      {/* Layer panel */}
      <div className="glass rounded-xl shadow-lg overflow-hidden">
        <div className="px-3 py-2 border-b border-black/5 dark:border-white/5">
          <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">
            Layers
          </span>
        </div>
        <div className="p-1 flex flex-col gap-0.5">
          {LAYERS.map(({ value, label, sublabel, icon }) => {
            const isActive = activeLevel === value

            return (
              <button
                key={value}
                onClick={() => !isLayerLoading && switchLayer(value)}
                disabled={isLayerLoading}
                className={[
                  'flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition-all duration-150',
                  isActive
                    ? 'bg-brand-400 text-white shadow-sm'
                    : 'text-slate-600 dark:text-slate-300 hover:bg-black/5 dark:hover:bg-white/10',
                  isLayerLoading ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer',
                ].join(' ')}
              >
                <span className="text-sm leading-none opacity-70">{icon}</span>
                <span className="flex flex-col min-w-0">
                  <span className="text-xs font-semibold leading-tight">{label}</span>
                  <span className={`text-[10px] leading-tight ${isActive ? 'text-white/70' : 'text-slate-400 dark:text-slate-500'}`}>
                    {sublabel}
                  </span>
                </span>
                {isActive && isLayerLoading && (
                  <span className="ml-auto w-3 h-3 border-2 border-white/40 border-t-white
                                   rounded-full animate-spin shrink-0" />
                )}
                {isActive && !isLayerLoading && (
                  <svg className="ml-auto w-3 h-3 shrink-0 text-white/80" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                  </svg>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* Selected region badge */}
      {selectedRegion && (
        <div className="glass rounded-xl shadow-lg px-3 py-2.5 flex items-start gap-2 max-w-[180px]
                        border-l-2 border-brand-400 animate-[fadeIn_0.2s_ease-out]">
          <div className="flex-1 min-w-0">
            <p className="text-[9px] font-bold uppercase tracking-widest text-brand-500 dark:text-brand-400 mb-0.5">
              Selected
            </p>
            <p className="text-xs font-semibold text-slate-800 dark:text-slate-100 truncate">
              {selectedRegion.statnaam}
            </p>
            <p className="text-[10px] text-slate-400 dark:text-slate-500 mt-0.5">
              {selectedRegion.statcode}
            </p>
          </div>
          <button
            onClick={() => selectRegion(null)}
            className="shrink-0 mt-0.5 w-5 h-5 rounded-full flex items-center justify-center
                       text-slate-400 hover:text-slate-600 dark:hover:text-slate-200
                       hover:bg-black/5 dark:hover:bg-white/10 transition-colors"
            title="Deselect"
          >
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}
    </div>
  )
}
