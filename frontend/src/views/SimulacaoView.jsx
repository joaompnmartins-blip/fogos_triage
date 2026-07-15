import { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip,
} from 'recharts'
import { fetchFireDetail, postSimulate, getSimulationJob } from '../api'
import { fmt, fmtDateTime, windDirText } from '../constants'

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
  'interpolate', ['linear'], ['coalesce', ['get', 'ros_m_min'], 0],
  0, '#3b82f6', 1, '#22c55e', 5, '#f97316', 20, '#ef4444',
]
const FLI_COLOR_EXPR = [
  'interpolate', ['linear'], ['coalesce', ['get', 'fi_kw_m'], 0],
  0, '#3b82f6', 100, '#22c55e', 500, '#f97316', 2000, '#ef4444',
]
const FLAME_COLOR_EXPR = [
  'interpolate', ['linear'], ['coalesce', ['get', 'flame_m'], 0],
  0, '#3b82f6', 1, '#22c55e', 2.5, '#f97316', 4, '#ef4444',
]

const COLOR_EXPRS = { ros: ROS_COLOR_EXPR, fi: FLI_COLOR_EXPR, flame: FLAME_COLOR_EXPR }
const COLOR_LABELS = { ros: 'ROS m/min', fi: 'FLI kW/m', flame: 'Chama m' }
const COLOR_STOPS = {
  ros:   [{ v: 0, c: '#3b82f6' }, { v: 1, c: '#22c55e' }, { v: 5, c: '#f97316' }, { v: '20+', c: '#ef4444' }],
  fi:    [{ v: 0, c: '#3b82f6' }, { v: 100, c: '#22c55e' }, { v: 500, c: '#f97316' }, { v: '2000+', c: '#ef4444' }],
  flame: [{ v: 0, c: '#3b82f6' }, { v: 1, c: '#22c55e' }, { v: 2.5, c: '#f97316' }, { v: '4+', c: '#ef4444' }],
}

// Rampa sequencial (tempo decorrido é uma grandeza ordenada) — um único
// matiz, claro→escuro, entre os mesmos extremos usados antes (âncoras
// visuais já conhecidas na app: laranja cedo → vermelho-escuro tarde).
const PERIM_RAMP_FROM = [0xf9, 0x73, 0x16]
const PERIM_RAMP_TO = [0x7f, 0x1d, 0x1d]

function _perimStyle(index, total) {
  const frac = total > 1 ? index / (total - 1) : 0
  const rgb = PERIM_RAMP_FROM.map((c0, i) =>
    Math.round(c0 + (PERIM_RAMP_TO[i] - c0) * frac))
  const color = `#${rgb.map(v => v.toString(16).padStart(2, '0')).join('')}`
  return { color, fillOpacity: 0.08 + 0.18 * frac }
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
  const [visiblePerimeters, setVisiblePerimeters] = useState(new Set())
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
    map.once('styledata', () => {
      if (result) _renderLayers(map, result, layer, opacity, visiblePerimeters)
    })
  }, [basemap])

  // Novo resultado — todos os perímetros começam visíveis
  useEffect(() => {
    if (result) setVisiblePerimeters(new Set(result.perimeters.map(p => p.t_h)))
  }, [result])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !result) return
    const onReady = () => _renderLayers(map, result, layer, opacity, visiblePerimeters)
    if (map.isStyleLoaded()) onReady()
    else map.once('styledata', onReady)
  }, [result, layer, opacity, visiblePerimeters])

  function togglePerimeter(t_h) {
    setVisiblePerimeters(prev => {
      const next = new Set(prev)
      if (next.has(t_h)) next.delete(t_h); else next.add(t_h)
      return next
    })
  }

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

              <div style={{
                background: 'var(--bg2)', borderRadius: 4, padding: '4px 6px',
              }}>
                <div style={{ fontSize: 9, color: 'var(--muted)', fontFamily: 'var(--font-mono)', marginBottom: 3 }}>
                  PERÍMETROS
                </div>
                <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap', maxWidth: 140 }}>
                  {result.perimeters.map((p, i) => {
                    const { color } = _perimStyle(i, result.perimeters.length)
                    const on = visiblePerimeters.has(p.t_h)
                    return (
                      <button key={p.t_h}
                        onClick={() => togglePerimeter(p.t_h)}
                        title={`${p.t_h}h — ${on ? 'esconder' : 'mostrar'}`}
                        style={{
                          fontSize: 9, padding: '2px 5px', borderRadius: 3,
                          fontFamily: 'var(--font-mono)', cursor: 'pointer',
                          border: `1px solid ${color}`,
                          background: on ? color : 'transparent',
                          color: on ? '#0d1410' : color,
                          opacity: on ? 1 : 0.6,
                        }}>
                        {p.t_h}h
                      </button>
                    )
                  })}
                </div>
              </div>
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
              {[1, 2, 3, 6, 12, 24].map(h => (
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

        {result && result.weather_hourly?.length > 0 && (
          <Meteogram points={result.weather_hourly} />
        )}

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
              <td style={{ padding: '6px 8px', color: 'var(--warn)' }}>{fmt(p.ros_max_m_min, 1, 'm/min')}</td>
              <td style={{ padding: '6px 8px', color: 'var(--warn)' }}>{fmt(p.fli_max_kw_m, 0, 'kW/m')}</td>
              <td style={{ padding: '6px 8px', color: 'var(--warn)' }}>{fmt(p.flame_max_m, 1, 'm')}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ fontSize: 9, color: 'var(--dim)', marginTop: 4, fontFamily: 'var(--font-mono)' }}>
        * ROS/FLI/Chama máx entre os vértices activos do perímetro nesse instante
      </div>
    </div>
  )
}

