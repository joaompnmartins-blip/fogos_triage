import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip,
} from 'recharts'
import { fmt, windDirText } from '../constants'
import { msToKmh } from './SimulationMapLayers'

// Painéis de apresentação partilhados entre SimulacaoView (ligada a
// ocorrências) e SimuladorLivreView (ignição livre) — mesmo formato de
// resultado (SimulationResultDetail), só a origem do job difere.

export function Legend({ stops, label }) {
  return (
    <div className="map-overlay-panel" style={{
      borderRadius: 4, padding: '6px 8px',
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

export function ResultsTable({ perimeters }) {
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

const METEO_TICK = { fontFamily: 'var(--font-mono)', fontSize: 10, fill: 'var(--dim)' }

function _hourLabel(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}h`
}

function MeteoTooltip({ active, payload, unit, formatValue }) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  const value = formatValue ? formatValue(payload[0].value) : fmt(payload[0].value, 1, unit)
  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--border)',
      borderRadius: 4, padding: '4px 8px', fontFamily: 'var(--font-mono)', fontSize: 10,
    }}>
      <div style={{ color: 'var(--muted)' }}>{_hourLabel(p.timestamp)} (t+{p.t_h}h)</div>
      <div style={{ color: payload[0].color, fontWeight: 700 }}>{value}</div>
    </div>
  )
}

function MeteoRow({ points, dataKey, label, unit, color, domain, yTicks, yTickFormatter, tooltipFormatter }) {
  return (
    <div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text)',
        marginBottom: 2, display: 'flex', alignItems: 'center', gap: 6,
      }}>
        <span style={{ display: 'inline-block', width: 12, height: 2, background: color }} />
        {label}
      </div>
      <ResponsiveContainer width="100%" height={130}>
        <LineChart data={points} margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="2 3" />
          <XAxis dataKey="t_h" tick={METEO_TICK} axisLine={{ stroke: 'var(--border)' }} tickLine={false}
            tickFormatter={t_h => _hourLabel(points.find(p => p.t_h === t_h)?.timestamp)} />
          <YAxis width={34} domain={domain} ticks={yTicks} tickFormatter={yTickFormatter}
            tick={METEO_TICK} axisLine={false} tickLine={false} />
          <Tooltip content={<MeteoTooltip unit={unit} formatValue={tooltipFormatter} />} />
          <Line type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2}
            dot={{ r: 2, fill: color, strokeWidth: 0 }} activeDot={{ r: 4 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

// Decompõe uma velocidade (km/h) em elementos de barbela meteorológica —
// convenção padrão: bandeira=50, traço longo=10, traço curto=5 km/h,
// arredondado aos 5 km/h mais próximos (calmo se <5).
function decomposeWindBarb(speedKmh) {
  let s = Math.round(speedKmh / 5) * 5
  const flags = Math.floor(s / 50); s -= flags * 50
  const longs = Math.floor(s / 10); s -= longs * 10
  const shorts = Math.floor(s / 5)
  return { flags, longs, shorts, calm: Math.round(speedKmh / 5) * 5 < 5 }
}

// Barbela de vento — haste aponta para de onde vem o vento (convenção
// meteorológica padrão), traços/bandeiras no lado esquerdo da haste a
// partir da cauda. Calmo (<5 km/h) → círculo aberto, sem haste.
function WindBarb({ dir, speedKmh, color, size = 32 }) {
  if (dir == null || speedKmh == null) return null
  const dec = decomposeWindBarb(speedKmh)
  const cx = size / 2, cy = size / 2

  if (dec.calm) {
    return (
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={cx} cy={cy} r={size * 0.09} fill="none" stroke={color} strokeWidth="1.4" />
      </svg>
    )
  }

  const SHAFT = size * 0.42, BARB = size * 0.17, STEP = size * 0.115
  const rad = (dir * Math.PI) / 180
  const ux = Math.sin(rad), uy = -Math.cos(rad)
  const px = uy, py = -ux // perpendicular (lado esquerdo da haste)
  const at = t => [cx + ux * t, cy + uy * t]
  const [tx, ty] = at(SHAFT)

  const elems = []
  let pos = SHAFT
  for (let f = 0; f < dec.flags; f++) {
    const [bx, by] = at(pos), [ex, ey] = at(pos - STEP * 1.4)
    elems.push(<polygon key={`f${f}`} points={`${bx},${by} ${bx + px * BARB},${by + py * BARB} ${ex},${ey}`} fill={color} />)
    pos -= STEP * 1.6
  }
  for (let l = 0; l < dec.longs; l++) {
    const [bx, by] = at(pos)
    elems.push(<line key={`l${l}`} x1={bx} y1={by} x2={bx + px * BARB} y2={by + py * BARB} stroke={color} strokeWidth="1.3" />)
    pos -= STEP
  }
  if (dec.shorts) {
    if (dec.flags === 0 && dec.longs === 0) pos -= STEP
    const [bx, by] = at(pos)
    elems.push(<line key="s" x1={bx} y1={by} x2={bx + px * BARB * 0.5} y2={by + py * BARB * 0.5} stroke={color} strokeWidth="1.3" />)
  }

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <line x1={cx} y1={cy} x2={tx} y2={ty} stroke={color} strokeWidth="1.3" />
      {elems}
    </svg>
  )
}

function WindDirectionRow({ points }) {
  return (
    <div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text)',
        marginBottom: 4, display: 'flex', alignItems: 'center', gap: 6,
      }}>
        <span style={{ display: 'inline-block', width: 12, height: 2, background: 'var(--p1)' }} />
        Direção e velocidade do vento (10m, barbelas km/h)
      </div>
      <div style={{ display: 'flex', gap: 3, overflowX: 'auto', paddingBottom: 2 }}>
        {points.map(p => {
          const spdKmh = msToKmh(p.wind_speed_ms)
          const gustKmh = p.wind_gust_ms != null ? msToKmh(p.wind_gust_ms) : null
          return (
            <div key={p.t_h}
              title={`${_hourLabel(p.timestamp)} (t+${p.t_h}h) — ${windDirText(p.wind_direction_deg)} (${fmt(p.wind_direction_deg, 0)}°) · ${fmt(spdKmh, 0)} km/h${gustKmh != null ? ` · rajada ${fmt(gustKmh, 0)} km/h` : ''}`}
              style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1,
                flex: '0 0 auto', width: 34,
              }}>
              <WindBarb dir={p.wind_direction_deg} speedKmh={spdKmh} color="var(--p1)" />
              {gustKmh != null && (
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 7.5, color: 'var(--meteo-gust)' }}>
                  {fmt(gustKmh, 0)}
                </span>
              )}
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--dim)' }}>
                {_hourLabel(p.timestamp)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function WindSpeedTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--border)',
      borderRadius: 4, padding: '4px 8px', fontFamily: 'var(--font-mono)', fontSize: 10,
    }}>
      <div style={{ color: 'var(--muted)' }}>{_hourLabel(p.timestamp)} (t+{p.t_h}h)</div>
      <div style={{ color: 'var(--p1)', fontWeight: 700 }}>{fmt(p.wind_speed_kmh, 0, 'km/h')}</div>
      {p.wind_gust_kmh != null && (
        <div style={{ color: 'var(--meteo-gust)', fontWeight: 700 }}>rajada {fmt(p.wind_gust_kmh, 0, 'km/h')}</div>
      )}
    </div>
  )
}

function WindSpeedRow({ points }) {
  const data = points.map(p => ({
    ...p,
    wind_speed_kmh: msToKmh(p.wind_speed_ms),
    wind_gust_kmh: p.wind_gust_ms != null ? msToKmh(p.wind_gust_ms) : null,
  }))
  const hasGust = data.some(d => d.wind_gust_kmh != null)
  return (
    <div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text)',
        marginBottom: 2, display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ display: 'inline-block', width: 12, height: 2, background: 'var(--p1)' }} />
          Velocidade (10m, km/h)
        </span>
        {hasGust && (
          <span style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--meteo-gust)' }}>
            <span style={{ display: 'inline-block', width: 12, height: 2, background: 'var(--meteo-gust)', borderTop: '2px dashed var(--meteo-gust)' }} />
            Rajada (km/h)
          </span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={130}>
        <LineChart data={data} margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="2 3" />
          <XAxis dataKey="t_h" tick={METEO_TICK} axisLine={{ stroke: 'var(--border)' }} tickLine={false}
            tickFormatter={t_h => _hourLabel(data.find(p => p.t_h === t_h)?.timestamp)} />
          <YAxis width={34} domain={[0, 'dataMax']} tick={METEO_TICK} axisLine={false} tickLine={false} />
          <Tooltip content={<WindSpeedTooltip />} />
          {hasGust && (
            <Line type="monotone" dataKey="wind_gust_kmh" stroke="var(--meteo-gust)" strokeWidth={1.6}
              strokeDasharray="4 3" dot={{ r: 1.8, fill: 'var(--meteo-gust)', strokeWidth: 0 }}
              activeDot={{ r: 4 }} isAnimationActive={false} />
          )}
          <Line type="monotone" dataKey="wind_speed_kmh" stroke="var(--p1)" strokeWidth={2}
            dot={{ r: 2, fill: 'var(--p1)', strokeWidth: 0 }} activeDot={{ r: 4 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export function Meteogram({ points }) {
  return (
    <div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)', marginBottom: 6 }}>
        METEOGRAMA — OPEN-METEO
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <MeteoRow points={points} dataKey="temperature_c" label="Temperatura (2m, °C)" unit="°C" color="var(--danger)" />
        <MeteoRow points={points} dataKey="relative_humidity_pct" label="Humidade relativa (2m, %)" unit="%" color="var(--meteo-humidity)" domain={[0, 100]} />
        <WindSpeedRow points={points} />
        <WindDirectionRow points={points} />
      </div>
    </div>
  )
}

export function DurationSelect({ value, onChange, options = [1, 2, 3, 6, 12, 24] }) {
  return (
    <select className="form-input" value={value}
      style={{ fontSize: 12, padding: '5px 8px' }}
      onChange={e => onChange(parseInt(e.target.value, 10))}>
      {options.map(h => (
        <option key={h} value={h}>{h}h</option>
      ))}
    </select>
  )
}
