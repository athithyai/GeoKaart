import { useCallback, useEffect, useRef, useState } from 'react'
import { ChatPanel } from '../chat/ChatPanel'
import { MapPanel } from '../map/MapPanel'
import { DataTable } from '../map/DataTable'
import { ThemeToggle } from './ThemeToggle'
import { LogoWordmark } from '../LogoIcon'
import { api } from '../../api/client'

type IngestStatus = 'idle' | 'running' | 'done' | 'error'

function _fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
  } catch { return iso.slice(0, 10) }
}

export function AppShell() {
  const [chatOpen,    setChatOpen]    = useState(true)
  const [ingestStatus, setIngestStatus] = useState<IngestStatus>('idle')
  const [ingestLastRun, setIngestLastRun] = useState<string | null>(null)
  const [ingestProgress, setIngestProgress] = useState('')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    api.adminStatus().then(s => {
      setIngestLastRun(s.db_log?.finished_at ?? s.finished_at ?? null)
      setIngestStatus(s.status as IngestStatus)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (ingestStatus !== 'running') return
    pollRef.current = setInterval(async () => {
      try {
        const s = await api.adminStatus()
        setIngestProgress(s.progress ?? '')
        if (s.status !== 'running') {
          setIngestStatus(s.status as IngestStatus)
          setIngestLastRun(s.db_log?.finished_at ?? s.finished_at ?? null)
          if (pollRef.current) clearInterval(pollRef.current)
        }
      } catch {}
    }, 3000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [ingestStatus])

  const handleRefresh = useCallback(async () => {
    if (ingestStatus === 'running') return
    try { await api.adminIngest(); setIngestStatus('running'); setIngestProgress('Starting…') }
    catch {}
  }, [ingestStatus])

  return (
    <div className="relative w-screen h-screen overflow-hidden bg-slate-900">

      {/* ── Full-screen map ─────────────────────────────────────────────────── */}
      <div className="absolute inset-0">
        <MapPanel />
      </div>

      {/* ── Topbar ──────────────────────────────────────────────────────────── */}
      <header className="absolute top-0 left-0 right-0 z-20 flex items-center justify-between
                         px-4 h-11 glass shadow-sm">
        <div className="flex items-center gap-3">
          {/* Chat toggle button */}
          <button
            onClick={() => setChatOpen(v => !v)}
            className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg
                       text-slate-600 dark:text-slate-300 hover:bg-black/5 dark:hover:bg-white/10
                       transition-colors"
            title={chatOpen ? 'Hide chat' : 'Open chat'}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              {chatOpen
                ? <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
                : <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              }
            </svg>
          </button>

          <div className="h-4 w-px bg-slate-200 dark:bg-slate-700" />
          <LogoWordmark iconSize={22} />
        </div>

        <div className="flex items-center gap-2">
          {/* Source badges */}
          <div className="hidden sm:flex items-center gap-1">
            {['CBS', 'PDOK', 'ORS'].map(s => (
              <span key={s} className="source-badge">{s}</span>
            ))}
          </div>

          {/* Data refresh */}
          <button
            onClick={handleRefresh}
            disabled={ingestStatus === 'running'}
            title={ingestStatus === 'running'
              ? `Refreshing… ${ingestProgress}`
              : `Refresh data${ingestLastRun ? ` · ${_fmtDate(ingestLastRun)}` : ''}`}
            className={[
              'flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-medium transition-all',
              ingestStatus === 'running'
                ? 'text-amber-500 dark:text-amber-400 cursor-wait'
                : 'text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-black/5 dark:hover:bg-white/10',
            ].join(' ')}
          >
            <span className={ingestStatus === 'running' ? 'animate-spin inline-block' : ''}>↻</span>
          </button>

          <ThemeToggle />
        </div>
      </header>

      {/* ── Floating chat panel ──────────────────────────────────────────────── */}
      <div
        className={[
          'absolute top-14 left-4 bottom-4 z-10',
          'w-[380px] flex flex-col',
          'glass rounded-2xl shadow-2xl shadow-black/20',
          'transition-all duration-300 ease-in-out',
          chatOpen ? 'opacity-100 translate-x-0' : 'opacity-0 -translate-x-8 pointer-events-none',
        ].join(' ')}
      >
        <ChatPanel />
      </div>

      {/* ── Chat open FAB (when chat is hidden) ───────────────────────────────── */}
      {!chatOpen && (
        <button
          onClick={() => setChatOpen(true)}
          className="absolute top-14 left-4 z-10 w-12 h-12 rounded-2xl
                     glass shadow-xl shadow-black/20 flex items-center justify-center
                     text-brand-500 hover:text-brand-600 transition-colors
                     animate-[fadeIn_0.2s_ease-out]"
          title="Open chat"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
          </svg>
        </button>
      )}

      {/* ── Data table — floating bottom strip ───────────────────────────────── */}
      <div className="absolute bottom-0 left-0 right-0 z-10">
        <DataTable />
      </div>
    </div>
  )
}
