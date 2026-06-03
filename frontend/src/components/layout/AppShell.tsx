import { useCallback, useEffect, useRef, useState } from 'react'
import { ChatPanel } from '../chat/ChatPanel'
import { MapPanel } from '../map/MapPanel'
import { DataTable } from '../map/DataTable'
import { ThemeToggle } from './ThemeToggle'
import { LogoWordmark } from '../LogoIcon'
import { api } from '../../api/client'

const MIN_CHAT_WIDTH = 300
const MAX_CHAT_WIDTH = 640
const DEFAULT_CHAT_WIDTH = 400

// ── Ingest status helpers ─────────────────────────────────────────────────────

type IngestStatus = 'idle' | 'running' | 'done' | 'error'

function _fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
    return d.toLocaleDateString('nl-NL', { day: 'numeric', month: 'short', year: 'numeric' })
  } catch {
    return iso.slice(0, 10)
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AppShell() {
  const [chatWidth, setChatWidth] = useState(DEFAULT_CHAT_WIDTH)
  const [dragging, setDragging] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  // Ingest / refresh state
  const [ingestStatus, setIngestStatus] = useState<IngestStatus>('idle')
  const [ingestLastRun, setIngestLastRun] = useState<string | null>(null)
  const [ingestProgress, setIngestProgress] = useState<string>('')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Fetch initial status on mount
  useEffect(() => {
    api.adminStatus().then(s => {
      const lastRun = s.db_log?.finished_at ?? s.finished_at
      setIngestLastRun(lastRun ?? null)
      setIngestStatus(s.status as IngestStatus)
    }).catch(() => {/* silently ignore */})
  }, [])

  // Poll while running
  useEffect(() => {
    if (ingestStatus === 'running') {
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.adminStatus()
          setIngestProgress(s.progress ?? '')
          if (s.status !== 'running') {
            setIngestStatus(s.status as IngestStatus)
            const lastRun = s.db_log?.finished_at ?? s.finished_at
            setIngestLastRun(lastRun ?? null)
            if (pollRef.current) clearInterval(pollRef.current)
          }
        } catch { /* ignore */ }
      }, 3000)
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [ingestStatus])

  const handleRefresh = useCallback(async () => {
    if (ingestStatus === 'running') return
    try {
      await api.adminIngest()
      setIngestStatus('running')
      setIngestProgress('Starting …')
    } catch { /* ignore */ }
  }, [ingestStatus])

  const startDrag = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setDragging(true)

    const startX = e.clientX
    const startW = chatWidth

    const onMove = (ev: MouseEvent) => {
      const delta = ev.clientX - startX
      const next = Math.max(MIN_CHAT_WIDTH, Math.min(MAX_CHAT_WIDTH, startW + delta))
      setChatWidth(next)
    }

    const onUp = () => {
      setDragging(false)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [chatWidth])

  return (
    <div className="h-screen w-screen flex flex-col bg-gray-50 dark:bg-gray-950 overflow-hidden">
      {/* Header */}
      <header className="flex items-center justify-between px-4 h-12 bg-white dark:bg-gray-900
                         border-b border-cbs-border dark:border-gray-800 shrink-0 z-10 shadow-sm">
        <div className="flex items-center gap-3">
          <LogoWordmark iconSize={28} />
          <span className="text-xs hidden sm:block" style={{ color: '#878787' }}>
            Dutch Regional Statistics
          </span>
        </div>
        <div className="flex items-center gap-2">
          {/* Spatial data refresh — small hidden chip, visible on hover */}
          <div className="group relative hidden sm:flex items-center">
            <button
              onClick={handleRefresh}
              disabled={ingestStatus === 'running'}
              title={
                ingestStatus === 'running'
                  ? `Vernieuwen: ${ingestProgress}`
                  : `Ruimtelijke data vernieuwen${ingestLastRun ? ` · bijgewerkt ${_fmtDate(ingestLastRun)}` : ''}`
              }
              className={[
                'flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium',
                'border transition-all duration-200',
                ingestStatus === 'running'
                  ? 'border-amber-300 text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950 cursor-wait'
                  : ingestStatus === 'error'
                  ? 'border-red-300 text-red-500 hover:bg-red-50 dark:hover:bg-red-950'
                  : 'border-gray-200 dark:border-gray-700 text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-500',
              ].join(' ')}
            >
              <span
                className={ingestStatus === 'running' ? 'animate-spin inline-block' : ''}
                style={{ display: 'inline-block' }}
              >↻</span>
              <span className="opacity-0 group-hover:opacity-100 transition-opacity duration-150 max-w-0 group-hover:max-w-[160px] overflow-hidden whitespace-nowrap">
                {ingestStatus === 'running'
                  ? (ingestProgress || 'Vernieuwen …')
                  : ingestLastRun
                  ? `bijgewerkt ${_fmtDate(ingestLastRun)}`
                  : 'data vernieuwen'}
              </span>
            </button>
          </div>

          <span className="text-xs mr-1 hidden sm:block" style={{ color: '#878787' }}>
            CBS StatLine × PDOK
          </span>
          <ThemeToggle />
        </div>
      </header>

      {/* Main content */}
      <div ref={containerRef} className="flex flex-1 min-h-0 overflow-hidden">
        {/* Chat panel */}
        <div
          style={{ width: chatWidth }}
          className="flex flex-col shrink-0 min-h-0 bg-white dark:bg-gray-900
                     border-r border-gray-200 dark:border-gray-800"
        >
          <ChatPanel />
        </div>

        {/* Resize handle */}
        <div
          onMouseDown={startDrag}
          className={`resize-handle w-1 shrink-0 bg-gray-200 dark:bg-gray-800
                      ${dragging ? 'dragging' : ''}`}
        />

        {/* Map panel */}
        <div className="flex-1 min-w-0 relative">
          <MapPanel />
        </div>
      </div>

      {/* Data table — full-width bottom strip, spans chat + map */}
      <DataTable />
    </div>
  )
}
