import { MessageList } from './MessageList'
import { InputBar } from './InputBar'
import { useChatStore } from '../../store/chatStore'

export function ChatPanel() {
  const { messages, reset } = useChatStore()

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Panel header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b
                      border-gray-100 dark:border-gray-800 shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase tracking-wider">
            Chat
          </span>
          {messages.length > 0 && (
            <span className="text-xs bg-brand-100 dark:bg-brand-900 text-brand-700
                             dark:text-brand-300 px-1.5 py-0.5 rounded-full font-medium">
              {messages.length}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* Reset button */}
          {messages.length > 0 && (
            <button
              onClick={reset}
              className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200
                         transition-colors px-2 py-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800"
              title="Clear conversation"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Messages */}
      <MessageList />

      {/* Input */}
      <InputBar />
    </div>
  )
}
