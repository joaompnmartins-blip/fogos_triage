import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { fetchFiresGeo } from '../api'
import { PRIORITY_COLOR, PRIORITY_LABEL } from '../constants'

// Portugal (continental + ilhas) bounding box
const PT_CENTER = [-8.0, 39.5]
const PT_BBOX = { minLat: 30, minLng: -32, maxLat: 42.5, maxLng: -5.5 }

// MapLibre expression: match priority_class → color
const priorityColorExpr = [
  'match', ['get', 'priority_class'],
  'P0', PRIORITY_COLOR.P0,
  'P1', PRIORITY_COLOR.P1,
  'P2', PRIORITY_COLOR.P2,
  'P3', PRIORITY_COLOR.P3,
  'P4', PRIORITY_COLOR.P4,
  '#2d3d2f',
]

export default function MapView({ apiKey }) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const navigate = useNavigate()
  const [fireCount, setFireCount] = useState(null)
  const [loadError, setLoadError] = useState(null)

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
      center: PT_CENTER,
      zoom: 6.5,
      attributionControl: false,
      maxZoom: 17,
      minZoom: 4,
    })

    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right')
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')

    mapRef.current = map

    const loadFires = async () => {
      try {
        const geojson = await fetchFiresGeo(apiKey, PT_BBOX)
        setFireCount(geojson.features?.length ?? 0)
        setLoadError(null)

        if (map.getSource('fires')) {
          map.getSource('fires').setData(geojson)
          return
        }

        map.addSource('fires', { type: 'geojson', data: geojson })

        // Glow / halo (larger, more transparent)
        map.addLayer({
          id: 'fires-glow',
          type: 'circle',
          source: 'fires',
          paint: {
            'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 14, 12, 28],
            'circle-color': priorityColorExpr,
            'circle-opacity': 0.08,
            'circle-blur': 1,
          },
        })

        // Main dot
        map.addLayer({
          id: 'fires-dot',
          type: 'circle',
          source: 'fires',
          paint: {
            'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 5, 10, 10, 14, 16],
            'circle-color': priorityColorExpr,
            'circle-stroke-width': 1.5,
            'circle-stroke-color': ['case', ['has', 'priority_class'], '#ffffff18', 'transparent'],
            'circle-opacity': 0.92,
          },
        })

        // Click → navigate to detail
        map.on('click', 'fires-dot', (e) => {
          const { fire_id } = e.features[0].properties
          navigate(`/fogo/${fire_id}`)
        })

        // Popup on hover
        const popup = new maplibregl.Popup({
          closeButton: false,
          closeOnClick: false,
          className: 'ft-popup',
          offset: 10,
        })

        map.on('mouseenter', 'fires-dot', (e) => {
          map.getCanvas().style.cursor = 'pointer'
          const p = e.features[0].properties
          const priority = p.priority_class || '—'
          const pLabel = PRIORITY_LABEL[priority] || ''
          const pColor = PRIORITY_COLOR[priority] || '#4d6650'
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
      } catch (err) {
        setLoadError(err.message)
      }
    }

    map.on('load', loadFires)

    // Refresh every 2 min
    const interval = setInterval(() => {
      if (map.getSource('fires')) loadFires()
    }, 120_000)

    return () => {
      clearInterval(interval)
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
      }
    }
  }, [apiKey])

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
        .maplibregl-ctrl-attrib { font-size: 9px !important; opacity: 0.4 !important; }
        .maplibregl-ctrl-group { background: #0d1410 !important; border: 1px solid #1e2b1f !important; }
        .maplibregl-ctrl-group button { background: transparent !important; color: #4d6650 !important; }
        .maplibregl-ctrl-group button:hover { background: #121a14 !important; color: #d4e5d0 !important; }
      `}</style>

      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />

      {/* Legend panel */}
      <div className="map-info-panel">
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>
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
            <div className="map-legend-dot" style={{ background: '#2d3d2f' }} />
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
      </div>
    </div>
  )
}
