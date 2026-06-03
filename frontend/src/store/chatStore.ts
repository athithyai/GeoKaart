/** Zustand global chat + map state store. */

import { create } from 'zustand'
import { api, ApiError } from '../api/client'
import type {
  ChartDataPoint,
  ChatState,
  ChoroplethFeatureCollection,
  GeographyLevel,
  MapPlan,
  Message,
  SelectedRegion,
} from '../types'

let idCounter = 0
const uid = () => `msg-${Date.now()}-${++idCounter}`

// ── Greeting fast-path (instant response, no backend call) ────────────────────
const _GREETINGS = new Set([
  // Dutch
  'hi', 'hello', 'hoi', 'hey', 'hallo', 'dag', 'yo', 'sup', 'howdy',
  'goedemorgen', 'goedemiddag', 'goedenavond', 'good morning', 'good afternoon',
  // Casual / slang
  'wasup', 'wassup', 'heya', 'hiya', 'yo',
  // Laughs / reactions (not a real question)
  'haha', 'hahaha', 'lol', 'lmao', 'rofl', 'xd', ':)', ':d', '😂', '😄', '😊',
  // Exclamations
  'wow', 'wauw', 'whoa', 'woah', 'omg', 'wtf', 'damn', 'tof', 'gaaf',
  'interessant', 'interesting', 'echt', 'serieus',
  // Thanks / acknowledgements
  'ok', 'oke', 'oks', 'thanks', 'thx', 'bedankt', 'dankjewel', 'dank',
  'cool', 'nice', 'great', 'awesome', 'perfect', 'mooi', 'goed', 'top',
])
const _CASUAL_REPLIES = [
  'Ha! Vraag me iets over Nederlandse statistieken — bijv. "Gasverbruik per gemeente" of "Bevolkingsdichtheid in Amsterdam".',
  'Haha 😄 Kom maar op met een vraag over CBS-data. Probeer: "WOZ-waarde per gemeente in Utrecht".',
  '😄 Ik ben er klaar voor. Stel een vraag over Nederlandse regionale cijfers!',
]
const _GREETING_REPLIES = [
  'Hallo! Vraag me iets over Nederlandse regionale statistieken. Probeer: "Bevolkingsdichtheid per gemeente" of "WOZ-waarde in Amsterdam".',
  'Hey! Ik maak interactieve kaarten van CBS-kerncijfers per gemeente. Wat wil je weten?',
  'Hi! Ask me about Dutch regional stats — housing values, population, income, or demographics per municipality. Type a question or pick an example.',
  'Hoi! Ik laat CBS-statistieken op een kaart zien. Probeer: "Inkomen per gemeente" of "Vergelijk Amsterdam met omliggende gemeenten".',
]
function _isCasual(text: string): boolean {
  const clean = text.trim().toLowerCase().replace(/[!?.,\s]+$/, '')
  // Pure laugh / emoji / casual acknowledgement (up to 4 words)
  const words = clean.split(/\s+/)
  if (words.length <= 4 && words.every(w => _GREETINGS.has(w))) return true
  // Pure emoji or single punctuation
  if (/^[\p{Emoji}\s!?.:;,]+$/u.test(clean)) return true
  return false
}
function _isGreeting(text: string): boolean {
  const words = text.trim().toLowerCase().replace(/[!?.,]+$/, '').split(/\s+/)
  return words.length <= 3 && words.some(w => _GREETINGS.has(w))
}
function _randomGreetingReply(): string {
  return _GREETING_REPLIES[Math.floor(Math.random() * _GREETING_REPLIES.length)]
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  currentPlan: null,
  currentGeoJSON: null,
  selectedRegion: null,
  isLoading: false,
  isLayerLoading: false,
  flyToStatcode: null,
  error: null,

  sendMessage: async (text: string) => {
    const { messages, selectedRegion } = get()

    // Build history BEFORE adding the new user message to avoid sending it twice.
    // Include plan context in assistant messages so the LLM can handle follow-ups.
    const history = messages
      .filter(m => m.role !== 'error')
      .slice(-10)
      .map(m => ({
        role: m.role as 'user' | 'assistant',
        content:
          m.role === 'assistant' && m.plan
            ? `${m.content}\n(Map context: level=${m.plan.geography_level}, scope=${m.plan.region_scope ?? 'all Netherlands'}, measure=${m.plan.measure_code}, table=${m.plan.table_id})`
            : m.content,
      }))

    // Append selected region context to the message if one is active
    const contextualText = selectedRegion
      ? `${text}\n[Selected region: ${selectedRegion.statnaam} (${selectedRegion.statcode}${selectedRegion.gm_code ? `, parent: ${selectedRegion.gm_code}` : ''})]`
      : text

    const userMsg: Message = {
      id: uid(),
      role: 'user',
      content: text,
      timestamp: Date.now(),
    }

    // Fast-path: greeting or casual reaction → instant reply, no LLM call needed
    if (_isGreeting(text) || _isCasual(text)) {
      const replies = _isGreeting(text) ? _GREETING_REPLIES : _CASUAL_REPLIES
      const greetMsg: Message = {
        id: uid(),
        role: 'assistant',
        content: replies[Math.floor(Math.random() * replies.length)],
        timestamp: Date.now(),
      }
      set({ messages: [...messages, userMsg, greetMsg] })
      return
    }

    set({ messages: [...messages, userMsg], isLoading: true, error: null })

    try {
      const response = await api.chat({ message: contextualText, history })

      // Build chart data from top-10 regions by value (choropleth only)
      let chartData: ChartDataPoint[] | undefined
      const features = response.geojson?.features ?? []
      if (features.length > 0 && response.geojson?.meta) {
        const sorted = features
          .filter(f => f.properties.value != null)
          .sort((a, b) => (b.properties.value as number) - (a.properties.value as number))
          .slice(0, 10)
        if (sorted.length > 0) {
          chartData = sorted.map(f => ({
            name: f.properties.statnaam,
            value: f.properties.value as number,
            label: f.properties.label ?? String(f.properties.value),
            color: f.properties.color ?? '#00A1CD',
          }))
        }
      }

      const assistantMsg: Message = {
        id: uid(),
        role: 'assistant',
        content: response.message,
        plan: response.plan,
        chartData,
        warnings: response.warnings,
        suggestions: response.suggestions,
        timestamp: Date.now(),
      }

      const hasFeatures = response.geojson?.features?.length > 0

      set({
        messages: [...get().messages, assistantMsg],
        currentPlan: response.plan,
        // Only update the map if the response contains actual geometry
        ...(hasFeatures
          ? { currentGeoJSON: response.geojson as ChoroplethFeatureCollection }
          : {}),
        isLoading: false,
      })
    } catch (err) {
      const detail =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
          ? err.message
          : 'An unexpected error occurred.'

      const errMsg: Message = {
        id: uid(),
        role: 'error',
        content: detail,
        timestamp: Date.now(),
      }

      set({
        messages: [...get().messages, errMsg],
        isLoading: false,
        error: detail,
      })
    }
  },

  selectRegion: (region: SelectedRegion | null) => {
    if (region) {
      const name = region.statnaam
      // Always show gemeente-level suggestions regardless of what was clicked
      const suggestions = [
        `Wat is de bevolkingsdichtheid in ${name}?`,
        `WOZ-waarde in ${name}`,
        `Inkomen per inwoner in ${name}`,
        `Vergelijk ${name} met omliggende gemeenten`,
      ]
      const sysMsg: Message = {
        id: uid(),
        role: 'system',
        content: `📍 ${name} (${region.statcode}) selected`,
        suggestions,
        timestamp: Date.now(),
      }
      set({ selectedRegion: region, messages: [...get().messages, sysMsg] })
    } else {
      set({ selectedRegion: null })
    }
  },

  switchLayer: async (level: GeographyLevel) => {
    const { currentPlan, selectedRegion } = get()

    // Skip if already on this level
    if (currentPlan?.geography_level === level) return

    // Use isLayerLoading — keeps chat input enabled and map controls usable
    set({ isLayerLoading: true, error: null })

    try {
      // Drill-down scope logic:
      // gemeente → wijk/buurt: prefer selectedRegion, then currentPlan scope, then null (all NL)
      // wijk → buurt: same logic
      // anything → gemeente: always null (national)
      let scope: string | null = null
      if (level !== 'gemeente') {
        scope =
          (selectedRegion?.statcode?.startsWith('GM') ? selectedRegion.statcode
          : (selectedRegion?.gm_code ?? null))
          || (currentPlan?.region_scope ?? null)
      }

      const geojson = await api.boundaries(level, scope)
      const newPlan = currentPlan
        ? { ...currentPlan, geography_level: level, region_scope: scope }
        : null

      set({
        currentPlan: newPlan,
        currentGeoJSON: geojson as ChoroplethFeatureCollection,
        selectedRegion: null,
        isLayerLoading: false,
      })
    } catch (err) {
      const detail =
        err instanceof ApiError ? err.message
        : err instanceof Error ? err.message
        : 'Layer switch failed.'
      set({ isLayerLoading: false, error: detail })
    }
  },

  initBoundaries: async () => {
    // Silently load gemeente boundaries on startup so the map is immediately interactive
    try {
      const geojson = await api.boundaries('gemeente', null)
      // Only set if no chat has happened yet (don't overwrite user's map)
      if (!get().currentGeoJSON) {
        set({
          currentGeoJSON: geojson as ChoroplethFeatureCollection,
          currentPlan: {
            intent: 'map_choropleth',
            table_id: '86165NED',
            measure_code: 'AantalInwoners_5',
            geography_level: 'gemeente',
            region_scope: null,
            period: null,
            classification: 'quantile',
            n_classes: 5,
            message: '',
          } as MapPlan,
        })
      }
    } catch {
      // Silently ignore — user can still interact via chat
    }
  },

  clearError: () => set({ error: null }),

  setFlyTo: (code: string | null) => set({ flyToStatcode: code }),

  reset: () =>
    set({
      messages: [],
      currentPlan: null,
      currentGeoJSON: null,
      selectedRegion: null,
      error: null,
    }),
}))
