import clsx from 'clsx'
import { PlanCard }    from './PlanCard'
import { MiniBarChart } from './MiniBarChart'
import type { Message }  from '../../types'
import { LoadingDots }  from './LoadingDots'
import { useChatStore } from '../../store/chatStore'
import { LogoIcon }     from '../LogoIcon'

interface Props {
  message: Message
  isStreaming?: boolean
  onRetry?: () => void
}

function renderMarkdown(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^- (.+)$/gm, '<li class="ml-3 list-disc">$1</li>')
    .replace(/\n(?!<li)/g, '<br />')
}

function formatTime(ts: number) {
  return new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit' }).format(new Date(ts))
}

export function MessageBubble({ message, isStreaming, onRetry }: Props) {
  const sendMessage = useChatStore(s => s.sendMessage)
  const isUser   = message.role === 'user'
  const isError  = message.role === 'error'
  const isSystem = message.role === 'system'

  // ── System notification ──────────────────────────────────────────────────
  if (isSystem) {
    return (
      <div className="flex flex-col items-center gap-2 my-1 animate-[slideUp_0.2s_ease-out]">
        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs
                        bg-amber-50 dark:bg-amber-950/50 border border-amber-200/60
                        dark:border-amber-800/40 text-amber-700 dark:text-amber-300">
          {message.content}
        </div>
        {message.suggestions && message.suggestions.length > 0 && (
          <div className="flex flex-wrap gap-1.5 justify-center max-w-xs">
            {message.suggestions.map((s, i) => (
              <button key={i} onClick={() => sendMessage(s)}
                className="text-[11px] px-2.5 py-1 rounded-full border
                           bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700
                           text-slate-600 dark:text-slate-300
                           hover:bg-brand-50 dark:hover:bg-brand-900/20
                           hover:border-brand-300 hover:text-brand-700
                           dark:hover:border-brand-600 dark:hover:text-brand-300
                           transition-all text-left">
                {s}
              </button>
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className={clsx(
      'flex gap-2.5 animate-[slideUp_0.2s_ease-out] message-enter',
      isUser ? 'flex-row-reverse' : 'flex-row'
    )}>
      {/* Avatar */}
      {isUser ? (
        <div className="w-7 h-7 rounded-full shrink-0 flex items-center justify-center
                        text-xs font-bold bg-slate-700 dark:bg-slate-600 text-white">
          U
        </div>
      ) : isError ? (
        <div className="w-7 h-7 rounded-full shrink-0 flex items-center justify-center
                        text-xs font-bold bg-red-500 text-white">!
        </div>
      ) : (
        <div className="w-7 h-7 shrink-0">
          <LogoIcon size={28} />
        </div>
      )}

      {/* Bubble */}
      <div className={clsx('flex flex-col max-w-[85%]', isUser ? 'items-end' : 'items-start')}>
        <div className={clsx(
          'px-3.5 py-2.5 rounded-2xl text-sm leading-relaxed',
          isUser
            ? 'bg-brand-400 text-white rounded-tr-sm shadow-sm shadow-brand-400/20'
            : isError
            ? 'bg-red-50 dark:bg-red-950/50 text-red-700 dark:text-red-300 border border-red-200/60 dark:border-red-800/40 rounded-tl-sm'
            : 'bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-100 rounded-tl-sm shadow-sm border border-black/5 dark:border-white/5'
        )}>
          {isStreaming ? (
            <LoadingDots />
          ) : isError ? (
            <div className="space-y-2">
              <p className="whitespace-pre-wrap">{message.content}</p>
              {onRetry && (
                <button onClick={onRetry}
                  className="text-xs font-medium px-2.5 py-1 rounded-lg
                             bg-red-100 dark:bg-red-900/50 hover:bg-red-200 dark:hover:bg-red-800/50
                             text-red-700 dark:text-red-300 border border-red-200 dark:border-red-700/50
                             transition-colors">
                  ↺ Try again
                </button>
              )}
            </div>
          ) : isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="text-sm leading-relaxed"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }} />
          )}
        </div>

        {/* Mini bar chart */}
        {!isStreaming && message.chartData && message.chartData.length > 0 && (
          <div className="w-full mt-1.5">
            <MiniBarChart data={message.chartData} measureCode={message.plan?.measure_code ?? ''} />
          </div>
        )}

        {/* Ring summary table */}
        {!isStreaming && message.ring_summary && message.ring_summary.length > 0 && (
          <div className="w-full mt-2 rounded-xl overflow-hidden border border-black/8 dark:border-white/8
                          shadow-sm animate-[fadeIn_0.3s_ease-out]">
            <div className="px-3 py-1.5 bg-slate-50 dark:bg-slate-800/60 border-b border-black/5 dark:border-white/5">
              <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
                Reachability bands
              </span>
            </div>
            <table className="w-full text-xs bg-white dark:bg-slate-800/40">
              <thead>
                <tr className="border-b border-black/5 dark:border-white/5">
                  <th className="px-3 py-1.5 text-left text-slate-400 font-semibold">Ring</th>
                  <th className="px-3 py-1.5 text-right text-slate-400 font-semibold">Avg</th>
                  <th className="px-3 py-1.5 text-right text-slate-400 font-semibold">Max</th>
                  <th className="px-3 py-1.5 text-right text-slate-400 font-semibold">N</th>
                </tr>
              </thead>
              <tbody>
                {message.ring_summary.map((r, i) => (
                  <tr key={i} className={i % 2 === 0 ? '' : 'bg-slate-50/50 dark:bg-slate-700/20'}>
                    <td className="px-3 py-1.5 text-slate-700 dark:text-slate-300 font-medium">
                      <span className="flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-full"
                          style={{ backgroundColor: '#00A1CD', opacity: 0.3 + i * 0.25 }} />
                        {r.minutes} min
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-slate-600 dark:text-slate-300">
                      {r.avg_value != null ? r.avg_value.toLocaleString() : '—'}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-slate-600 dark:text-slate-300">
                      {r.max_value != null ? r.max_value.toLocaleString() : '—'}
                    </td>
                    <td className="px-3 py-1.5 text-right text-slate-400">{r.n_regions}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Plan card */}
        {!isStreaming && message.plan && (
          <div className="w-full mt-1.5">
            <PlanCard plan={message.plan} />
          </div>
        )}

        {/* Warnings */}
        {message.warnings && message.warnings.length > 0 && (
          <div className="mt-1 space-y-1">
            {message.warnings.map((w, i) => (
              <p key={i} className="text-[11px] text-amber-600 dark:text-amber-400 flex items-start gap-1">
                <span>⚠</span><span>{w}</span>
              </p>
            ))}
          </div>
        )}

        {/* Suggestions */}
        {!isStreaming && message.suggestions && message.suggestions.length > 0 && (
          <div className="mt-2 w-full">
            <p className="text-[9px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-widest mb-1.5">
              Try also
            </p>
            <div className="flex flex-wrap gap-1.5">
              {message.suggestions.map((s, i) => (
                <button key={i} onClick={() => sendMessage(s)}
                  className="text-[11px] px-2.5 py-1 rounded-full border
                             bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700
                             text-slate-600 dark:text-slate-300
                             hover:bg-brand-50 dark:hover:bg-brand-900/20
                             hover:border-brand-300 hover:text-brand-700
                             dark:hover:border-brand-600 dark:hover:text-brand-300
                             transition-all">
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        <span className="text-[9px] text-slate-300 dark:text-slate-600 mt-1 px-0.5">
          {formatTime(message.timestamp)}
        </span>
      </div>
    </div>
  )
}
