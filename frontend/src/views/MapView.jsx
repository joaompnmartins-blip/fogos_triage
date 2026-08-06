import { useEffect, useRef, useState, useCallback } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { fetchFiresGeo } from '../api'
import {
  SEVERITY_COLOR, SEVERITY_LABEL, CONTROL_LABEL,
  STATUS_EM_RESOLUCAO, STATUS_EM_RESOLUCAO_COLOR, STATUS_EM_RESOLUCAO_LABEL,
} from '../constants'
import { REGION_BBOX, REGION_INITIAL_VIEW, flyToRegion } from '../region'
import {
  basemapStyle, addFuelModelLayer, setFuelModelLayerVisible, setFuelModelLayerOpacity,
  FUEL_MODEL_MIN_ZOOM,
} from '../basemaps'
import { FuelModelLegend } from '../components/SimulationPanels'

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

// O estado sobrepõe-se à severidade: uma ocorrência em resolução está
// dominada, e é isso que interessa ver no mapa, não a severidade que lhe
// foi atribuída à chegada. `status_code` é INTEGER na BD (migrations/
// 001_initial_schema.sql), ao contrário do `priority_class`, que chega
// como string — daí o `==` com número aqui e o `match` com '1'/'2' acima.
const fireColorExpr = [
  'case',
  ['==', ['get', 'status_code'], STATUS_EM_RESOLUCAO], STATUS_EM_RESOLUCAO_COLOR,
  priorityColorExpr,
]

