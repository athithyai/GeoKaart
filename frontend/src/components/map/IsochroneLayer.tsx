/**
 * IsochroneLayer — renders a reachability polygon on the MapLibre map.
 *
 * Renders as a semi-transparent teal fill with a solid border.
 * Stacks behind the choropleth fill so coloured regions show through.
 * Automatically removes itself when currentIsochrone is cleared.
 */
import { useEffect } from 'react'
import type maplibregl from 'maplibre-gl'
import { useChatStore } from '../../store/chatStore'

const SOURCE = 'isochrone-source'
const FILL   = 'isochrone-fill'
const LINE   = 'isochrone-line'

interface Props {
  map: maplibregl.Map
}

export function useIsochroneLayer({ map }: Props) {
  const currentIsochrone = useChatStore(s => s.currentIsochrone)

  useEffect(() => {
    if (!map) return

    const removeLayer = (id: string) => { if (map.getLayer(id))  map.removeLayer(id) }
    const removeSource = (id: string) => { if (map.getSource(id)) map.removeSource(id) }

    if (!currentIsochrone) {
      // Clean up when isochrone is cleared
      removeLayer(FILL)
      removeLayer(LINE)
      removeSource(SOURCE)
      return
    }

    // Wrap the Feature in a FeatureCollection for MapLibre
    const geojsonData: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features: [currentIsochrone],
    }

    if (map.getSource(SOURCE)) {
      // Update existing source
      (map.getSource(SOURCE) as maplibregl.GeoJSONSource).setData(geojsonData)
      return
    }

    map.addSource(SOURCE, { type: 'geojson', data: geojsonData })

    // Fill — behind choropleth (insert before the choropleth-fill layer if it exists)
    const beforeLayer = map.getLayer('choropleth-fill') ? 'choropleth-fill' : undefined

    map.addLayer(
      {
        id: FILL,
        type: 'fill',
        source: SOURCE,
        paint: {
          'fill-color': '#00A1CD',
          'fill-opacity': 0.12,
        },
      },
      beforeLayer,
    )

    // Outline
    map.addLayer({
      id: LINE,
      type: 'line',
      source: SOURCE,
      paint: {
        'line-color': '#00A1CD',
        'line-width': 2.5,
        'line-dasharray': [4, 2],
      },
    })

    return () => {
      removeLayer(FILL)
      removeLayer(LINE)
      removeSource(SOURCE)
    }
  }, [map, currentIsochrone])
}
