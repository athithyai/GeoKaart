/**
 * useIsochroneLayer — renders a reachability polygon on the MapLibre map.
 *
 * Teal dashed outline + semi-transparent fill.
 * Sits behind the choropleth fill so coloured regions show through.
 * Clears itself when currentIsochrone becomes null.
 *
 * Design note: mapRef is passed (not map directly) because refs don't
 * trigger re-renders. mapReady is the stable signal that the map exists.
 */
import { useEffect, type RefObject } from 'react'
import type maplibregl from 'maplibre-gl'
import { useChatStore } from '../../store/chatStore'

const SOURCE = 'isochrone-source'
const FILL   = 'isochrone-fill'
const LINE   = 'isochrone-line'

interface Props {
  mapRef: RefObject<maplibregl.Map | null>
  mapReady: boolean
}

export function useIsochroneLayer({ mapRef, mapReady }: Props) {
  const currentIsochrone = useChatStore(s => s.currentIsochrone)

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return

    const removeLayer = (id: string) => { try { if (map.getLayer(id))  map.removeLayer(id)  } catch {} }
    const removeSource= (id: string) => { try { if (map.getSource(id)) map.removeSource(id) } catch {} }

    if (!currentIsochrone) {
      removeLayer(FILL)
      removeLayer(LINE)
      removeSource(SOURCE)
      return
    }

    const geojsonData: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features: [currentIsochrone],
    }

    if (map.getSource(SOURCE)) {
      ;(map.getSource(SOURCE) as maplibregl.GeoJSONSource).setData(geojsonData)
      return
    }

    map.addSource(SOURCE, { type: 'geojson', data: geojsonData })

    // Insert behind choropleth fill so coloured regions show through
    const beforeLayer = map.getLayer('choropleth-fill') ? 'choropleth-fill' : undefined

    map.addLayer(
      {
        id: FILL,
        type: 'fill',
        source: SOURCE,
        paint: {
          'fill-color': '#00A1CD',
          'fill-opacity': 0.15,
        },
      },
      beforeLayer,
    )

    map.addLayer({
      id: LINE,
      type: 'line',
      source: SOURCE,
      paint: {
        'line-color': '#00A1CD',
        'line-width': 3,
        'line-dasharray': [3, 2],
      },
    })

    // Fly map to show the isochrone
    try {
      const coords = (currentIsochrone.geometry as GeoJSON.Polygon).coordinates[0]
      if (coords && coords.length > 0) {
        const lons = coords.map(c => c[0])
        const lats = coords.map(c => c[1])
        map.fitBounds(
          [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
          { padding: 60, duration: 1200, maxZoom: 14 }
        )
      }
    } catch {}

  }, [mapRef, mapReady, currentIsochrone])
}