export default function MapView({ apiKey, theme }) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const fireDataRef = useRef({ type: 'FeatureCollection', features: [] })
  const setupLayersFnRef = useRef(null)
  const basemapInitRef = useRef(true)  // skip first run of basemap effect
  const navigate = useNavigate()
  const location = useLocation()
  const [basemap, setBasemap] = useState('osm')
  const [fireCount, setFireCount] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [showFuelModel, setShowFuelModel] = useState(false)
  const [fuelModelOpacity, setFuelModelOpacity] = useState(0.7)
  // Zoom actual do mapa — só para saber se o overlay de combustível
  // tem tiles a este nível (ver FUEL_MODEL_MIN_ZOOM em basemaps.js).
  const [mapZoom, setMapZoom] = useState(0)
  const showFuelModelRef = useRef(false)
  const fuelModelOpacityRef = useRef(0.7)

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
      ...REGION_INITIAL_VIEW,
      attributionControl: false,
      maxZoom: 17,
      minZoom: 4,
    })

    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right')

    // Zoom vive fora do React; espelha-se em estado só para a UI poder

    // avisar quando o overlay de combustível não tem tiles a este nível.

    setMapZoom(map.getZoom())

    map.on('zoomend', () => setMapZoom(map.getZoom()))
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')

    mapRef.current = map

    // Adds fire source + layers using current fireDataRef
    function setupLayers() {
      // Overlay do modelo de combustível — independente de "fires", mas
      // precisa de ser reposto em cada style.load tal como o resto (ver
      // addFuelModelLayer, idempotente). Visibilidade lida de uma ref
      // (não do state directamente) para não ficar presa ao valor de
      // quando este closure foi criado (montagem inicial).
      addFuelModelLayer(map, { visible: showFuelModelRef.current, opacity: fuelModelOpacityRef.current })

      if (map.getSource('fires')) return
      map.addSource('fires', { type: 'geojson', data: fireDataRef.current })

      // Glow (all fires)
      map.addLayer({
        id: 'fires-glow',
        type: 'circle',
        source: 'fires',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 14, 12, 28],
          'circle-color': fireColorExpr,
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
          'circle-color': fireColorExpr,
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
          'circle-stroke-color': fireColorExpr,
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
      // Em resolução, o ponto está azul e não da cor da severidade — o
      // popup tem de dizer porquê, senão a cor fica a explicar-se a si
      // própria. A severidade continua visível, que é o ponto de a
      // manter aqui.
      const emResolucao = Number(p.status_code) === STATUS_EM_RESOLUCAO
      const linhaEstado = emResolucao
        ? `<div style="color:${STATUS_EM_RESOLUCAO_COLOR};font-size:10px;margin-bottom:3px">
             ● ${STATUS_EM_RESOLUCAO_LABEL}
           </div>`
        : ''
      popup
        .setLngLat(e.lngLat)
        .setHTML(`
          <div style="font-family:'IBM Plex Mono',monospace;font-size:11px;color:#d4e5d0;line-height:1.6">
            ${linhaEstado}
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

  // Clique em "Mapa" na barra lateral estando já no mapa — repõe o
  // enquadramento da região. O sinal é um carimbo de tempo novo em
  // `location.state` a cada clique (ver Sidebar em App.jsx); sem ele o
  // React Router não remontaria a vista e o mapa ficaria onde estava.
  //
  // Vindo de outra vista este efeito também corre, mas o mapa acabou de
  // montar já nesta posição, e o flyTo não tem para onde ir.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !location.state?.reporVista) return
    flyToRegion(map)
  }, [location.state?.reporVista])

  // Basemap/tema switching — skip first render (map já inicializado com o
  // estilo correcto em basemapStyle(basemap, theme) acima)
  useEffect(() => {
    if (basemapInitRef.current) { basemapInitRef.current = false; return }
    const map = mapRef.current
    if (!map) return
    map.setStyle(basemapStyle(basemap, theme), { diff: false })
  }, [basemap, theme])

  // Overlay do modelo de combustível — visibilidade/opacidade actualizadas
  // sem reconstruir nada (setLayoutProperty/setPaintProperty), e a ref
  // mantida em sincronia para addFuelModelLayer saber o valor certo
  // mesmo depois de uma troca de basemap que recria a source/layer.
  useEffect(() => {
    showFuelModelRef.current = showFuelModel
    const map = mapRef.current
    if (map) setFuelModelLayerVisible(map, showFuelModel)
  }, [showFuelModel])

  useEffect(() => {
    fuelModelOpacityRef.current = fuelModelOpacity
    const map = mapRef.current
    if (map) setFuelModelLayerOpacity(map, fuelModelOpacity)
  }, [fuelModelOpacity])

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
          Estado
        </div>
        <div className="map-legend">
          <div className="map-legend-item" title="Ocorrência dominada, a caminho da conclusão — a cor do estado sobrepõe-se à da severidade">
            <div className="map-legend-dot" style={{ background: STATUS_EM_RESOLUCAO_COLOR }} />
            <span>Em Resolução</span>
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

        {/* `pointer-events: all` é obrigatório aqui: o .map-info-panel é
            pointer-events:none (para o mapa continuar arrastável por baixo
            do painel) e os filhos herdam-no — sem isto o clique atravessa
            a checkbox e vai parar ao canvas, e o toggle parecia não fazer
            nada. É a mesma razão pela qual .map-basemap-btns repõe
            pointer-events:all (ver global.css). */}
        <label className="map-basemap-btn" style={{
          display: 'flex', alignItems: 'center', gap: 6, marginTop: 8,
          cursor: 'pointer', pointerEvents: 'all',
        }}>
          <input type="checkbox" checked={showFuelModel}
            onChange={e => setShowFuelModel(e.target.checked)} />
          Modelos de Combustível
        </label>
        {showFuelModel && mapZoom < FUEL_MODEL_MIN_ZOOM && (
          <div style={{
            marginTop: 6, maxWidth: 150,
            fontFamily: 'var(--font-mono)', fontSize: 9,
            color: 'var(--warn)', lineHeight: 1.35,
          }}>
            Aproxime o mapa para ver os modelos de combustível
          </div>
        )}
        {showFuelModel && mapZoom >= FUEL_MODEL_MIN_ZOOM && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6, marginTop: 6,
            pointerEvents: 'all',  // idem — senão o slider não recebe o arrasto
          }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)' }}>TRANSP</span>
            <input type="range" min={0} max={1} step={0.05}
              value={fuelModelOpacity} onChange={e => setFuelModelOpacity(parseFloat(e.target.value))}
              style={{ width: 80, cursor: 'pointer' }} />
          </div>
        )}
      </div>

      {showFuelModel && mapZoom >= FUEL_MODEL_MIN_ZOOM && (
        <div style={{ position: 'absolute', bottom: 10, left: 10, zIndex: 10 }}>
          <FuelModelLegend />
        </div>
      )}
    </div>
  )
}
