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
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ flexShrink: 0 }}>
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
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ flexShrink: 0 }}>
      <line x1={cx} y1={cy} x2={tx} y2={ty} stroke={color} strokeWidth="1.3" />
      {elems}
    </svg>
  )
}

const RESULTS_HEADERS = ['Hora', 'Temp (°C)', 'HR (%)', 'Vento (km/h)', 'Rajada (km/h)', 'Área (ha)', 'ROS máx', 'FLI máx', 'Chama máx']

function WindCell({ dir, speedKmh, color }) {
  if (speedKmh == null) return '—'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}
      title={`${windDirText(dir)} (${fmt(dir, 0)}°) · ${fmt(speedKmh, 0)} km/h`}>
      <WindBarb dir={dir} speedKmh={speedKmh} color={color} size={22} />
      <span style={{ color }}>{fmt(speedKmh, 0)}</span>
    </div>
  )
}

export function ResultsTable({ perimeters, weatherHourly = [] }) {
  const wxByHour = new Map(weatherHourly.map(w => [w.t_h, w]))
  return (
    <div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)', marginBottom: 6 }}>
        RESULTADOS DA SIMULAÇÃO
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)' }}>
            {RESULTS_HEADERS.map(h => (
              <th key={h} style={{ padding: '4px 8px', textAlign: 'left', color: 'var(--muted)', fontWeight: 400, fontSize: 9 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {perimeters.map(p => {
            const wx = wxByHour.get(p.t_h)
            const spdKmh = wx ? msToKmh(wx.wind_speed_ms) : null
            const gustKmh = wx?.wind_gust_ms != null ? msToKmh(wx.wind_gust_ms) : null
            return (
              <tr key={p.t_h} style={{ borderBottom: '1px solid rgba(37,52,39,.3)' }}>
                <td style={{ padding: '6px 8px', color: 'var(--accent2)', fontWeight: 700 }}>t={p.t_h}h</td>
                <td style={{ padding: '6px 8px', color: 'var(--danger)' }}>{wx ? fmt(wx.temperature_c, 0) : '—'}</td>
                <td style={{ padding: '6px 8px', color: 'var(--meteo-humidity)' }}>{wx ? fmt(wx.relative_humidity_pct, 0) : '—'}</td>
                <td style={{ padding: '6px 8px' }}>
                  <WindCell dir={wx?.wind_direction_deg} speedKmh={spdKmh} color="var(--p1)" />
                </td>
                <td style={{ padding: '6px 8px' }}>
                  <WindCell dir={wx?.wind_direction_deg} speedKmh={gustKmh} color="var(--meteo-gust)" />
                </td>
                <td style={{ padding: '6px 8px' }}>{fmt(p.area_ha, 0)}</td>
                <td style={{ padding: '6px 8px', color: 'var(--warn)' }}>{fmt(p.ros_max_m_min, 1, 'm/min')}</td>
                <td style={{ padding: '6px 8px', color: 'var(--warn)' }}>{fmt(p.fli_max_kw_m, 0, 'kW/m')}</td>
                <td style={{ padding: '6px 8px', color: 'var(--warn)' }}>{fmt(p.flame_max_m, 1, 'm')}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <div style={{ fontSize: 9, color: 'var(--dim)', marginTop: 4, fontFamily: 'var(--font-mono)' }}>
        * ROS/FLI/Chama máx entre os vértices activos do perímetro nesse instante · barbelas de vento/rajada usam a mesma direção (Open-Meteo não dá direção separada para a rajada)
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
