import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { fetchFireDetail } from '../api'
import { SeverityBadge, FireTypeBadge } from '../components/SeverityBadge'
import { fmt, fmtDateTime, fmtDuration, windDirText, SEVERITY_COLOR, SEVERITY_LABEL } from '../constants'

function InfoRow({ label, value, unit, color }) {
  return (
    <div className="info-row">
      <span className="info-label">{label}</span>
      <span className="info-val" style={color ? { color } : {}}>
        {value ?? '—'}{unit && value != null ? ` ${unit}` : ''}
      </span>
    </div>
  )
}

function ScenarioCard({ scenario }) {
  if (!scenario) return null
  const labels = { central: 'Vento Geral', gusts: 'Vento Rajadas' }
  const labelColor = {
    gusts: 'var(--danger)',
    central: 'var(--muted)',
  }[scenario.scenario] || 'var(--muted)'

  return (
    <div className={`scenario-card ${scenario.scenario}`}>
      <div className="scenario-label" style={{ color: labelColor }}>
        {labels[scenario.scenario] || scenario.scenario}
      </div>

      <div className="scenario-metric">
        <div className="scenario-metric-label">ROS</div>
        <div className="scenario-metric-val">
          {fmt(scenario.ros_km_per_h, 1)}
          <span style={{ fontSize: 13, color: 'var(--muted)', marginLeft: 4 }}>km/h</span>
        </div>
      </div>

      <div className="scenario-metric">
        <div className="scenario-metric-label">Intensidade</div>
        <div className="scenario-metric-val" style={{ fontSize: 20 }}>
          {fmt(scenario.fireline_intensity_kw_m, 0)}
          <span style={{ fontSize: 12, color: 'var(--muted)', marginLeft: 4 }}>kW/m</span>
        </div>
      </div>

      <div className="scenario-metric">
        <div className="scenario-metric-label">Chama</div>
        <div className="scenario-metric-val" style={{ fontSize: 20 }}>
          {fmt(scenario.flame_length_m, 1)}
          <span style={{ fontSize: 12, color: 'var(--muted)', marginLeft: 4 }}>m</span>
        </div>
      </div>

      <div className="scenario-metric">
        <div className="scenario-metric-label">Vento ef.</div>
        <div className="scenario-metric-val" style={{ fontSize: 18 }}>
          {fmt(scenario.effective_wind_ms, 1)}
          <span style={{ fontSize: 12, color: 'var(--muted)', marginLeft: 4 }}>m/s</span>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
        <FireTypeBadge type={scenario.fire_type} />
        {scenario.severity_category != null && (
          <span
            className="badge"
            style={{
              background: 'transparent',
              color: SEVERITY_COLOR[scenario.severity_category] || 'var(--muted)',
              border: `1px solid ${SEVERITY_COLOR[scenario.severity_category] || 'var(--border2)'}40`,
              fontSize: 9,
            }}
          >
            {scenario.severity_category} {SEVERITY_LABEL[scenario.severity_category]}
          </span>
        )}
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

  if (loading) return <div className="state-center" style={{ height: '100%' }}>A carregar…</div>
  if (error) return (
    <div className="state-center" style={{ height: '100%', color: 'var(--danger)', gap: 8 }}>
      <div>Erro ao carregar ocorrência</div>
      <div style={{ fontSize: 11, opacity: 0.7 }}>{error}</div>
      <button className="btn btn-ghost" onClick={() => navigate('/lista')}>← Voltar</button>
    </div>
  )
  if (!fire) return null

  const t = fire.triage
  const wx = t?.weather
  const terrain = t?.terrain
  const priorityColor = t ? SEVERITY_COLOR[t.priority_class] : 'var(--muted)'
  const scenarios = t?.scenarios || []
  const central = scenarios.find(s => s.scenario === 'central')
  const gusts = scenarios.find(s => s.scenario === 'gusts')

  return (
    <div className="content-scroll">
      {/* Breadcrumb */}
      <div className="breadcrumb">
        <Link to="/lista">Ocorrências</Link>
        <span className="sep">›</span>
        <span>{[fire.municipality, fire.district].filter(Boolean).join(', ')}</span>
        {t && (
          <>
            <span className="sep">·</span>
            <Link to={`/fogo/${fireId}/historico`} style={{ color: 'var(--accent2)' }}>
              Ver histórico
            </Link>
            <span className="sep">·</span>
            <Link to={`/fogo/${fireId}/simulacao`} style={{ color: 'var(--p1)' }}>
              ▶ Simular
            </Link>
          </>
        )}
      </div>

      {/* Hero */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 24, flexWrap: 'wrap' }}>
        {t && <SeverityBadge category={t.priority_class} size="lg" />}
        {central && <FireTypeBadge type={central.fire_type} />}
        {fire.is_important && <span className="badge badge-danger">IMPORTANTE</span>}
        <div style={{ flex: 1 }}>
          <div style={{ fontFamily: 'var(--font-cond)', fontSize: 26, fontWeight: 800, letterSpacing: '.03em', textTransform: 'uppercase', lineHeight: 1.1 }}>
            {[fire.municipality, fire.district].filter(Boolean).join(' · ')}
          </div>
          {(fire.parish || fire.locality) && (
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
              {[fire.parish, fire.locality].filter(Boolean).join(', ')}
            </div>
          )}
        </div>
      </div>

      {/* Scenarios */}
      {t ? (
        <>
          <div className="section-hdr">
            <div className="section-title">Cenários de Comportamento</div>
          </div>
          <div className="scenario-grid">
            <ScenarioCard scenario={central} />
            <ScenarioCard scenario={gusts} />
          </div>
        </>
      ) : (
        <div style={{ padding: '16px 0 24px', color: 'var(--muted)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
          Ocorrência sem triagem — natureza não relevante ou ainda não processada.
        </div>
      )}

      {/* Detail grid */}
      <div className="detail-grid">
        {/* Ocorrência */}
        <div className="detail-card">
          <div className="detail-card-title">Ocorrência</div>
          <InfoRow label="Estado" value={fire.status_name} />
          <InfoRow label="Início" value={fmtDateTime(fire.started_at)} />
          <InfoRow label="Duração" value={fmtDuration(fire.started_at)} />
          <InfoRow label="Operacionais" value={fire.operatives} />
          <InfoRow label="Veículos" value={fire.vehicles} />
          {fire.aerial > 0 && <InfoRow label="Aéreos" value={fire.aerial} />}
          {fire.heli_fight > 0 && <InfoRow label="Heli-combate" value={fire.heli_fight} />}
          {t && <InfoRow label="Intensidade (central)" value={fmt(t.priority_score, 0)} unit="kW/m" color={priorityColor} />}
          {t && <InfoRow label="Combustível" value={t.fuel_model_code} />}
        </div>

        {/* Terreno */}
        {terrain && (
          <div className="detail-card">
            <div className="detail-card-title">Terreno</div>
            <InfoRow label="Altitude" value={fmt(terrain.elevation_m, 0)} unit="m" />
            <InfoRow label="Declive" value={fmt(terrain.slope_degrees, 1)} unit="°" />
            <InfoRow label="Aspecto" value={fmt(terrain.aspect_degrees, 0)} unit="°" />
            <InfoRow label="Combustível" value={terrain.fuel_model_code} />
            {terrain.stand_height_m != null && (
              <InfoRow label="Alt. vegetal" value={fmt(terrain.stand_height_m, 1)} unit="m" />
            )}
            {terrain.canopy_cover_pct != null && (
              <InfoRow label="Coberto" value={fmt(terrain.canopy_cover_pct, 0)} unit="%" />
            )}
          </div>
        )}

        {/* Meteorologia */}
        {wx && (
          <div className="detail-card">
            <div className="detail-card-title">
              Meteorologia
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--dim)', marginLeft: 8, textTransform: 'none', letterSpacing: 0 }}>
                {wx.source === 'open_meteo' ? 'Open-Meteo' : wx.source === 'ipma_fogos' ? `IPMA${wx.station_location ? ` · ${wx.station_location}` : ''}` : wx.source}
              </span>
            </div>
            <InfoRow label="Temperatura" value={fmt(wx.temperature_c, 1)} unit="°C" />
            <InfoRow label="Humidade relativa" value={fmt(wx.relative_humidity_pct, 0)} unit="%" />
            <InfoRow
              label="Velocidade vento"
              value={wx.wind_speed_kmh != null ? fmt(wx.wind_speed_kmh, 1) : wx.wind_speed_ms != null ? fmt(wx.wind_speed_ms * 3.6, 1) : null}
              unit="km/h"
            />
            <InfoRow label="Direção vento" value={windDirText(wx.wind_direction_deg)} />
            {wx.precipitation_mm_24h != null && (
              <InfoRow label="Precipitação 24h" value={fmt(wx.precipitation_mm_24h, 1)} unit="mm" />
            )}
            {t?.wind_midflame_ms != null && (
              <InfoRow label="Vento midflame" value={fmt(t.wind_midflame_ms * 3.6, 1)} unit="km/h" />
            )}
            {wx.fire_weather_index != null && (
              <InfoRow label="FWI" value={fmt(wx.fire_weather_index, 1)} color="var(--warn)" />
            )}
          </div>
        )}

        {/* Humidades dos combustíveis */}
        {t && (t.fuel_moisture_1h_pct != null || t.fuel_moisture_live_h_pct != null) && (
          <div className="detail-card">
            <div className="detail-card-title">Humidade dos Combustíveis</div>
            {t.fuel_moisture_1h_pct != null && (
              <InfoRow label="Morto 1h" value={fmt(t.fuel_moisture_1h_pct, 1)} unit="%" />
            )}
            {t.fuel_moisture_10h_pct != null && (
              <InfoRow label="Morto 10h" value={fmt(t.fuel_moisture_10h_pct, 1)} unit="%" />
            )}
            {t.fuel_moisture_100h_pct != null && (
              <InfoRow label="Morto 100h" value={fmt(t.fuel_moisture_100h_pct, 1)} unit="%" />
            )}
            {t.fuel_moisture_live_h_pct != null && (
              <InfoRow
                label="Vivo herbáceo"
                value={fmt(t.fuel_moisture_live_h_pct, 0)}
                unit="%"
                color={t.fuel_moisture_live_h_pct < 80 ? 'var(--danger)' : t.fuel_moisture_live_h_pct < 120 ? 'var(--warn)' : undefined}
              />
            )}
            {t.fuel_moisture_live_w_pct != null && (
              <InfoRow
                label="Vivo lenhoso"
                value={fmt(t.fuel_moisture_live_w_pct, 0)}
                unit="%"
                color={t.fuel_moisture_live_w_pct < 80 ? 'var(--danger)' : t.fuel_moisture_live_w_pct < 120 ? 'var(--warn)' : undefined}
              />
            )}
          </div>
        )}

        {/* Parâmetros avançados */}
        {central && (
          <div className="detail-card">
            <div className="detail-card-title">Parâmetros avançados</div>
            <InfoRow label="Calor por área" value={fmt(central.heat_per_unit_area_kj_m2, 0)} unit="kJ/m²" />
            <InfoRow label="Int. de reação" value={fmt(central.reaction_intensity_kw_m2, 0)} unit="kW/m²" />
            <InfoRow label="Dir. de propagação" value={fmt(central.direction_max_spread_deg, 0)} unit="°" />
            <InfoRow label="Vento ef." value={fmt(central.effective_wind_ms, 1)} unit="m/s" />
          </div>
        )}

        {/* Notas */}
        {t?.notes && t.notes.length > 0 && (
          <div className="detail-card">
            <div className="detail-card-title">Notas</div>
            {t.notes.map((note, i) => (
              <div key={i} style={{ display: 'flex', gap: 6, padding: '4px 0', borderBottom: '1px solid rgba(37,52,39,.5)' }}>
                <span style={{ color: 'var(--warn)', fontSize: 10, flexShrink: 0 }}>▸</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)' }}>{note}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer meta */}
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--dim)', borderTop: '1px solid var(--border)', paddingTop: 12, marginTop: 8 }}>
        ID: {fire.fire_id}
        {fire.sado_id && ` · SADO: ${fire.sado_id}`}
        {fire.dico && ` · DICO: ${fire.dico}`}
        {t && ` · Triagem: ${fmtDateTime(t.computed_at)}`}
      </div>
    </div>
  )
}
