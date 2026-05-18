import { useEffect, useRef, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { fetchFiresGeo } from '../api'
import { PRIORITY_COLOR, PRIORITY_LABEL } from '../constants'

const PT_CENTER = [-8.0, 39.5]
const PT_BBOX = { minLat: 30, minLng: -32, maxLat: 42.5, maxLng: -5.5 }

const priorityColorExpr = [
  'match', ['get', 'priority_class'],
  'P0', PRIORITY_COLOR.P0,
  'P1', PRIORITY_COLOR.P1,
  'P2', PRIORITY_COLOR.P2,
  'P3', PRIORITY_COLOR.P3,
  'P4', PRIORITY_COLOR.P4,
  '#888888',
]

const OSM_STYLE = 'https://tiles.openfreemap.org/styles/liberty'

const SATELLITE_STYLE = {
  version: 8,
  sources: {
    satellite: {
      type: 'raster',
      tiles: [
        'https://mt0.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
        'https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
      ],
      tileSize: 256,
      attribution: '© Google',
      maxzoom: 20,
    },
  },
  layers: [{ id: 'satellite-bg', type: 'raster', source: 'satellite' }],
}

export default function MapView({ apiKey }) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const fireDataRef = useRef({ type: 'FeatureCollection', features: [] })
  const setupLayersFnRef = useRef(null)
  const navigate = useNavigate()
  const [basemap, setBasemap] = useState('osm')
  const [fireCount, setFireCount] = useState(null)
  const [loadError, setLoadError] = useState(null)

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const popup = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      className: 'ft-popup',
      offset: 10,
    })

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: OSM_STYLE,
      center: PT_CENTER,
      zoom: 6.5,
      attributionControl: false,
      maxZoom: 17,
      minZoom: 4,
    })

    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right')
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')

    mapRef.current = map

    // Adds fire source + layers using current fireDataRef
    function setupLayers() {
      if (map.getSource('fires')) return
      map.addSource('fires', { type: 'geojson', data: fireDataRef.current })
      map.addLayer({
        id: 'fires-glow',
        type: 'circle',
        source: 'fires',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 14, 12, 28],
          'circle-color': priorityColorExpr,
          'circle-opacity': 0.10,
          'circle-blur': 1,
        },
      })
      map.addLayer({
        id: 'fires-dot',
        type: 'circle',
        source: 'fires',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 5, 10, 10, 14, 16],
          'circle-color': priorityColorExpr,
          'circle-stroke-width': 1.5,
          'circle-stroke-color': 'rgba(255,255,255,0.25)',
          'circle-opacity': 0.92,
        },
      })
    }
    setupLayersFnRef.current = setupLayers

    async function loadFires() {
      try {
        const geojson = await fetchFiresGeo(apiKey, PT_BBOX)
        fireDataRef.current = geojson
        setFireCount(geojson.features?.length ?? 0)
        setLoadError(null)
        if (map.getSource('fires')) {
          map.getSource('fires').setData(geojson)
        }
      } catch (err) {
        setLoadError(err.message)
      }
    }

    // Event handlers — added once, survive setStyle
    map.on('click', 'fires-dot', (e) => {
      const { fire_id } = e.features[0].properties
      navigate(`/fogo/${fire_id}`)
    })

    map.on('mouseenter', 'fires-dot', (e) => {
      map.getCanvas().style.cursor = 'pointer'
      const p = e.features[0].properties
      const priority = p.priority_class || '—'
      const pLabel = PRIORITY_LABEL[priority] || ''
      const pColor = PRIORITY_COLOR[priority] || '#888'
      const loc = [p.municipality, p.district].filter(Boolean).join(' · ')
      const flame = p.flame_length_m != null ? `${Number(p.flame_length_m).toFixed(1)}m` : '—'
      popup
        .setLngLat(e.lngLat)
        .setHTML(`
          <div style="font-family:'IBM Plex Mono',monospace;font-size:11px;color:#d4e5d0;line-height:1.6">
            <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
              <span style="color:${pColor};font-weight:500">${priority} ${pLabel}</span>
            </div>
            <div style="color:#8ab08a">${loc || p.parish || '—'}</div>
            <div style="color:#4d6650;font-size:10px;margin-top:2px">Chama ${flame}</div>
          </div>
        `)
        .addTo(map)
    })

    map.on('mouseleave', 'fires-dot', () => {
      map.getCanvas().style.cursor = ''
      popup.remove()
    })

    map.on('load', () => {
      setupLayers()
      loadFires()
    })

    const interval = setInterval(loadFires, 120_000)

    return () => {
      clearInterval(interval)
      popup.remove()
      mapRef.current.remove()
      mapRef.current = null
    }
  }, [apiKey]) // eslint-disable-line

  // Basemap switching
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const style = basemap === 'satellite' ? SATELLITE_STYLE : OSM_STYLE
    map.setStyle(style)
    map.once('style.load', () => setupLayersFnRef.current?.())
  }, [basemap])

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <style>{`
        .maplibregl-popup-content {
          background: #0d1410 !important;
          border: 1px solid #1e2b1f !important;
          border-radius: 3px !important;
          padding: 10px 12px !important;
          box-shadow: 0 4px 16px #00000060 !important;
        }
        .maplibregl-popup-tip { display: none !important; }
        .maplibregl-ctrl-attrib { font-size: 9px !important; opacity: 0.5 !important; }
        .maplibregl-ctrl-group { background: var(--surface) !important; border: 1px solid var(--border) !important; }
        .maplibregl-ctrl-group button { background: transparent !important; color: var(--muted) !important; }
        .maplibregl-ctrl-group button:hover { background: var(--surface2) !important; color: var(--text) !important; }
      `}</style>

      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />

      <div className="map-info-panel">
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted)', letterSpacing: '.08em', textTransform: 'uppercase', marginBottom: 8 }}>
          Prioridade
        </div>
        <div className="map-legend">
          {['P0', 'P1', 'P2', 'P3', 'P4'].map(p => (
            <div key={p} className="map-legend-item">
              <div className="map-legend-dot" style={{ background: PRIORITY_COLOR[p] }} />
              <span style={{ color: 'var(--text)' }}>{p}</span>
              <span>{PRIORITY_LABEL[p]}</span>
            </div>
          ))}
          <div className="map-legend-item" style={{ marginTop: 4 }}>
            <div className="map-legend-dot" style={{ background: '#888888' }} />
            <span>Sem triagem</span>
          </div>
        </div>

        {fireCount !== null && (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted)', marginTop: 10, borderTop: '1px solid var(--border)', paddingTop: 8 }}>
            {fireCount} ocorrência{fireCount !== 1 ? 's' : ''}
          </div>
        )}
        {loadError && (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--danger)', marginTop: 6 }}>
            Erro: {loadError}
          </div>
        )}

        <div className="map-basemap-btns">
          <button
            className={`map-basemap-btn${basemap === 'osm' ? ' active' : ''}`}
            onClick={() => setBasemap('osm')}
          >
            Mapa
          </button>
          <button
            className={`map-basemap-btn${basemap === 'satellite' ? ' active' : ''}`}
            onClick={() => setBasemap('satellite')}
          >
            Satélite
          </button>
        </div>
      </div>
    </div>
  )
}
