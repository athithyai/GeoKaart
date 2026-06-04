import { useEffect, useState } from 'react'

export function ThemeToggle() {
  const [dark, setDark] = useState(false)

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
  }, [dark])

  return (
    <button
      onClick={() => setDark(d => !d)}
      className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 dark:text-slate-500
                 dark:hover:text-slate-300 hover:bg-black/5 dark:hover:bg-white/10
                 transition-colors"
      title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
      aria-label="Toggle theme"
    >
      {dark ? (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364-6.364l-.707.707M6.343
               17.657l-.707.707M17.657 17.657l-.707-.707M6.343 6.343l-.707-.707
               M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
        </svg>
      ) : (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003
               9.003 0 008.354-5.646z" />
        </svg>
      )}
    </button>
  )
}
