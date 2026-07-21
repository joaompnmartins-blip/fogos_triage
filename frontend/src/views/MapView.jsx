import { useEffect, useRef, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { fetchFiresGeo } from '../api'
import { SEVERITY_COLOR, SEVERITY_LABEL, CONTROL_LABEL } from '../constants'
import { REGION_CENTER, REGION_BBOX, REGION_ZOOM } from '../region'
import { basemapStyle } from '../basemaps'

const priorityColorExpr = [
  'match', ['get', 'priority_class'],
  '1', SEVERITY_COLOR[1],
  '2', SEVERITY_COLOR[2],
  '3', SEVERITY_COLOR[3],
  '4', SEVERITY_COLOR[4],
  '5', SEVERITY_COLOR[5],
  '6', SEVERITY_COLOR[6],
  '7', SEVERITY_COLOR[7],
  '#888888',
]

export default function MapView({ apiKey, theme }) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const fireDataRef = useRef({ type: 'FeatureCollection', features: [] })
  const setupLayersFnRef = useRef(null)
  const basemapInitRef = useRef(true)  // skip first run of basemap effect
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
      style: basemapStyle(basemap, theme),
      center: REGION_CENTER,
      zoom: REGION_ZOOM,
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

      // Glow (all fires)
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

      // Main dot (all fires, priority color)
      // Agrícola (3105): anel dourado; outros: anel branco subtil
      map.addLayer({
        id: 'fires-dot',
        type: 'circle',
        source: 'fires',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 5, 10, 10, 14, 16],
          'circle-color': priorityColorExpr,
          'circle-stroke-width': ['match', ['get', 'natureza_code'],
            3105, 2.5,
            3109, 0,
            1.5,
          ],
          'circle-stroke-color': ['match', ['get', 'natureza_code'],
            3105, 'rgba(255,200,0,0.90)',
            'rgba(255,255,255,0.25)',
          ],
          'circle-opacity': 0.92,
        },
      })

      // Anel exterior para Gestão de Combustível (3109) — cria aspeto ⊙
      map.addLayer({
        id: 'fires-gc-ring',
        type: 'circle',
        source: 'fires',
        filter: ['==', ['get', 'natureza_code'], 3109],
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 9, 10, 16, 14, 24],
          'circle-color': 'rgba(0,0,0,0)',
          'circle-stroke-width': 1.5,
          'circle-stroke-color': priorityColorExpr,
          'circle-opacity': 1,
        },
      })
    }
    setupLayersFnRef.current = setupLayers

    // Re-add fires source/layers every time a new style is loaded (initial + basemap switches)
    map.on('style.load', () => setupLayersFnRef.current?.())

    async function loadFires() {
      try {
        const geojson = await fetchFiresGeo(apiKey, REGION_BBOX)
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
      const category = p.priority_class || null
      const pLabel = SEVERITY_LABEL[category] || '—'
      const pColor = SEVERITY_COLOR[category] || '#888'
      const loc = [p.municipality, p.district].filter(Boolean).join(' · ')
      const flame = p.flame_length_m != null ? `${Number(p.flame_length_m).toFixed(1)}m` : '—'
      popup
        .setLngLat(e.lngLat)
        .setHTML(`
          <div style="font-family:'IBM Plex Mono',monospace;font-size:11px;color:#d4e5d0;line-height:1.6">
            <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
              <span style="color:${pColor};font-weight:500">${category ?? '—'} ${pLabel}</span>
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

    map.on('load', loadFires)

    const interval = setInterval(loadFires, 120_000)

    return () => {
      clearInterval(interval)
      popup.remove()
      mapRef.current.remove()
      mapRef.current = null
    }
  }, [apiKey]) // eslint-disable-line

  // Basemap/tema switching — skip first render (map já inicializado com o
  // estilo correcto em basemapStyle(basemap, theme) acima)
  useEffect(() => {
    if (basemapInitRef.current) { basemapInitRef.current = false; return }
    const map = mapRef.current
    if (!map) return
    map.setStyle(basemapStyle(basemap, theme), { diff: false })
  }, [basemap, theme])

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
          Classificação
        </div>
        <div className="map-legend">
          {[1, 2, 3, 4].map(cat => (
            <div key={cat} className="map-legend-item" title={CONTROL_LABEL[cat]}>
              <div className="map-legend-dot" style={{ background: SEVERITY_COLOR[cat] }} />
              <span style={{ color: 'var(--text)' }}>{cat}</span>
              <span>{SEVERITY_LABEL[cat]}</span>
            </div>
          ))}
          <div style={{ height: 1, background: 'var(--border)', margin: '3px 0' }} />
          {[5, 6, 7].map(cat => (
            <div key={cat} className="map-legend-item" title={CONTROL_LABEL[cat]}>
              <div className="map-legend-dot" style={{ background: SEVERITY_COLOR[cat], outline: '1.5px solid rgba(255,255,255,0.4)', outlineOffset: '1px' }} />
              <span style={{ color: 'var(--text)' }}>{cat}</span>
              <span>{SEVERITY_LABEL[cat]}</span>
            </div>
          ))}
          <div className="map-legend-item" style={{ marginTop: 4 }}>
            <div className="map-legend-dot" style={{ background: '#888888' }} />
            <span>Sem triagem</span>
          </div>
        </div>

        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted)', letterSpacing: '.08em', textTransform: 'uppercase', marginTop: 10, marginBottom: 6 }}>
          Tipo
        </div>
        <div className="map-legend">
          <div className="map-legend-item">
            <div className="map-legend-dot" style={{ background: 'var(--muted)' }} />
            <span>Florestal / Mato</span>
          </div>
          <div className="map-legend-item">
            <div className="map-legend-dot" style={{ background: 'var(--muted)', outline: '1.5px solid var(--muted)', outlineOffset: '2px' }} />
            <span>Gestão Combustível</span>
          </div>
          <div className="map-legend-item">
            <div className="map-legend-dot" style={{ background: 'var(--muted)', outline: '2px solid rgba(255,200,0,0.85)', outlineOffset: '1px' }} />
            <span>Agrícola</span>
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
          <button
            className={`map-basemap-btn${basemap === 'topo' ? ' active' : ''}`}
            onClick={() => setBasemap('topo')}
          >
            Topo
          </button>
        </div>
      </div>
    </div>
  )
}
