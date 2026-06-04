import { MessageList } from './MessageList'
import { InputBar }   from './InputBar'
import { useChatStore } from '../../store/chatStore'

export function ChatPanel() {
  const { messages, isLoading, reset } = useChatStore()

  return (
    <div className="flex flex-col h-full min-h-0 rounded-2xl overflow-hidden">

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-4 py-3 shrink-0
                      border-b border-black/5 dark:border-white/5">
        <div className="flex items-center gap-2.5">
          {/* Animated status dot */}
          <div className={[
            'w-2 h-2 rounded-full shrink-0',
            isLoading
              ? 'bg-amber-400 animate-pulse'
              : 'bg-emerald-400',
          ].join(' ')} />
          <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 tracking-wide">
            {isLoading ? 'Thinking…' : 'GeoKaart AI'}
          </span>
          {messages.length > 0 && (
            <span className="text-[10px] bg-brand-400/15 text-brand-600 dark:text-brand-300
                             px-1.5 py-0.5 rounded-full font-semibold">
              {messages.filter(m => m.role !== 'system').length}
            </span>
          )}
        </div>

        {messages.length > 0 && (
          <button
            onClick={reset}
            className="text-[11px] text-slate-400 hover:text-slate-600 dark:hover:text-slate-200
                       transition-colors px-2 py-1 rounded-lg hover:bg-black/5 dark:hover:bg-white/10
                       font-medium"
          >
            Clear
          </button>
        )}
      </div>

      {/* ── Messages ───────────────────────────────────────────────────── */}
      <MessageList />

      {/* ── Input ──────────────────────────────────────────────────────── */}
      <InputBar />
    </div>
  )
}
