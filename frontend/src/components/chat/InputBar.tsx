import { useRef, useState, KeyboardEvent } from 'react'
import { useChatStore } from '../../store/chatStore'

export function InputBar() {
  const [value, setValue] = useState('')
  const sendMessage = useChatStore(s => s.sendMessage)
  const isLoading   = useChatStore(s => s.isLoading)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const canSend = value.trim().length > 0 && !isLoading

  const handleSend = async () => {
    if (!canSend) return
    const text = value.trim()
    setValue('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    await sendMessage(text)
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  const handleInput = () => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`
  }

  return (
    <div className="px-3 pb-3 pt-2 shrink-0 border-t border-black/5 dark:border-white/5">
      <div className={[
        'flex items-end gap-2 rounded-xl border transition-all px-3 py-2',
        'bg-slate-50 dark:bg-slate-800/60',
        canSend || value.length > 0
          ? 'border-brand-400/50 ring-2 ring-brand-400/10'
          : 'border-slate-200 dark:border-slate-700',
      ].join(' ')}>
        <textarea
          ref={textareaRef}
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onInput={handleInput}
          placeholder="Ask about any place in the Netherlands…"
          rows={1}
          disabled={isLoading}
          className="flex-1 resize-none bg-transparent text-sm text-slate-800 dark:text-slate-100
                     placeholder-slate-400 dark:placeholder-slate-500 outline-none
                     leading-relaxed max-h-36 disabled:opacity-50 font-sans"
        />
        <button
          onClick={handleSend}
          disabled={!canSend}
          className={[
            'shrink-0 w-7 h-7 rounded-lg flex items-center justify-center mb-0.5',
            'transition-all duration-150',
            canSend
              ? 'bg-brand-400 hover:bg-brand-500 text-white shadow-sm shadow-brand-400/30'
              : 'bg-slate-200 dark:bg-slate-700 text-slate-400 dark:text-slate-500',
          ].join(' ')}
          aria-label="Send"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
              d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
          </svg>
        </button>
      </div>
      <p className="text-[9px] text-slate-400 dark:text-slate-600 mt-1.5 px-1 text-center">
        Enter to send · Shift+Enter for new line
      </p>
    </div>
  )
}
