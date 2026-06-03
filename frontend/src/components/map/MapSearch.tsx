/** Map search box — find gemeente by name with live autocomplete.
 *  Wijk + buurt search kept for future use; only gemeente shown for now.
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '../../api/client'
import { useChatStore } from '../../store/chatStore'
import type { SearchResult } from '../../types'

export function MapSearch() {
  const [open,    setOpen]    = useState(false)
  const [query,   setQuery]   = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [focused, setFocused] = useState(false)
  const inputRef    = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const selectRegion = useChatStore(s => s.selectRegion)
  const setFlyTo     = useChatStore(s => s.setFlyTo)

  // Search with debounce
  const doSearch = useCallback(async (q: string) => {
    if (q.trim().length < 2) {
      setResults([])
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const { results: r } = await api.search(q.trim())
      // Only show gemeente results — wijk/buurt hidden until future release
      setResults(r.filter(x => x.level === 'gemeente'))
    } catch {
      setResults([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => doSearch(query), 280)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [query, doSearch])

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
        setFocused(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  function handleSelect(r: SearchResult) {
    selectRegion({ statcode: r.statcode, statnaam: r.statnaam, gm_code: r.gm_code })
    setFlyTo(r.statcode)
    setQuery('')
    setResults([])
    setOpen(false)
    setFocused(false)
  }

  function handleIconClick() {
    if (open) {
      setOpen(false)
      setQuery('')
      setResults([])
    } else {
      setOpen(true)
      setTimeout(() => inputRef.current?.focus(), 80)
    }
  }

  const showDropdown = focused && (results.length > 0 || (query.length >= 2 && !loading))

  return (
    <div ref={containerRef} className="flex flex-col items-end gap-1">
      <div
        className="flex items-center bg-white dark:bg-gray-900 rounded-xl shadow-lg border
                   border-gray-200 dark:border-gray-700 overflow-hidden transition-all duration-200"
        style={{ width: open ? 220 : 36, height: 36 }}
      >
        {/* Search icon button */}
        <button
          onClick={handleIconClick}
          className="shrink-0 w-9 h-9 flex items-center justify-center
                     text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors"
          title={open ? 'Close search' : 'Search regions'}
        >
          {open ? (
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/>
            </svg>
          ) : (
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z"/>
            </svg>
          )}
        </button>

        {/* Input */}
        {open && (
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onFocus={() => setFocused(true)}
            placeholder="Zoek gemeente…"
            className="flex-1 h-full px-1 pr-2 text-xs bg-transparent outline-none
                       placeholder-gray-400 dark:placeholder-gray-500
                       text-gray-800 dark:text-gray-200"
          />
        )}

        {/* Loading spinner */}
        {open && loading && (
          <span className="shrink-0 mr-2 w-3 h-3 border-2 border-t-transparent rounded-full animate-spin"
                style={{ borderColor: '#00A1CD', borderTopColor: 'transparent' }} />
        )}
      </div>

      {/* Dropdown results */}
      {showDropdown && (
        <div className="bg-white dark:bg-gray-900 rounded-xl shadow-xl border
                        border-gray-200 dark:border-gray-700 overflow-hidden
                        max-h-72 overflow-y-auto w-64">
          {results.length === 0 ? (
            <p className="px-3 py-2.5 text-xs text-gray-400">Geen resultaten gevonden</p>
          ) : (
            results.map(r => (
              <button
                key={r.statcode}
                onMouseDown={() => handleSelect(r)}
                className="w-full flex items-center gap-2.5 px-3 py-2 text-left
                           hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors
                           border-b border-gray-100 dark:border-gray-800 last:border-0"
              >
                <span className="text-xs font-medium text-gray-800 dark:text-gray-200 truncate">
                  {r.statnaam}
                </span>
                <span className="ml-auto shrink-0 text-[10px] text-gray-400">{r.statcode}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
