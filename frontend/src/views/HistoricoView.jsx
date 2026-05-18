import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { fetchFireHistory, fetchFireDetail } from '../api'
import { fmtDateTime, fmtTime } from '../constants'

const CHANGE_LABELS = {
  created: 'CRIADO',
  status: 'ESTADO',
  resources: 'RECURSOS',
  both: 'ESTADO+RECURSOS',
}

const CHANGE_DOT = {
  created: 'created',
  status: 'status',
  resources: 'resources',
  both: 'status',
}

function ResourceLine({ item }) {
  const parts = []
  if (item.operatives) parts.push(`${item.operatives} operacionais`)
  if (item.vehicles) parts.push(`${item.vehicles} veículos`)
  if (item.aerial) parts.push(`${item.aerial} aéreos`)
  if (item.heli_fight) parts.push(`${item.heli_fight} heli-combate`)
  if (item.plane_fight) parts.push(`${item.plane_fight} aviões`)
  return <span>{parts.join(' · ') || '—'}</span>
}

export default function HistoricoView({ apiKey }) {
  const { fireId } = useParams()
  const navigate = useNavigate()
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
      .then(([hist, f]) => {
        setHistory(hist)
        setFire(f)
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [apiKey, fireId])

  if (loading) return <div className="state-center">A carregar…</div>
  if (error) return (
    <div className="state-center" style={{ color: 'var(--danger)', gap: 8 }}>
      <div>Erro ao carregar histórico</div>
      <div style={{ fontSize: 11, opacity: 0.7 }}>{error}</div>
    </div>
  )

  const location = fire ? `${fire.municipality}, ${fire.district}` : fireId

  return (
    <div className="content scrollable" style={{ height: '100%' }}>
      {/* Sub-header */}
      <div style={{
        padding: '10px 16px',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        background: 'var(--surface2)',
      }}>
        <Link
          to={`/fogo/${fireId}`}
          style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent2)' }}
        >
          ← Detalhe
        </Link>
        <span style={{ fontFamily: 'var(--font-cond)', fontSize: 15, fontWeight: 600 }}>
          {location}
        </span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)' }}>
          {history?.length ?? 0} eventos
        </span>
      </div>

      {history && history.length === 0 ? (
        <div className="state-center" style={{ color: 'var(--muted)' }}>
          <div>Sem histórico registado</div>
        </div>
      ) : (
        <div className="history-list">
          {(history || []).map((item, idx) => {
            const changeType = item.change_type || 'status'
            const isCreated = changeType === 'created'
            const isStatus = changeType === 'status' || changeType === 'both'
            const isResources = changeType === 'resources' || changeType === 'both'

            return (
              <div key={idx} className="history-item">
                <div className="history-time">{fmtTime(item.snapshot_at)}</div>
                <div className={`history-dot ${CHANGE_DOT[changeType] || 'status'}`} />
                <div className="history-content">
                  <div className="history-event">
                    {CHANGE_LABELS[changeType] || changeType.toUpperCase()}
                  </div>
                  <div className="history-detail">
                    {isStatus && (
                      <div>
                        {item.previous_status_code != null
                          ? `${item.previous_status_code} → ${item.status_code} ${item.status_name}`
                          : `${item.status_code} ${item.status_name}`}
                      </div>
                    )}
                    {isResources && (
                      <div><ResourceLine item={item} /></div>
                    )}
                    <div style={{ color: 'var(--dim)', fontSize: 10, marginTop: 2 }}>
                      {fmtDateTime(item.snapshot_at)}
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
