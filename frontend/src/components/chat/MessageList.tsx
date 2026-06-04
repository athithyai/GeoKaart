import { useEffect, useRef, useState } from 'react'
import { useChatStore } from '../../store/chatStore'
import { MessageBubble } from './MessageBubble'
import { LoadingDots } from './LoadingDots'
import { LogoIcon } from '../LogoIcon'

// ── 12 CBS data categories ─────────────────────────────────────────────────────

interface Category {
  id: string
  label: string
  labelNl: string
  icon: string
  examples: string[]
}

const CATEGORIES: Category[] = [
  {
    id: 'bevolking',
    label: 'Population',
    labelNl: 'Bevolking',
    icon: '👥',
    examples: [
      'Toon bevolkingsdichtheid per gemeente in Nederland',
      'Hoeveel ouderen (65+) per buurt in Amsterdam?',
      'Percentage jongeren per wijk in Rotterdam',
    ],
  },
  {
    id: 'wonen',
    label: 'Housing',
    labelNl: 'Wonen & vastgoed',
    icon: '🏠',
    examples: [
      'Gemiddelde WOZ-waarde per gemeente',
      'Percentage koopwoningen per wijk in Utrecht',
      'Woningvoorraad per buurt in Den Haag',
    ],
  },
  {
    id: 'energie',
    label: 'Energy',
    labelNl: 'Energie',
    icon: '⚡',
    examples: [
      'Gasverbruik per gemeente in Noord-Holland',
      'Woningen met zonnestroom per wijk in Utrecht',
      'Elektriciteitsverbruik per gemeente',
    ],
  },
  {
    id: 'onderwijs',
    label: 'Education',
    labelNl: 'Onderwijs',
    icon: '🎓',
    examples: [
      'HBO/WO-opgeleide inwoners per gemeente',
      'Leerlingen basisonderwijs per wijk in Amsterdam',
      'Hoogopgeleiden per buurt in Eindhoven',
    ],
  },
  {
    id: 'arbeid',
    label: 'Labour',
    labelNl: 'Arbeid',
    icon: '💼',
    examples: [
      'Nettoarbeidsparticipatie per gemeente',
      'Werkzame beroepsbevolking per wijk in Rotterdam',
      'Percentage zelfstandigen per gemeente',
    ],
  },
  {
    id: 'inkomen',
    label: 'Income',
    labelNl: 'Inkomen',
    icon: '💶',
    examples: [
      'Gemiddeld inkomen per inwoner per gemeente',
      'Armoede per buurt in Rotterdam',
      'Mediaan vermogen per gemeente in Nederland',
    ],
  },
  {
    id: 'sociaal',
    label: 'Social security',
    labelNl: 'Sociale zekerheid',
    icon: '🤝',
    examples: [
      'Bijstandsuitkeringen per wijk in Den Haag',
      'WW-uitkeringen per gemeente',
      'AOW-uitkeringen per buurt in Amsterdam',
    ],
  },
  {
    id: 'zorg',
    label: 'Care',
    labelNl: 'Zorg',
    icon: '🏥',
    examples: [
      'Jongeren met jeugdzorg per gemeente',
      'Wmo-cliënten per wijk in Utrecht',
      'Jeugdzorg per buurt in Rotterdam',
    ],
  },
  {
    id: 'bedrijven',
    label: 'Business',
    labelNl: 'Bedrijfsvestigingen',
    icon: '🏢',
    examples: [
      'Bedrijfsvestigingen per gemeente in Noord-Holland',
      'Aantal bedrijven per wijk in Amsterdam',
      'Bedrijvigheid per gemeente in Nederland',
    ],
  },
  {
    id: 'auto',
    label: 'Vehicles',
    labelNl: "Motorvoertuigen",
    icon: '🚗',
    examples: [
      "Personenauto's per gemeente",
      "Aantal auto's per wijk in Utrecht",
      "Motorvoertuigen per buurt in Rotterdam",
    ],
  },
  {
    id: 'nabijheid',
    label: 'Proximity',
    labelNl: 'Nabijheid',
    icon: '📍',
    examples: [
      'Afstand tot supermarkt per gemeente',
      'Afstand tot huisartsenpraktijk per wijk in Amsterdam',
      'Afstand tot school per buurt in Eindhoven',
    ],
  },
  {
    id: 'oppervlakte',
    label: 'Area',
    labelNl: 'Oppervlakte',
    icon: '🗺️',
    examples: [
      'Oppervlakte per gemeente in Nederland',
      'Omgevingsadressendichtheid per wijk in Utrecht',
      'Stedelijkheid per gemeente',
    ],
  },
]

// ── Empty state with category grid ────────────────────────────────────────────

