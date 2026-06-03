import { useLangStore } from '../../store/langStore'
import type { Lang } from '../../i18n'

const LANGS: { value: Lang; label: string }[] = [
  { value: 'nl', label: 'NL' },
  { value: 'en', label: 'EN' },
]

export function LangToggle() {
  const { lang, setLang } = useLangStore()

  return (
    <div className="flex items-center rounded-lg border border-gray-200 dark:border-gray-700
                    overflow-hidden bg-gray-50 dark:bg-gray-800">
      {LANGS.map(({ value, label }) => {
        const active = lang === value
        return (
          <button
            key={value}
            onClick={() => setLang(value)}
            className={[
              'px-2.5 py-1 text-xs font-semibold transition-colors',
              active
                ? 'bg-brand-600 text-white'
                : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200',
            ].join(' ')}
            aria-pressed={active}
          >
            {label}
          </button>
        )
      })}
    </div>
  )
}
