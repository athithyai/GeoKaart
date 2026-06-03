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
    <div className="flex-1 flex flex-col items-center p-4 gap-4
                    text-center custom-scrollbar overflow-y-auto">
      {/* Welcome */}
      <div className="pt-2">
        <div className="mx-auto mb-3 w-12 h-12">
          <LogoIcon size={48} />
        </div>
        <h2 className="font-display font-medium text-base mb-1 leading-tight">
          <span style={{ color: '#271D6C' }}>Cijfers</span><span style={{ color: '#00A1CD' }}>Chat</span>
        </h2>
        <p className="text-xs max-w-xs" style={{ color: '#878787' }}>
          Kies een categorie om CBS-data op de kaart te verkennen.
        </p>
      </div>

      {/* 12 Category cards */}
      <div className="w-full">
        <p className="font-display text-xs font-medium uppercase tracking-wider mb-2 text-left" style={{ color: '#878787' }}>
          Categorieën
        </p>
        <div className="grid grid-cols-3 gap-1.5">
          {CATEGORIES.map(cat => (
            <div key={cat.id}>
              <button
                onClick={() => setExpanded(expanded === cat.id ? null : cat.id)}
                className={`w-full flex flex-col items-center gap-1 px-2 py-2.5 rounded-xl text-center
                            border transition-all duration-150 text-xs
                            ${expanded === cat.id
                              ? 'bg-brand-50 dark:bg-brand-900/30 border-brand-300 dark:border-brand-600 text-brand-700 dark:text-brand-300'
                              : 'bg-gray-50 dark:bg-gray-800 border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 hover:bg-brand-50 dark:hover:bg-gray-700 hover:border-brand-200 dark:hover:border-gray-600'
                            }`}
              >
                <span className="text-base leading-none">{cat.icon}</span>
                <span className="font-medium leading-tight">{cat.labelNl}</span>
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
            <p className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider text-left">
              {cat.icon} {cat.labelNl} — voorbeeldvragen
            </p>
            {cat.examples.map(q => (
              <button
                key={q}
                onClick={() => onSend(q)}
                className="w-full text-left text-sm px-3.5 py-2.5 rounded-xl
                           bg-gray-50 dark:bg-gray-800 hover:bg-brand-50 dark:hover:bg-gray-700
                           text-gray-700 dark:text-gray-300 hover:text-brand-700
                           dark:hover:text-brand-300 border border-gray-200 dark:border-gray-700
                           hover:border-brand-300 dark:hover:border-brand-600
                           transition-all duration-150"
              >
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
    <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-4 min-h-0">
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
        <div className="flex gap-3">
          <div className="w-7 h-7 shrink-0">
            <LogoIcon size={28} />
          </div>
          <div className="px-3.5 py-2.5 rounded-2xl rounded-tl-sm
                          bg-gray-100 dark:bg-gray-800">
            <LoadingDots />
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}
