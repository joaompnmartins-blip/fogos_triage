import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { fetchFireDetail } from '../api'
import { PriorityBadge, FireTypeBadge } from '../components/PriorityBadge'
import { fmt, fmtDateTime, fmtDuration, windDirText, TACTIC_LABEL, PRIORITY_COLOR } from '../constants'

function DataCell({ label, value, unit, color }) {
  return (
    <div className="data-cell">
      <div className="data-label">{label}</div>
      <div className="data-value" style={color ? { color } : {}}>
        {value ?? '—'}
        {unit && value != null && (
          <span className="data-value unit">{unit}</span>
        )}
      </div>
    </div>
  )
}

function SectionCard({ title, children }) {
  return (
    <div className="card">
      <div className="card-header">{title}</div>
      <div className="card-body">{children}</div>
    </div>
  )
}

function ScenarioCard({ scenario }) {
  if (!scenario) return null
  const isWorst = scenario.scenario === 'worst'
  const isBest = scenario.scenario === 'best'
  const scenarioLabel = { central: 'Central', worst: 'Pior caso', best: 'Melhor caso' }
  const tacticColor = {
    direct_attack_manual: 'var(--success)',
    direct_attack_difficult: 'var(--warn)',
    indirect_attack_machinery: 'var(--p1)',
    indirect_attack_only: 'var(--danger)',
  }

  return (
    <div className={`scenario-card ${scenario.scenario}`}>
      <div className="scenario-label" style={{ color: isWorst ? 'var(--danger)' : isBest ? 'var(--accent2)' : 'var(--muted)' }}>
        {scenarioLabel[scenario.scenario] || scenario.scenario}
      </div>
      <div className="data-grid data-grid-2" style={{ gap: 10, marginBottom: 12 }}>
        <DataCell label="ROS" value={fmt(scenario.ros_km_per_h, 1)} unit="km/h" />
        <DataCell label="Intensidade" value={fmt(scenario.fireline_intensity_kw_m, 0)} unit="kW/m" />
        <DataCell label="Chama" value={fmt(scenario.flame_length_m, 1)} unit="m" />
        <DataCell label="Vento ef." value={fmt(scenario.effective_wind_ms, 1)} unit="m/s" />
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <FireTypeBadge type={scenario.fire_type} />
        <span
          className="badge"
          style={{
            background: 'transparent',
            color: tacticColor[scenario.tactic_category] || 'var(--muted)',
            border: `1px solid ${tacticColor[scenario.tactic_category] || 'var(--border2)'}40`,
            fontSize: 10,
          }}
        >
          {TACTIC_LABEL[scenario.tactic_category] || scenario.tactic_category}
        </span>
      </div>
    </div>
  )
}

