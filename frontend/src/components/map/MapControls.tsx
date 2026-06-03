/** Layer-level toggle buttons + selected region badge. */

import { useChatStore } from '../../store/chatStore'
import type { GeographyLevel } from '../../types'

const LEVELS: { value: GeographyLevel; label: string; sublabel: string }[] = [
  { value: 'gemeente', label: 'Gemeente', sublabel: 'municipalities' },
  // wijk + buurt kept for future use — not exposed in UI yet
]

export function MapControls() {
  const currentPlan    = useChatStore(s => s.currentPlan)
  const selectedRegion = useChatStore(s => s.selectedRegion)
  const isLayerLoading = useChatStore(s => s.isLayerLoading)
  const switchLayer    = useChatStore(s => s.switchLayer)
  const selectRegion   = useChatStore(s => s.selectRegion)

  const activeLevel = currentPlan?.geography_level ?? null

  return (
    <div className="absolute top-3 left-3 z-10 flex flex-col gap-2 pointer-events-auto">

      {/* Layer toggles */}
      <div className="bg-white dark:bg-gray-900 rounded-xl shadow-lg border
                      border-gray-200 dark:border-gray-700 overflow-hidden">
        <div className="px-3 py-1.5 border-b border-gray-100 dark:border-gray-800">
          <span className="font-display text-[10px] font-medium uppercase tracking-wider"
                style={{ color: '#878787' }}>
            Geography layer
          </span>
        </div>


        <div className="flex flex-col">
          {LEVELS.map(({ value, label, sublabel }) => {
            const isActive = activeLevel === value
            const disabled = isLayerLoading

            return (
              <button
                key={value}
                onClick={() => !disabled && switchLayer(value)}
                disabled={disabled}
                className={[
                  'flex items-center gap-2.5 px-3 py-2 text-left transition-colors',
                  'border-b border-gray-100 dark:border-gray-800 last:border-0',
                  isActive ? '' : 'hover:bg-gray-50 dark:hover:bg-gray-800',
                  disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer',
                ].join(' ')}
                style={isActive
                  ? { backgroundColor: '#e8f6fb', color: '#271D6C' }
                  : { color: '#091D23' }}
              >
                {/* Active indicator dot */}
                <span
                  className="w-1.5 h-1.5 rounded-full shrink-0 transition-colors"
                  style={{ backgroundColor: isActive ? '#00A1CD' : '#D2D2D2' }}
                />

                <span className="flex flex-col min-w-0">
                  <span className="text-xs font-medium leading-tight">{label}</span>
                  <span className="text-[10px] leading-tight" style={{ color: '#878787' }}>
                    {sublabel}
                  </span>
                </span>

                {isActive && isLayerLoading && (
                  <span className="ml-auto w-3 h-3 border-2 border-t-transparent
                                   rounded-full animate-spin shrink-0"
                        style={{ borderColor: '#00A1CD', borderTopColor: 'transparent' }} />
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* Selected region badge */}
      {selectedRegion && (
        <div className="bg-white dark:bg-gray-900 rounded-xl shadow-lg border
                        border-brand-200 dark:border-brand-800 px-3 py-2
                        flex items-start gap-2 max-w-[180px]">
          <div className="flex-1 min-w-0">
            <p className="font-display text-[10px] font-medium uppercase tracking-wider mb-0.5"
               style={{ color: '#0580A1' }}>
              Selected
            </p>
            <p className="text-xs font-medium text-gray-800 dark:text-gray-200 truncate">
              {selectedRegion.statnaam}
            </p>
            <p className="text-[10px] text-gray-400 dark:text-gray-500">
              {selectedRegion.statcode}
            </p>
          </div>
          <button
            onClick={() => selectRegion(null)}
            className="shrink-0 mt-0.5 text-gray-400 hover:text-gray-600
                       dark:hover:text-gray-200 transition-colors"
            title="Deselect region"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}
    </div>
  )
}
