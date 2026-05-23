import { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { fetchFireDetail, postSimulate, getSimulationJob } from '../api'
import { fmt, fmtDateTime } from '../constants'

const OSM_STYLE = 'https://tiles.openfreemap.org/styles/liberty'
const SATELLITE_STYLE = {
  version: 8,
  sources: {
    satellite: {
      type: 'raster',
      tiles: [
        'https://mt0.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
        'https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
      ],
      tileSize: 256,
      attribution: '© Google',
      maxzoom: 20,
    },
  },
  layers: [{ id: 'satellite-bg', type: 'raster', source: 'satellite' }],
}

const ROS_COLOR_EXPR = [
  'interpolate', ['linear'], ['get', 'ros_m_min'],
  0, '#3b82f6', 1, '#22c55e', 5, '#f97316', 20, '#ef4444',
]
const FLI_COLOR_EXPR = [
  'interpolate', ['linear'], ['get', 'fi_kw_m'],
  0, '#3b82f6', 100, '#22c55e', 500, '#f97316', 2000, '#ef4444',
]
const FLAME_COLOR_EXPR = [
  'interpolate', ['linear'], ['get', 'flame_m'],
  0, '#3b82f6', 1, '#22c55e', 2.5, '#f97316', 4, '#ef4444',
]

const COLOR_EXPRS = { ros: ROS_COLOR_EXPR, fi: FLI_COLOR_EXPR, flame: FLAME_COLOR_EXPR }
const COLOR_LABELS = { ros: 'ROS m/min', fi: 'FLI kW/m', flame: 'Chama m' }
const COLOR_STOPS = {
  ros:   [{ v: 0, c: '#3b82f6' }, { v: 1, c: '#22c55e' }, { v: 5, c: '#f97316' }, { v: '20+', c: '#ef4444' }],
  fi:    [{ v: 0, c: '#3b82f6' }, { v: 100, c: '#22c55e' }, { v: 500, c: '#f97316' }, { v: '2000+', c: '#ef4444' }],
  flame: [{ v: 0, c: '#3b82f6' }, { v: 1, c: '#22c55e' }, { v: 2.5, c: '#f97316' }, { v: '4+', c: '#ef4444' }],
}

const PERIM_STYLES = {
  1: { color: '#f97316', fillOpacity: 0.08 },
  2: { color: '#ef4444', fillOpacity: 0.12 },
  3: { color: '#991b1b', fillOpacity: 0.18 },
  6: { color: '#7f1d1d', fillOpacity: 0.22 },
}

export default function SimulacaoView({ apiKey }) {
  const { fireId } = useParams()
  const mapRef = useRef(null)
  const containerRef = useRef(null)

  const [fire, setFire] = useState(null)
  const [basemap, setBasemap] = useState('osm')
  const [layer, setLayer] = useState('ros')
  const [opacity, setOpacity] = useState(0.75)
  const [durationH, setDurationH] = useState(3)
  const [windOverride, setWindOverride] = useState({ speed: '', dir: '' })
  const [jobStatus, setJobStatus] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const pollRef = useRef(null)

  useEffect(() => {
    fetchFireDetail(apiKey, fireId)
      .then(setFire)
      .catch(e => setError(e.message))
  }, [apiKey, fireId])

  useEffect(() => {
    if (!containerRef.current || mapRef.current || !fire) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: OSM_STYLE,
      center: [fire.longitude, fire.latitude],
      zoom: 12,
      attributionControl: false,
    })
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right')
    new maplibregl.Marker({ color: '#ef4444' })
      .setLngLat([fire.longitude, fire.latitude])
      .addTo(map)
    mapRef.current = map
    return () => { map.remove(); mapRef.current = null }
  }, [fire])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    map.setStyle(basemap === 'osm' ? OSM_STYLE : SATELLITE_STYLE)
    map.once('styledata', () => { if (result) _renderLayers(map, result, layer, opacity) })
  }, [basemap])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !result) return
    const onReady = () => _renderLayers(map, result, layer, opacity)
    if (map.isStyleLoaded()) onReady()
    else map.once('styledata', onReady)
  }, [result, layer, opacity])

  function startPolling(jobId) {
    pollRef.current = setInterval(async () => {
      try {
        const job = await getSimulationJob(apiKey, jobId)
        setJobStatus(job.status)
        if (job.status === 'done') {
          clearInterval(pollRef.current)
          setResult(job.result)
        } else if (job.status === 'failed') {
          clearInterval(pollRef.current)
          setError(job.error_message || 'Simulação falhou')
        }
      } catch (e) {
        clearInterval(pollRef.current)
        setError(e.message)
      }
    }, 2000)
  }

  useEffect(() => () => clearInterval(pollRef.current), [])

  async function handleSimulate() {
    setJobStatus('pending')
    setResult(null)
    setError(null)
    try {
      const job = await postSimulate(apiKey, fireId, {
        duration_h: durationH,
        wind_speed_ms: windOverride.speed ? parseFloat(windOverride.speed) : undefined,
        wind_direction_deg: windOverride.dir ? parseFloat(windOverride.dir) : undefined,
      })
      setJobStatus(job.status)
      startPolling(job.job_id)
    } catch (e) {
      setJobStatus(null)
      setError(e.message)
    }
  }

  if (!fire) return <div className="state-center" style={{ height: '100%' }}>A carregar…</div>

  const triage = fire.triage
  const isRunning = jobStatus === 'pending' || jobStatus === 'running'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>

      <div className="breadcrumb" style={{ flexShrink: 0 }}>
        <Link to="/lista">Ocorrências</Link>
        <span className="sep">›</span>
        <Link to={`/fogo/${fireId}`}>{[fire.municipality, fire.district].filter(Boolean).join(', ')}</Link>
        <span className="sep">›</span>
        <span>Simulação</span>
      </div>

      {/* Mapa */}
      <div style={{ flex: '0 0 60%', position: 'relative' }}>
        <div ref={containerRef} style={{ width: '100%', height: '100%' }} />

        <div style={{
          position: 'absolute', top: 10, right: 10, zIndex: 10,
          display: 'flex', flexDirection: 'column', gap: 6,
        }}>
          <div style={{ display: 'flex', gap: 4 }}>
            {['osm', 'satellite'].map(b => (
              <button key={b} className={`btn btn-ghost${basemap === b ? ' active' : ''}`}
                style={{ fontSize: 10, padding: '3px 8px' }}
                onClick={() => setBasemap(b)}>
                {b === 'osm' ? 'OSM' : 'SAT'}
              </button>
            ))}
          </div>

          {result && (
            <>
              <div style={{ display: 'flex', gap: 4 }}>
                {Object.entries(COLOR_LABELS).map(([k, label]) => (
                  <button key={k} className={`btn btn-ghost${layer === k ? ' active' : ''}`}
                    style={{ fontSize: 9, padding: '3px 6px' }}
                    onClick={() => setLayer(k)}>
                    {label.split(' ')[0]}
                  </button>
                ))}
              </div>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 6,
                background: 'var(--bg2)', borderRadius: 4, padding: '4px 8px',
              }}>
                <span style={{ fontSize: 9, color: 'var(--muted)', fontFamily: 'var(--font-mono)' }}>TRANSP</span>
                <input type="range" min={0} max={1} step={0.05}
                  value={opacity} onChange={e => setOpacity(parseFloat(e.target.value))}
                  style={{ width: 80, cursor: 'pointer' }} />
              </div>
              <Legend stops={COLOR_STOPS[layer]} label={COLOR_LABELS[layer]} />
            </>
          )}
        </div>
      </div>

      {/* Painel inferior */}
      <div style={{
        flex: '0 0 40%', overflowY: 'auto', borderTop: '1px solid var(--border)',
        padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 12,
      }}>

        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)', marginBottom: 4 }}>
              DURAÇÃO
            </div>
            <div style={{ display: 'flex', gap: 4 }}>
              {[1, 2, 3, 6].map(h => (
                <button key={h} className={`btn btn-ghost${durationH === h ? ' active' : ''}`}
                  style={{ fontSize: 11, padding: '4px 10px' }}
                  onClick={() => setDurationH(h)}>
                  {h}h
                </button>
              ))}
            </div>
          </div>

          <div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)', marginBottom: 4 }}>
              VENTO OVERRIDE (opcional)
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <input className="form-input" type="number" placeholder="m/s"
                style={{ width: 70, fontSize: 12 }}
                value={windOverride.speed}
                onChange={e => setWindOverride(p => ({ ...p, speed: e.target.value }))} />
              <input className="form-input" type="number" placeholder="° dir"
                style={{ width: 70, fontSize: 12 }}
                value={windOverride.dir}
                onChange={e => setWindOverride(p => ({ ...p, dir: e.target.value }))} />
            </div>
          </div>

          <button
            className="btn btn-primary"
            disabled={isRunning || !triage}
            onClick={handleSimulate}
            style={{ padding: '6px 18px', alignSelf: 'flex-end' }}
          >
            {isRunning
              ? <><span className="dot" style={{ marginRight: 6 }} />A calcular…</>
              : '▶ Simular'}
          </button>

          {!triage && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--warn)' }}>
              Sem triagem — simulação não disponível
            </span>
          )}
        </div>

        {error && (
          <div style={{ color: 'var(--danger)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
            ✗ {error}
          </div>
        )}

        {result && <ResultsTable perimeters={result.perimeters} />}

        {result && (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--dim)', marginTop: 4 }}>
            {'Meteo: Open-Meteo · vento '}
            {fmt(result.meta.wind_speed_ms, 1)} m/s {fmt(result.meta.wind_dir_deg, 0)}°
            {triage && ` · Triagem: ${fmtDateTime(triage.computed_at)}`}
            {` · Resolução: ${result.meta.resolution_m}m`}
          </div>
        )}
      </div>
    </div>
  )
}