export default function DetalheView({ apiKey }) {
  const { fireId } = useParams()
  const navigate = useNavigate()
  const [fire, setFire] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchFireDetail(apiKey, fireId)
      .then(setFire)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [apiKey, fireId])

  if (loading) return <div className="state-center">A carregar…</div>
  if (error) return (
    <div className="state-center" style={{ color: 'var(--danger)', gap: 8 }}>
      <div>Erro ao carregar ocorrência</div>
      <div style={{ fontSize: 11, opacity: 0.7 }}>{error}</div>
      <button className="btn-ghost" onClick={() => navigate('/lista')}>← Voltar</button>
    </div>
  )
  if (!fire) return null

  const t = fire.triage
  const wx = t?.weather
  const terrain = t?.terrain

  const priorityColor = t ? PRIORITY_COLOR[t.priority_class] : 'var(--muted)'

  const scenarios = t?.scenarios || []
  const central = scenarios.find(s => s.scenario === 'central')
  const worst = scenarios.find(s => s.scenario === 'worst')
  const best = scenarios.find(s => s.scenario === 'best')

  return (
    <div className="detail-layout">
      {/* Sidebar */}
      <aside className="detail-sidebar">
        {/* Hero card */}
        <div className="detail-hero">
          <div className="detail-hero-top">
            {t && <PriorityBadge priority={t.priority_class} size="lg" />}
            {central && <FireTypeBadge type={central.fire_type} />}
          </div>
          <div className="detail-hero-title">
            {fire.municipality}, {fire.district}
          </div>
          <div className="detail-hero-sub">
            {[fire.parish, fire.locality].filter(Boolean).join(' · ')}
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 4 }}>
            <span className="badge" style={{ background: 'var(--surface3)', color: 'var(--muted)', border: '1px solid var(--border)' }}>
              {fire.status_name}
            </span>
            {fire.is_important && (
              <span className="badge" style={{ background: '#e0505018', color: 'var(--danger)', border: '1px solid #e0505030' }}>
                IMPORTANTE
              </span>
            )}
          </div>
          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 8, marginTop: 4 }}>
            <div className="data-grid data-grid-2" style={{ gap: 8 }}>
              <DataCell label="Início" value={fmtDateTime(fire.started_at)} />
              <DataCell label="Duração" value={fmtDuration(fire.started_at)} />
              <DataCell label="Operacionais" value={fire.operatives} />
              <DataCell label="Veículos" value={fire.vehicles} />
              {fire.aerial > 0 && <DataCell label="Aéreos" value={fire.aerial} />}
              {fire.heli_fight > 0 && <DataCell label="Helicópteros" value={fire.heli_fight} />}
            </div>
          </div>
          {t && (
            <div style={{ borderTop: '1px solid var(--border)', paddingTop: 8, marginTop: 4 }}>
              <div className="data-grid data-grid-2" style={{ gap: 8 }}>
                <DataCell label="Score" value={fmt(t.priority_score, 0)} color={priorityColor} />
                <DataCell label="Comb." value={t.fuel_model_code} />
              </div>
            </div>
          )}
          {t && (
            <div style={{ marginTop: 4 }}>
              <Link
                to={`/fogo/${fireId}/historico`}
                style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent2)' }}
              >
                Ver histórico →
              </Link>
            </div>
          )}
        </div>

        {/* Terrain */}
        {terrain && (
          <SectionCard title="Terreno">
            <div className="data-grid data-grid-2" style={{ gap: 10 }}>
              <DataCell label="Altitude" value={fmt(terrain.elevation_m, 0)} unit="m" />
              <DataCell label="Declive" value={fmt(terrain.slope_degrees, 1)} unit="°" />
              <DataCell label="Aspecto" value={fmt(terrain.aspect_degrees, 0)} unit="°" />
              <DataCell label="Combustível" value={terrain.fuel_model_code} />
              {terrain.stand_height_m != null && (
                <DataCell label="Alt. vegetal" value={fmt(terrain.stand_height_m, 1)} unit="m" />
              )}
              {terrain.canopy_cover_pct != null && (
                <DataCell label="Coberto" value={fmt(terrain.canopy_cover_pct, 0)} unit="%" />
              )}
            </div>
          </SectionCard>
        )}

        {/* Weather */}
        {wx && (
          <SectionCard title="Meteorologia">
            <div className="data-grid data-grid-2" style={{ gap: 10 }}>
              <DataCell label="Temperatura" value={fmt(wx.temperature_c, 1)} unit="°C" />
              <DataCell label="HR" value={fmt(wx.relative_humidity_pct, 0)} unit="%" />
              <DataCell
                label="Vento"
                value={wx.wind_speed_ms != null ? `${fmt(wx.wind_speed_ms, 1)} m/s` : '—'}
              />
              <DataCell label="Direção" value={windDirText(wx.wind_direction_deg)} />
              {t?.wind_midflame_ms != null && (
                <DataCell label="Midflame" value={fmt(t.wind_midflame_ms, 1)} unit="m/s" />
              )}
              {t?.fuel_moisture_1h_pct != null && (
                <DataCell label="Hum. 1h" value={fmt(t.fuel_moisture_1h_pct, 1)} unit="%" />
              )}
              {wx.fire_weather_index != null && (
                <DataCell label="FWI" value={fmt(wx.fire_weather_index, 1)} color="var(--warn)" />
              )}
            </div>
            {wx.source && (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted)', marginTop: 10, borderTop: '1px solid var(--border)', paddingTop: 8 }}>
                Fonte: {wx.source}
              </div>
            )}
          </SectionCard>
        )}

        {/* Notes */}
        {t?.notes && t.notes.length > 0 && (
          <SectionCard title="Notas">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {t.notes.map((note, i) => (
                <div key={i} style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)', display: 'flex', gap: 6 }}>
                  <span style={{ color: 'var(--warn)' }}>▸</span>
                  <span>{note}</span>
                </div>
              ))}
            </div>
          </SectionCard>
        )}
      </aside>

      {/* Main content — scenarios */}
      <main className="detail-main">
        {t ? (
          <>
            <div style={{ fontFamily: 'var(--font-cond)', fontSize: 13, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--muted)' }}>
              Cenários de comportamento
            </div>
            <div className="scenario-grid">
              <ScenarioCard scenario={worst} />
              <ScenarioCard scenario={central} />
              <ScenarioCard scenario={best} />
            </div>

            {/* Heat table */}
            {central && (
              <SectionCard title="Parâmetros avançados (cenário central)">
                <div className="data-grid data-grid-3" style={{ gap: 12 }}>
                  <DataCell label="Calor por área" value={fmt(central.heat_per_unit_area_kj_m2, 0)} unit="kJ/m²" />
                  <DataCell label="Int. reação" value={fmt(central.reaction_intensity_kw_m2, 0)} unit="kW/m²" />
                  <DataCell label="Dir. propagação" value={fmt(central.direction_max_spread_deg, 0)} unit="°" />
                </div>
              </SectionCard>
            )}

            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--dim)', marginTop: 'auto', paddingTop: 16 }}>
              Triagem calculada: {fmtDateTime(t.computed_at)}
            </div>
          </>
        ) : (
          <div className="state-center" style={{ color: 'var(--muted)' }}>
            <div>Ocorrência sem triagem</div>
            <div style={{ fontSize: 11 }}>Natureza não relevante ou ainda não processada</div>
          </div>
        )}

        {/* ID info */}
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--dim)', borderTop: '1px solid var(--border)', paddingTop: 10 }}>
          ID: {fire.fire_id}
          {fire.sado_id && ` · SADO: ${fire.sado_id}`}
          {fire.dico && ` · DICO: ${fire.dico}`}
        </div>
      </main>
    </div>
  )
}
