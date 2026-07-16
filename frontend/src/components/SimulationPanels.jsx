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
      background: 'var(--bg2)', border: '1px solid var(--border)',
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

function WindDirectionRow({ points }) {
  return (
    <div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text)',
        marginBottom: 4, display: 'flex', alignItems: 'center', gap: 6,
      }}>
        <span style={{ display: 'inline-block', width: 12, height: 2, background: 'var(--p1)' }} />
        Direção do vento (10m)
      </div>
      <div style={{ display: 'flex', gap: 3, overflowX: 'auto', paddingBottom: 2 }}>
        {points.map(p => (
          <div key={p.t_h}
            title={`${_hourLabel(p.timestamp)} (t+${p.t_h}h) — ${windDirText(p.wind_direction_deg)} (${fmt(p.wind_direction_deg, 0)}°)`}
            style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2,
              flex: '0 0 auto', width: 30,
            }}>
            <svg width="16" height="16" viewBox="0 0 14 14"
              style={{ transform: `rotate(${p.wind_direction_deg}deg)` }}>
              <path d="M7 1 L11 9 L7 6.5 L3 9 Z" fill="var(--p1)" />
            </svg>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--dim)' }}>
              {_hourLabel(p.timestamp)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function Meteogram({ points }) {
  const withKmh = points.map(p => ({ ...p, wind_speed_kmh: msToKmh(p.wind_speed_ms) }))
  return (
    <div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)', marginBottom: 6 }}>
        METEOGRAMA — OPEN-METEO
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <MeteoRow points={points} dataKey="temperature_c" label="Temperatura (2m, °C)" unit="°C" color="var(--danger)" />
        <MeteoRow points={points} dataKey="relative_humidity_pct" label="Humidade relativa (2m, %)" unit="%" color="var(--meteo-humidity)" domain={[0, 100]} />
        <MeteoRow points={withKmh} dataKey="wind_speed_kmh" label="Velocidade do vento (10m, km/h)" unit="km/h" color="var(--p1)" domain={[0, 'dataMax']} />
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
