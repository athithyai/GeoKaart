/** Shared TypeScript types for GeoKaart frontend. */

// ── Plan ─────────────────────────────────────────────────────────────────────

export type GeographyLevel = 'gemeente' | 'wijk' | 'buurt'
export type Classification  = 'quantile' | 'jenks' | 'equal'
export type Intent          = 'map_choropleth' | 'zoom' | 'compare' | 'info' | 'explain'

export interface MapPlan {
  intent: Intent
  table_id: string
  measure_code: string
  geography_level: GeographyLevel
  region_scope: string | null
  province_scope?: string | null
  period: string | null
  classification: Classification
  n_classes: number
  message: string
}

// ── GeoJSON meta ──────────────────────────────────────────────────────────────

export interface ChoroplethMeta {
  measure_code: string
  period: string
  breaks: number[]
  colors: string[]
  null_color: string
  n_matched: number
  n_total: number
  warnings: string[]
}

export interface ChoroplethFeatureProperties {
  statcode: string
  statnaam: string
  value: number | null
  label: string
  color: string
}

export interface ChoroplethFeatureCollection extends GeoJSON.FeatureCollection {
  meta?: ChoroplethMeta
  features: Array<GeoJSON.Feature<GeoJSON.Geometry, ChoroplethFeatureProperties>>
}

// ── API payloads ──────────────────────────────────────────────────────────────

export interface ChatRequest {
  message: string
  history: Array<{ role: 'user' | 'assistant'; content: string }>
  lang?: 'en' | 'nl'
}

export interface ChatResponse {
  message: string
  plan: MapPlan
  geojson: ChoroplethFeatureCollection
  warnings: string[]
  suggestions: string[]
}

// ── Chat store ────────────────────────────────────────────────────────────────

export type MessageRole = 'user' | 'assistant' | 'error' | 'system'

export interface ChartDataPoint {
  name: string
  value: number
  label: string
  color: string
}

export interface Message {
  id: string
  role: MessageRole
  content: string
  plan?: MapPlan
  chartData?: ChartDataPoint[]
  warnings?: string[]
  suggestions?: string[]
  timestamp: number
}

export interface SelectedRegion {
  statcode: string
  statnaam: string
  gm_code?: string
}

export interface SearchResult {
  statnaam: string
  statcode: string
  gm_code: string
  level: 'gemeente' | 'wijk' | 'buurt'
}

export interface ChatState {
  messages: Message[]
  currentPlan: MapPlan | null
  currentGeoJSON: ChoroplethFeatureCollection | null
  selectedRegion: SelectedRegion | null
  isLoading: boolean       // chat request in flight
  isLayerLoading: boolean  // layer switch in flight (map stays interactive during chat)
  flyToStatcode: string | null
  setFlyTo: (code: string | null) => void
  error: string | null
  sendMessage: (text: string) => Promise<void>
  selectRegion: (region: SelectedRegion | null) => void
  switchLayer: (level: GeographyLevel) => Promise<void>
  initBoundaries: () => Promise<void>
  clearError: () => void
  reset: () => void
}

// ── Catalog ───────────────────────────────────────────────────────────────────

export interface CatalogEntry {
  id: string
  title: string
  period: string
  geo_levels: GeographyLevel[]
}
