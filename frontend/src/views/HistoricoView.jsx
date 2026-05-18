import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { fetchFireHistory, fetchFireDetail } from '../api'
import { fmtDateTime } from '../constants'

const TAG_CLASS = {
  created: 'tag-created',
  status: 'tag-status',
  resources: 'tag-resources',
  both: 'tag-both',
}

const CHANGE_LABELS = {
  created: 'CRIADO',
  status: 'ESTADO',
  resources: 'RECURSOS',
  both: 'ESTADO+RECURSOS',
}

function ResourceLine({ item }) {
  const parts = []
  if (item.operatives) parts.push(`${item.operatives} oper.`)
  if (item.vehicles) parts.push(`${item.vehicles} veíc.`)
  if (item.aerial) parts.push(`${item.aerial} aéreos`)
  if (item.heli_fight) parts.push(`${item.heli_fight} heli`)
  if (item.plane_fight) parts.push(`${item.plane_fight} aviões`)
  return <>{parts.join(' · ') || '—'}</>
}

export default function HistoricoView({ apiKey }) {
  const { fireId } = useParams()
  const [history, setHistory] = useState(null)
  const [fire, setFire] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    Promise.all([
      fetchFireHistory(apiKey, fireId),
      fetchFireDetail(apiKey, fireId),
    ])
      .then(([hist, f]) => { setHistory(hist); setFire(f) })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [apiKey, fireId])

  if (loading) return <div className="state-center" style={{ height: '100%' }}>A carregar…</div>
  if (error) return (
    <div className="state-center" style={{ height: '100%', color: 'var(--danger)', gap: 8 }}>
      <div>Erro ao carregar histórico</div>
      <div style={{ fontSize: 11, opacity: 0.7 }}>{error}</div>
    </div>
  )

  const location = fire ? [fire.municipality, fire.district].filter(Boolean).join(', ') : fireId

  let lastDay = null

  return (
    <div className="content-scroll">
      {/* Breadcrumb */}
      <div className="breadcrumb">
        <Link to="/lista">Ocorrências</Link>
        <span className="sep">›</span>
        <Link to={`/fogo/${fireId}`}>{location}</Link>
        <span className="sep">›</span>
        <span>Histórico</span>
      </div>

      <div className="section-hdr">
        <div className="section-title">
          Histórico
          <span>{history?.length ?? 0} eventos</span>
        </div>
      </div>

      {history && history.length === 0 ? (
        <div style={{ color: 'var(--muted)', fontFamily: 'var(--font-mono)', fontSize: 12, padding: '20px 0' }}>
          Sem histórico registado.
        </div>
      ) : (
        <div>
          {(history || []).map((item, idx) => {
            const changeType = item.change_type || 'status'
            const isStatus = changeType === 'status' || changeType === 'both' || changeType === 'created'
            const isResources = changeType === 'resources' || changeType === 'both'

            const d = new Date(item.snapshot_at)
            const dayKey = d.toLocaleDateString('pt-PT', { weekday: 'short', day: 'numeric', month: 'short' })
            const showDaySep = dayKey !== lastDay
            if (showDaySep) lastDay = dayKey

            return (
              <div key={idx}>
                {showDaySep && (
                  <div className="occ-log-day-sep">{dayKey}</div>
                )}
                <div className="occ-log-entry">
                  <div className="occ-log-ts">
                    {d.toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ marginBottom: 4 }}>
                      <span className={`occ-log-tag ${TAG_CLASS[changeType] || 'tag-status'}`}>
                        {CHANGE_LABELS[changeType] || changeType.toUpperCase()}
                      </span>
                    </div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)', lineHeight: 1.7 }}>
                      {isStatus && item.status_name && (
                        <div>
                          {item.previous_status_code != null
                            ? `${item.previous_status_code} → ${item.status_code} ${item.status_name}`
                            : `${item.status_code} ${item.status_name}`}
                        </div>
                      )}
                      {isResources && (
                        <div><ResourceLine item={item} /></div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