const METEO_TICK = { fontFamily: 'var(--font-mono)', fontSize: 9, fill: 'var(--dim)' }

function MeteoTooltip({ active, payload, label, unit }) {
  if (!active || !payload?.length) return null
  return (
    <div style={{
      background: 'var(--surface, var(--bg2))', border: '1px solid var(--border)',
      borderRadius: 4, padding: '4px 8px', fontFamily: 'var(--font-mono)', fontSize: 10,
    }}>
      <div style={{ color: 'var(--muted)' }}>t={label}h</div>
      <div style={{ color: payload[0].color }}>{fmt(payload[0].value, 1, unit)}</div>
    </div>
  )
}

function MeteoRow({ points, dataKey, label, unit, color, domain }) {
  return (
    <div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)', marginBottom: 2 }}>
        {label.toUpperCase()}
      </div>
      <ResponsiveContainer width="100%" height={70}>
        <LineChart data={points} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="2 3" vertical={false} />
          <XAxis dataKey="t_h" tick={METEO_TICK} axisLine={{ stroke: 'var(--border)' }} tickLine={false} />
          <YAxis width={30} domain={domain} tick={METEO_TICK} axisLine={false} tickLine={false} />
          <Tooltip content={<MeteoTooltip unit={unit} />} />
          <Line type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2}
            dot={{ r: 2, fill: color, strokeWidth: 0 }} activeDot={{ r: 4 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function WindDirectionRow({ points }) {
  return (
    <div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)', marginBottom: 4 }}>
        DIREÇÃO DO VENTO
      </div>
      <div style={{ display: 'flex', gap: 2, overflowX: 'auto', paddingBottom: 2 }}>
        {points.map(p => (
          <div key={p.t_h} title={`t=${p.t_h}h — ${windDirText(p.wind_direction_deg)} (${fmt(p.wind_direction_deg, 0)}°)`}
            style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2,
              flex: '0 0 auto', width: 28,
            }}>
            <svg width="14" height="14" viewBox="0 0 14 14"
              style={{ transform: `rotate(${p.wind_direction_deg}deg)` }}>
              <path d="M7 1 L11 9 L7 6.5 L3 9 Z" fill="var(--p1)" />
            </svg>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--dim)' }}>
              {p.t_h}h
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function Meteogram({ points }) {
  return (
    <div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)', marginBottom: 6 }}>
        METEOGRAMA — OPEN-METEO
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <MeteoRow points={points} dataKey="temperature_c" label="Temperatura °C" unit="°C" color="var(--danger)" />
        <MeteoRow points={points} dataKey="relative_humidity_pct" label="Humidade relativa %" unit="%" color="var(--meteo-humidity)" domain={[0, 100]} />
        <MeteoRow points={points} dataKey="wind_speed_ms" label="Vel. vento m/s" unit="m/s" color="var(--p1)" domain={[0, 'dataMax']} />
        <WindDirectionRow points={points} />
      </div>
    </div>
  )
}

function _renderLayers(map, result, layer, opacity, visiblePerimeters) {
  const perimIds = result.perimeters.flatMap(({ t_h }) => [`perim-${t_h}h-fill`, `perim-${t_h}h-line`]);
  ['sim-pixels-fill', 'sim-pixels-outline', ...perimIds]
    .forEach(id => { try { map.removeLayer(id) } catch {} });
  ['sim-pixels', ...result.perimeters.map(({ t_h }) => `perim-${t_h}h`)]
    .forEach(id => { try { map.removeSource(id) } catch {} })

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

  const maxTH = Math.max(...result.perimeters.map(p => p.t_h))
  result.perimeters.forEach(({ t_h, geojson }, i) => {
    if (visiblePerimeters && !visiblePerimeters.has(t_h)) return
    const style = _perimStyle(i, result.perimeters.length)
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
        'line-width': t_h === maxTH ? 2 : 1,
      },
    })
  })
}
