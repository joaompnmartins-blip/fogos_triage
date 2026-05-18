import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchFires } from '../api'
import { PriorityBadge, FireTypeBadge } from '../components/PriorityBadge'
import { fmt, fmtTime, fmtDuration } from '../constants'

const NATUREZA_ICONS = {
  3101: '🌲',
  3103: '🌿',
  3105: '🌾',
}

function FireCard({ fire, onClick }) {
  const t = fire.triage
  const central = t?.central

  const location = [fire.municipality, fire.district].filter(Boolean).join(' · ')
  const detail = [fire.parish, fire.locality].filter(Boolean).join(', ')

  return (
    <div className="fire-card" onClick={onClick} role="button" tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && onClick()}>
      <div className="fire-card-header">
        {t ? <PriorityBadge priority={t.priority_class} /> : (
          <span className="badge" style={{ background: 'var(--inactive)', color: 'var(--muted)', border: '1px solid var(--border)' }}>
            SEM TRIAGEM
          </span>
        )}
        {central && <FireTypeBadge type={central.fire_type} />}
        <span className="fire-card-location">{location}</span>
        <span className="fire-card-meta">{fmtDuration(fire.started_at)}</span>
        {fire.is_important && (
          <span className="badge" style={{ background: '#e0505018', color: 'var(--danger)', border: '1px solid #e0505030', fontSize: 9 }}>
            IMPORTANTE
          </span>
        )}
      </div>

      {detail && (
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)' }}>
          {detail}
        </div>
      )}

      {central && (
        <div className="fire-card-metrics">
          <div className="metric">
            <span className="metric-label">ROS</span>
            <span className="metric-value">
              {fmt(central.ros_km_per_h, 1)}<span className="unit">km/h</span>
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">Intensidade</span>
            <span className="metric-value">
              {fmt(central.fireline_intensity_kw_m, 0)}<span className="unit">kW/m</span>
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">Chama</span>
            <span className="metric-value">
              {fmt(central.flame_length_m, 1)}<span className="unit">m</span>
            </span>
          </div>
          {t && (
            <div className="metric">
              <span className="metric-label">Score</span>
              <span className="metric-value" style={{ color: 'var(--muted)' }}>
                {fmt(t.priority_score, 0)}
              </span>
            </div>
          )}
        </div>
      )}

      <div className="fire-card-footer">
        <span className="resource-chip">
          <span style={{ color: 'var(--muted)' }}>⟳</span>
          <span className="num">{fire.operatives}</span>
          <span>operacionais</span>
        </span>
        {fire.vehicles > 0 && (
          <span className="resource-chip">
            <span className="num">{fire.vehicles}</span>
            <span>veíc.</span>
          </span>
        )}
        {fire.aerial > 0 && (
          <span className="resource-chip">
            <span style={{ color: 'var(--accent2)' }}>✈</span>
            <span className="num">{fire.aerial}</span>
            <span>aéreos</span>
          </span>
        )}
        <span style={{ flex: 1 }} />
        <span className="fire-card-meta">
          {fire.status_name || ''}
        </span>
        <span className="fire-card-meta" style={{ color: 'var(--dim)' }}>
          {fmtTime(fire.started_at)}
        </span>
      </div>
    </div>
  )
}

export default function ListaView({ apiKey }) {
  const [fires, setFires] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState(null)
  const [cursor, setCursor] = useState(null)
  const [hasMore, setHasMore] = useState(false)
  const [total, setTotal] = useState(0)
  const [filter, setFilter] = useState({ minPriority: '', onlyTriaged: false })
  const navigate = useNavigate()

  const load = useCallback(async ({ reset = true, currentCursor } = {}) => {
    if (reset) setLoading(true)
    else setLoadingMore(true)

    try {
      const result = await fetchFires(apiKey, {
        limit: 50,
        cursor: reset ? null : currentCursor,
        minPriority: filter.minPriority || undefined,
        onlyTriaged: filter.onlyTriaged,
      })
      setFires(prev => reset ? result.items : [...prev, ...result.items])
      setTotal(result.total)
      setCursor(result.next_cursor || null)
      setHasMore(!!result.next_cursor)
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
      setLoadingMore(false)
    }
  }, [apiKey, filter])

  // Reset on filter change
  useEffect(() => { load({ reset: true }) }, [filter, apiKey])

  // Auto-refresh every 60s
  useEffect(() => {
    const id = setInterval(() => load({ reset: true }), 60_000)
    return () => clearInterval(id)
  }, [load])

  const loadMore = () => {
    if (!hasMore || loadingMore) return
    load({ reset: false, currentCursor: cursor })
  }

  return (
    <div className="content scrollable" style={{ height: '100%' }}>
      {/* Filter bar */}
      <div className="filter-bar">
        <span className="filter-label">Filtrar</span>
        <select
          className="filter-select"
          value={filter.minPriority}
          onChange={e => setFilter(f => ({ ...f, minPriority: e.target.value }))}
        >
          <option value="">Todas as prioridades</option>
          <option value="P1">P1 e acima</option>
          <option value="P2">P2 e acima</option>
          <option value="P3">P3 e acima</option>
        </select>
        <label className="filter-check">
          <input
            type="checkbox"
            checked={filter.onlyTriaged}
            onChange={e => setFilter(f => ({ ...f, onlyTriaged: e.target.checked }))}
          />
          Só com triagem
        </label>
        <span className="total-chip">
          {loading ? '…' : `${total} ocorrência${total !== 1 ? 's' : ''}`}
        </span>
      </div>

      {/* Content */}
      {loading ? (
        <div className="state-center" style={{ height: 'calc(100% - 42px)' }}>
          <div>A carregar…</div>
        </div>
      ) : error ? (
        <div className="state-center" style={{ height: 'calc(100% - 42px)', color: 'var(--danger)' }}>
          <div>Erro ao carregar</div>
          <div style={{ fontSize: 11, opacity: 0.7 }}>{error}</div>
        </div>
      ) : fires.length === 0 ? (
        <div className="state-center" style={{ height: 'calc(100% - 42px)' }}>
          <div>Nenhuma ocorrência ativa</div>
        </div>
      ) : (
        <>
          <div className="fire-list">
            {fires.map(fire => (
              <FireCard
                key={fire.fire_id}
                fire={fire}
                onClick={() => navigate(`/fogo/${fire.fire_id}`)}
              />
            ))}
          </div>
          {hasMore && (
            <div className="load-more-wrap">
              <button className="btn-ghost" onClick={loadMore} disabled={loadingMore}>
                {loadingMore ? 'A carregar…' : 'Carregar mais'}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
