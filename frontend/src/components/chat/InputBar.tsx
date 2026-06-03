import { useRef, useState, KeyboardEvent } from 'react'
import { useChatStore } from '../../store/chatStore'

export function InputBar() {
  const [value, setValue] = useState('')
  const sendMessage = useChatStore(s => s.sendMessage)
  const isLoading = useChatStore(s => s.isLoading)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const canSend = value.trim().length > 0 && !isLoading

  const handleSend = async () => {
    if (!canSend) return
    const text = value.trim()
    setValue('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
    await sendMessage(text)
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleInput = () => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }

  return (
    <div className="p-3 border-t border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
      <div className="flex items-end gap-2 bg-gray-50 dark:bg-gray-800 rounded-xl
                      border border-gray-200 dark:border-gray-700 focus-within:border-brand-400
                      dark:focus-within:border-brand-500 focus-within:ring-2
                      focus-within:ring-brand-400/20 transition-all px-3 py-2">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onInput={handleInput}
          placeholder="Ask about Dutch regional statistics…"
          rows={1}
          disabled={isLoading}
          className="flex-1 resize-none bg-transparent text-sm text-gray-900 dark:text-gray-100
                     placeholder-gray-400 dark:placeholder-gray-500 outline-none
                     leading-relaxed max-h-40 disabled:opacity-50"
        />
        <button
          onClick={handleSend}
          disabled={!canSend}
          className="shrink-0 w-8 h-8 rounded-lg flex items-center justify-center
                     bg-brand-600 hover:bg-brand-700 disabled:bg-gray-300 dark:disabled:bg-gray-700
                     text-white disabled:text-gray-400 dark:disabled:text-gray-500
                     transition-colors mb-0.5"
          aria-label="Send"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
          </svg>
        </button>
      </div>
      <p className="text-[10px] text-gray-400 dark:text-gray-600 mt-1.5 px-1">
        Enter to send · Shift+Enter for new line
      </p>
    </div>
  )
}