function EmptyState({ onSend }: { onSend: (q: string) => void }) {
  const [expanded, setExpanded] = useState<string | null>(null)

  return (
    <div className="flex-1 flex flex-col items-center p-3 gap-3
                    text-center custom-scrollbar overflow-y-auto">
      {/* Welcome */}
      <div className="pt-2">
        <div className="mx-auto mb-3 w-12 h-12">
          <LogoIcon size={48} />
        </div>
        <h2 className="font-bold text-base mb-1 leading-tight tracking-tight">
          <span className="text-slate-800 dark:text-slate-100">Geo</span>
          <span style={{ color: '#00A1CD' }}>Kaart</span>
        </h2>
        <p className="text-xs text-slate-400 dark:text-slate-500 max-w-xs">
          Ask anything about any place in the Netherlands.
        </p>
        {/* Quick prompts */}
        <div className="mt-3 flex flex-col gap-1.5 text-left">
          {[
            '🗺️ Population density per municipality',
            '💶 Income within 10 min walk from Rotterdam Centraal',
            '🏠 House values by neighbourhood in Amsterdam',
          ].map((q, i) => (
            <button key={i} onClick={() => onSend(q.replace(/^.{2} /, ''))}
              className="text-xs text-left px-3 py-2 rounded-xl border
                         bg-white/60 dark:bg-slate-800/60 border-slate-200/80 dark:border-slate-700/80
                         text-slate-600 dark:text-slate-300
                         hover:bg-brand-50 dark:hover:bg-brand-900/20
                         hover:border-brand-300 hover:text-brand-700
                         dark:hover:border-brand-600 dark:hover:text-brand-300
                         transition-all">
              {q}
            </button>
          ))}
        </div>
      </div>

      {/* 12 Category cards */}
      <div className="w-full">
        <p className="text-[10px] font-bold uppercase tracking-widest mb-2 text-left
                      text-slate-400 dark:text-slate-500">
          Browse by category
        </p>
        <div className="grid grid-cols-3 gap-1.5">
          {CATEGORIES.map(cat => (
            <div key={cat.id}>
              <button
                onClick={() => setExpanded(expanded === cat.id ? null : cat.id)}
                className={`w-full flex flex-col items-center gap-1 px-2 py-2.5 rounded-xl text-center
                            border transition-all duration-150 text-xs
                            ${expanded === cat.id
                              ? 'bg-brand-400/10 dark:bg-brand-400/15 border-brand-400/40 dark:border-brand-400/30 text-brand-700 dark:text-brand-300'
                              : 'bg-white/60 dark:bg-slate-800/60 border-slate-200/80 dark:border-slate-700/80 text-slate-600 dark:text-slate-300 hover:bg-brand-50 dark:hover:bg-brand-900/20 hover:border-brand-300/60 dark:hover:border-brand-600/40'
                            }`}
              >
                <span className="text-sm leading-none">{cat.icon}</span>
                <span className="font-medium leading-tight text-[11px]">{cat.labelNl}</span>
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Expanded examples */}
      {expanded && (() => {
        const cat = CATEGORIES.find(c => c.id === expanded)!
        return (
          <div className="w-full space-y-1.5 animate-[slideUp_0.15s_ease-out]">
            <p className="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-widest text-left">
              {cat.icon} {cat.labelNl}
            </p>
            {cat.examples.map(q => (
              <button key={q} onClick={() => onSend(q)}
                className="w-full text-left text-xs px-3.5 py-2.5 rounded-xl
                           bg-white/70 dark:bg-slate-800/60
                           hover:bg-brand-50 dark:hover:bg-brand-900/20
                           text-slate-600 dark:text-slate-300 hover:text-brand-700
                           dark:hover:text-brand-300 border border-slate-200/80 dark:border-slate-700/80
                           hover:border-brand-300/60 dark:hover:border-brand-600/40
                           transition-all duration-150">
                {q}
              </button>
            ))}
          </div>
        )
      })()}
    </div>
  )
}

// ── Main message list ──────────────────────────────────────────────────────────

export function MessageList() {
  const messages   = useChatStore(s => s.messages)
  const isLoading  = useChatStore(s => s.isLoading)
  const sendMessage = useChatStore(s => s.sendMessage)
  const bottomRef  = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  if (messages.length === 0) {
    return <EmptyState onSend={sendMessage} />
  }

  return (
    <div className="flex-1 overflow-y-auto custom-scrollbar p-3 space-y-3 min-h-0">
      {messages.map((msg, index) => {
        let onRetry: (() => void) | undefined
        if (msg.role === 'error') {
          const prevUser = [...messages].slice(0, index).reverse().find(m => m.role === 'user')
          if (prevUser) onRetry = () => sendMessage(prevUser.content)
        }
        return <MessageBubble key={msg.id} message={msg} onRetry={onRetry} />
      })}

      {/* Loading bubble */}
      {isLoading && (
        <div className="flex gap-2.5">
          <div className="w-7 h-7 shrink-0"><LogoIcon size={28} /></div>
          <div className="px-3.5 py-2.5 rounded-2xl rounded-tl-sm
                          bg-white dark:bg-slate-800 border border-black/5 dark:border-white/5 shadow-sm">
            <LoadingDots />
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}
