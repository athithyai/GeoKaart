import { useEffect, useRef, useState, useCallback } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useChatStore } from '../../store/chatStore'
import { MapLegend } from './MapLegend'
import { MapTooltip } from './MapTooltip'
import { MapControls } from './MapControls'
import { MapSearch } from './MapSearch'
import type { ChoroplethFeatureProperties, ChoroplethMeta } from '../../types'

const NL_CENTER: [number, number] = [5.2913, 52.1326]
const NL_ZOOM = 7
const SOURCE_ID = 'choropleth-source'
const FILL_LAYER = 'choropleth-fill'
const OUTLINE_LAYER = 'choropleth-outline'
const SELECTED_LAYER = 'choropleth-selected'
const BASE_STYLE = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json'

interface TooltipState {
  x: number
  y: number
  props: ChoroplethFeatureProperties
}

export function MapPanel() {
  const mapContainer    = useRef<HTMLDivElement>(null)
  const mapRef          = useRef<maplibregl.Map | null>(null)
  const hoveredId       = useRef<string | number | null>(null)
  const selectedId      = useRef<string | number | null>(null)
  const isBoundaryOnly  = useRef(false)

  const [tooltip,  setTooltip]  = useState<TooltipState | null>(null)
  const [meta,     setMeta]     = useState<ChoroplethMeta | null>(null)
  const [measureCode, setMeasureCode] = useState('')
  const [mapReady, setMapReady] = useState(false)

  const currentGeoJSON  = useChatStore(s => s.currentGeoJSON)
  const currentPlan     = useChatStore(s => s.currentPlan)
  const isLoading       = useChatStore(s => s.isLoading)
  const selectedRegion  = useChatStore(s => s.selectedRegion)
  const selectRegion    = useChatStore(s => s.selectRegion)
  const flyToStatcode   = useChatStore(s => s.flyToStatcode)
  const setFlyTo        = useChatStore(s => s.setFlyTo)

  // ── Init map ────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return

    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: BASE_STYLE,
      center: NL_CENTER,
      zoom: NL_ZOOM,
      attributionControl: { compact: true },
    })

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')
    map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left')

    map.on('load', () => setMapReady(true))
    mapRef.current = map

    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  // ── Update choropleth when GeoJSON changes ──────────────────────────────────
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady || !currentGeoJSON) return

    // Clear any selected state when data changes
    selectedId.current = null

    const geojson  = currentGeoJSON
    const fc_meta  = geojson.meta

    // Remove old layers/source
    ;[SELECTED_LAYER, OUTLINE_LAYER, FILL_LAYER].forEach(id => {
      if (map.getLayer(id)) map.removeLayer(id)
    })
    if (map.getSource(SOURCE_ID)) map.removeSource(SOURCE_ID)

    if (!geojson.features.length) return

    // Add source with generateId so feature-state works
    map.addSource(SOURCE_ID, {
      type: 'geojson',
      data: geojson as GeoJSON.FeatureCollection,
      generateId: true,
    })

    // Boundary-only mode (no CBS data) vs choropleth mode
    const _isBoundaryOnly = !fc_meta
    isBoundaryOnly.current = _isBoundaryOnly

    // Fill layer
    map.addLayer({
      id: FILL_LAYER,
      type: 'fill',
      source: SOURCE_ID,
      paint: {
        'fill-color': _isBoundaryOnly
          ? ['case',
              ['boolean', ['feature-state', 'selected'], false], '#dbeafe',
              ['boolean', ['feature-state', 'hover'],    false], '#e5e7eb',
              'transparent']
          : ['coalesce', ['get', 'color'], '#cccccc'],
        'fill-opacity': _isBoundaryOnly
          ? ['case',
              ['boolean', ['feature-state', 'selected'], false], 0.6,
              ['boolean', ['feature-state', 'hover'],    false], 0.4,
              0.0]
          : ['case',
              ['boolean', ['feature-state', 'selected'], false], 0.95,
              ['boolean', ['feature-state', 'hover'],    false], 0.85,
              0.72],
      },
    })

    // Outline layer — thicker + different colour when selected
    map.addLayer({
      id: OUTLINE_LAYER,
      type: 'line',
      source: SOURCE_ID,
      paint: {
        'line-color': [
          'case',
          ['boolean', ['feature-state', 'selected'], false], '#f59e0b',
          ['boolean', ['feature-state', 'hover'],    false], '#1d4ed8',
          _isBoundaryOnly ? '#6b7280' : '#ffffff',
        ],
        'line-width': [
          'case',
          ['boolean', ['feature-state', 'selected'], false], 2.5,
          ['boolean', ['feature-state', 'hover'],    false], 1.5,
          _isBoundaryOnly ? 1.0 : 0.5,
        ],
        'line-opacity': 0.9,
      },
    })

    // Selected glow layer — bright amber border only on the selected feature
    map.addLayer({
      id: SELECTED_LAYER,
      type: 'line',
      source: SOURCE_ID,
      paint: {
        'line-color': '#f59e0b',
        'line-width': ['case', ['boolean', ['feature-state', 'selected'], false], 3.5, 0],
        'line-opacity': ['case', ['boolean', ['feature-state', 'selected'], false], 1.0, 0],
        'line-blur': 1,
      },
    })

    if (fc_meta) {
      setMeta(fc_meta)
      setMeasureCode(fc_meta.measure_code)
    }

    // Fly to bounds — zoom to the scoped region if set, otherwise all features
    const scopeCode = currentPlan?.region_scope?.toUpperCase() ?? null
    const targetFeatures =
      scopeCode && currentPlan?.geography_level === 'gemeente'
        ? geojson.features.filter(
            f => (f.properties as { statcode?: string })?.statcode?.toUpperCase() === scopeCode
          )
        : geojson.features

    const flyFeatures = targetFeatures.length > 0 ? targetFeatures : geojson.features
    const bounds = new maplibregl.LngLatBounds()
    let hasCoords = false
    flyFeatures.forEach(f => {
      if (!f.geometry) return
      collectCoords(f.geometry).forEach(([lng, lat]) => {
        bounds.extend([lng, lat])
        hasCoords = true
      })
    })
    if (hasCoords) {
      map.fitBounds(bounds, { padding: 60, maxZoom: 13, duration: 800 })
    }
  }, [currentGeoJSON, mapReady])

  // ── Sync external deselect (X button in MapControls) ───────────────────────
  useEffect(() => {
    if (selectedRegion === null && selectedId.current !== null) {
      const map = mapRef.current
      if (map && map.getSource(SOURCE_ID)) {
        map.setFeatureState({ source: SOURCE_ID, id: selectedId.current }, { selected: false })
        if (map.getLayer(FILL_LAYER)) {
          const ibo = isBoundaryOnly.current
          map.setPaintProperty(FILL_LAYER, 'fill-opacity',
            ibo
              ? ['case', ['boolean', ['feature-state', 'selected'], false], 0.7, ['boolean', ['feature-state', 'hover'], false], 0.4, 0.0]
              : ['case', ['boolean', ['feature-state', 'selected'], false], 0.95, ['boolean', ['feature-state', 'hover'], false], 0.85, 0.72]
          )
        }
      }
      selectedId.current = null
    }
  }, [selectedRegion])

  // ── Fly to a searched/selected region ──────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current
    if (!map || !flyToStatcode || !currentGeoJSON) return

    const target = currentGeoJSON.features.find(
      f => f.properties.statcode === flyToStatcode
    )
    if (!target?.geometry) {
      setFlyTo(null)
      return
    }

    const bounds = new maplibregl.LngLatBounds()
    let hasCoords = false
    collectCoords(target.geometry).forEach(([lng, lat]) => {
      bounds.extend([lng, lat])
      hasCoords = true
    })
    if (hasCoords) {
      map.fitBounds(bounds, { padding: 80, maxZoom: 14, duration: 700 })
    }
    setFlyTo(null)
  }, [flyToStatcode, currentGeoJSON, setFlyTo])

  // ── Hover + click interactions ──────────────────────────────────────────────
  const setupInteractions = useCallback(() => {
    const map = mapRef.current
    if (!map) return

    // Hover
    map.on('mousemove', FILL_LAYER, e => {
      if (!e.features?.length) return
      map.getCanvas().style.cursor = 'pointer'

      const feat = e.features[0]
      const fid  = feat.id ?? null

      if (fid !== hoveredId.current) {
        if (hoveredId.current !== null)
          map.setFeatureState({ source: SOURCE_ID, id: hoveredId.current }, { hover: false })
        hoveredId.current = fid
        if (fid !== null)
          map.setFeatureState({ source: SOURCE_ID, id: fid }, { hover: true })
      }

      setTooltip({ x: e.point.x, y: e.point.y, props: feat.properties as ChoroplethFeatureProperties })
    })

    map.on('mouseleave', FILL_LAYER, () => {
      map.getCanvas().style.cursor = ''
      if (hoveredId.current !== null) {
        map.setFeatureState({ source: SOURCE_ID, id: hoveredId.current }, { hover: false })
        hoveredId.current = null
      }
      setTooltip(null)
    })

    // Click → select / deselect
    map.on('click', FILL_LAYER, e => {
      if (!e.features?.length) return
      const feat  = e.features[0]
      const fid   = feat.id ?? null
      const props = feat.properties as ChoroplethFeatureProperties & { gm_code?: string }

      const applyDim = (active: boolean) => {
        if (!map.getLayer(FILL_LAYER)) return
        const ibo = isBoundaryOnly.current
        map.setPaintProperty(FILL_LAYER, 'fill-opacity',
          ibo
            ? ['case',
                ['boolean', ['feature-state', 'selected'], false], 0.7,
                ['boolean', ['feature-state', 'hover'],    false], active ? 0.25 : 0.4,
                active ? 0.05 : 0.0]
            : ['case',
                ['boolean', ['feature-state', 'selected'], false], 0.95,
                ['boolean', ['feature-state', 'hover'],    false], active ? 0.45 : 0.85,
                active ? 0.12 : 0.72]
        )
      }

      if (fid === selectedId.current) {
        // Clicking the same feature deselects it
        if (fid !== null)
          map.setFeatureState({ source: SOURCE_ID, id: fid }, { selected: false })
        selectedId.current = null
        applyDim(false)
        selectRegion(null)
      } else {
        // Deselect previous
        if (selectedId.current !== null)
          map.setFeatureState({ source: SOURCE_ID, id: selectedId.current }, { selected: false })
        // Select new
        selectedId.current = fid
        if (fid !== null)
          map.setFeatureState({ source: SOURCE_ID, id: fid }, { selected: true })
        applyDim(true)
        selectRegion({
          statcode: props.statcode,
          statnaam: props.statnaam,
          gm_code:  props.gm_code,
        })
      }
    })

    // Click on empty map → deselect
    map.on('click', e => {
      const features = map.queryRenderedFeatures(e.point, { layers: [FILL_LAYER] })
      if (!features.length && selectedId.current !== null) {
        map.setFeatureState({ source: SOURCE_ID, id: selectedId.current }, { selected: false })
        selectedId.current = null
        if (map.getLayer(FILL_LAYER)) {
          const ibo = isBoundaryOnly.current
          map.setPaintProperty(FILL_LAYER, 'fill-opacity',
            ibo
              ? ['case', ['boolean', ['feature-state', 'selected'], false], 0.7, ['boolean', ['feature-state', 'hover'], false], 0.4, 0.0]
              : ['case', ['boolean', ['feature-state', 'selected'], false], 0.95, ['boolean', ['feature-state', 'hover'], false], 0.85, 0.72]
          )
        }
        selectRegion(null)
      }
    })
  }, [selectRegion])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    setupInteractions()
  }, [mapReady, setupInteractions])

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="relative w-full h-full bg-gray-100 dark:bg-gray-900">
      <div ref={mapContainer} className="absolute inset-0" />

      {/* Layer toggles + selected region badge */}
      <MapControls />

      {/* Search box — top right */}
      <div className="absolute top-3 right-3 z-10 pointer-events-auto">
        <MapSearch />
      </div>

      {/* Loading overlay */}
      {isLoading && (
        <div className="absolute inset-0 bg-white/30 dark:bg-gray-900/30 backdrop-blur-[1px]
                        flex items-center justify-center z-20 pointer-events-none">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg px-5 py-3
                          flex items-center gap-3 border border-gray-200 dark:border-gray-700">
            <div className="w-4 h-4 border-2 border-brand-600 border-t-transparent
                            rounded-full animate-spin" />
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
              Loading data…
            </span>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!currentGeoJSON && !isLoading && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-10">
          <div className="bg-white/80 dark:bg-gray-900/80 backdrop-blur-sm rounded-2xl
                          px-6 py-4 text-center shadow-lg border border-gray-200 dark:border-gray-700">
            <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
              Ask a question in the chat
            </p>
            <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
              The map will update with your data
            </p>
          </div>
        </div>
      )}

      {/* Legend */}
      {meta && <MapLegend meta={meta} measureCode={measureCode} />}

      {/* Tooltip — boundary mode shows only region name; choropleth mode shows value */}
      {tooltip && (
        <MapTooltip
          x={tooltip.x}
          y={tooltip.y}
          statnaam={tooltip.props.statnaam}
          value={meta ? tooltip.props.value : null}
          label={meta ? tooltip.props.label : 'Click to select'}
          measureCode={meta ? (currentPlan?.measure_code ?? '') : ''}
          period={meta?.period ?? ''}
        />
      )}

      {/* Attribution */}
      <div className="absolute bottom-2 right-2 text-[10px] text-gray-400 dark:text-gray-600
                      pointer-events-none z-10">
        CBS StatLine × PDOK
      </div>
    </div>
  )
}

// ── Utility ────────────────────────────────────────────────────────────────────

function collectCoords(geom: GeoJSON.Geometry): [number, number][] {
  const coords: [number, number][] = []
  const walk = (g: GeoJSON.Geometry) => {
    if (g.type === 'Point') coords.push(g.coordinates as [number, number])
    else if (g.type === 'LineString' || g.type === 'MultiPoint')
      (g.coordinates as [number, number][]).forEach(c => coords.push(c))
    else if (g.type === 'Polygon' || g.type === 'MultiLineString')
      (g.coordinates as [number, number][][]).flat().forEach(c => coords.push(c))
    else if (g.type === 'MultiPolygon')
      (g.coordinates as [number, number][][][]).flat(2).forEach(c => coords.push(c))
    else if (g.type === 'GeometryCollection')
      g.geometries.forEach(walk)
  }
  walk(geom)
  return coords
}
