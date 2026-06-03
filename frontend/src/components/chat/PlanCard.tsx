/** Collapsible JSON plan viewer with syntax highlighting. */
import type { MapPlan } from '../../types'

function highlightJson(json: string): string {
  return json
    .replace(/("(?:[^"\\]|\\.)*")(\s*:)/g, '<span class="json-key">$1</span>$2')
    .replace(/:\s*("(?:[^"\\]|\\.)*")/g, ': <span class="json-str">$1</span>')
    .replace(/:\s*(\d+\.?\d*)/g, ': <span class="json-num">$1</span>')
    .replace(/:\s*(true|false)/g, ': <span class="json-bool">$1</span>')
    .replace(/:\s*(null)/g, ': <span class="json-null">$1</span>')
}

interface Props {
  plan: MapPlan
}

export function PlanCard({ plan }: Props) {
  const json = JSON.stringify(plan, null, 2)
  const highlighted = highlightJson(json)

  return (
    <details className="mt-2 group">
      <summary
        className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400
                   cursor-pointer select-none hover:text-gray-700 dark:hover:text-gray-200
                   list-none transition-colors"
      >
        <svg
          className="w-3 h-3 transition-transform group-open:rotate-90"
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <span className="font-medium">Execution plan</span>
        <span className="opacity-60">· {plan.table_id} / {plan.geography_level}</span>
      </summary>

      <div className="mt-2 rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between px-3 py-1.5 bg-gray-100 dark:bg-gray-800
                        border-b border-gray-200 dark:border-gray-700">
          <span className="text-xs font-medium text-gray-500 dark:text-gray-400">JSON Plan</span>
          <button
            onClick={() => navigator.clipboard.writeText(json)}
            className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200
                       transition-colors"
          >
            Copy
          </button>
        </div>
        <pre
          className="text-xs font-mono p-3 overflow-x-auto bg-gray-50 dark:bg-gray-900
                     text-gray-800 dark:text-gray-200 leading-relaxed"
          dangerouslySetInnerHTML={{ __html: highlighted }}
        />
      </div>
    </details>
  )
}