function Legend({ stops, label }) {
  return (
    <div style={{
      background: 'var(--bg2)', borderRadius: 4, padding: '6px 8px',
      fontFamily: 'var(--font-mono)', fontSize: 9,
    }}>
      <div style={{ color: 'var(--muted)', marginBottom: 4 }}>{label.toUpperCase()}</div>
      <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
        {stops.map(({ v, c }) => (
          <div key={v} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
            <div style={{ width: 16, height: 10, borderRadius: 2, background: c }} />
            <span style={{ color: 'var(--dim)' }}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function ResultsTable({ perimeters }) {
  return (
    <div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)', marginBottom: 6 }}>
        RESULTADOS DA SIMULAÇÃO
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            {['Hora', 'Área (ha)', 'ROS máx', 'FLI máx', 'Chama máx'].map(h => (
              <th key={h} style={{ padding: '4px 8px', textAlign: 'left', color: 'var(--muted)', fontWeight: 400, fontSize: 9 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {perimeters.map(p => (
            <tr key={p.t_h} style={{ borderBottom: '1px solid rgba(37,52,39,.3)' }}>
              <td style={{ padding: '6px 8px', color: 'var(--accent2)', fontWeight: 700 }}>t={p.t_h}h</td>
              <td style={{ padding: '6px 8px' }}>{fmt(p.area_ha, 0)}</td>
              <td style={{ padding: '6px 8px', color: 'var(--warn)' }}>—</td>
              <td style={{ padding: '6px 8px', color: 'var(--warn)' }}>—</td>
              <td style={{ padding: '6px 8px', color: 'var(--warn)' }}>—</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ fontSize: 9, color: 'var(--dim)', marginTop: 4, fontFamily: 'var(--font-mono)' }}>
        * ROS/FLI/Chama máx calculados a partir da grelha de pixels
      </div>
    </div>
  )
}

function _renderLayers(map, result, layer, opacity) {
  ['sim-pixels-fill', 'sim-pixels-outline',
    'perim-1h-fill', 'perim-1h-line',
    'perim-2h-fill', 'perim-2h-line',
    'perim-3h-fill', 'perim-3h-line',
    'perim-6h-fill', 'perim-6h-line',
  ].forEach(id => { try { map.removeLayer(id) } catch {} });
  ['sim-pixels', 'perim-1h', 'perim-2h', 'perim-3h', 'perim-6h',
  ].forEach(id => { try { map.removeSource(id) } catch {} })

  if (result.pixel_grid) {
    map.addSource('sim-pixels', { type: 'geojson', data: result.pixel_grid })
    map.addLayer({
      id: 'sim-pixels-fill',
      type: 'fill',
      source: 'sim-pixels',
      paint: {
        'fill-color': COLOR_EXPRS[layer],
        'fill-opacity': opacity,
      },
    })
  }

  result.perimeters.forEach(({ t_h, geojson }) => {
    const style = PERIM_STYLES[t_h] || PERIM_STYLES[3]
    const id = `perim-${t_h}h`
    map.addSource(id, { type: 'geojson', data: geojson })
    map.addLayer({
      id: `${id}-fill`,
      type: 'fill',
      source: id,
      paint: { 'fill-color': style.color, 'fill-opacity': style.fillOpacity },
    })
    map.addLayer({
      id: `${id}-line`,
      type: 'line',
      source: id,
      paint: {
        'line-color': style.color,
        'line-width': t_h === Math.max(...result.perimeters.map(p => p.t_h)) ? 2 : 1,
      },
    })
  })
}
