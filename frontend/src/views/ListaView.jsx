import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchFires } from '../api'
import { PriorityBadge, FireTypeBadge } from '../components/PriorityBadge'
import { fmt, fmtTime, fmtDuration, PRIORITY_COLOR } from '../constants'

function FireCard({ fire, onClick }) {
  const t = fire.triage
  const central = t?.central
  const priorityColor = t ? PRIORITY_COLOR[t.priority_class] : 'var(--icnf-blue-light)'

  return (
    <div
      className="fire-card"
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && onClick()}
      style={{ '--card-color': priorityColor }}
    >
      <div className="fire-card-header">
        <div className="fire-card-id">{fire.fire_id.slice(0, 18)}</div>
        <div className="fire-card-name">
          {[fire.municipality, fire.district].filter(Boolean).join(' · ')}
        </div>
        {(fire.parish || fire.locality) && (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>
            {[fire.parish, fire.locality].filter(Boolean).join(', ')}
          </div>
        )}
        <div className="fire-card-meta">
          {t ? <PriorityBadge priority={t.priority_class} /> : (
            <span className="badge badge-closed">SEM TRIAGEM</span>
          )}
          {central && <FireTypeBadge type={central.fire_type} />}
          {fire.is_important && (
            <span className="badge badge-danger" style={{ fontSize: 9 }}>IMPORTANTE</span>
          )}
          <span style={{ flex: 1 }} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted)' }}>
            {fmtDuration(fire.started_at)}
          </span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--dim)' }}>
            {fmtTime(fire.started_at)}
          </span>
        </div>
      </div>

      <div className="fire-card-body">
        <div>
          <div className="fire-big-num">
            {central ? fmt(central.ros_km_per_h, 1) : '—'}
          </div>
          <div className="fire-big-label">km/h ROS</div>
        </div>
        <div className="fire-metrics">
          {central && (
            <>
              <div><strong>{fmt(central.fireline_intensity_kw_m, 0)}</strong> kW/m</div>
              <div><strong>{fmt(central.flame_length_m, 1)}</strong> m chama</div>
            </>
          )}
          <div><strong>{fire.operatives}</strong> operacionais</div>
          {fire.vehicles > 0 && <div><strong>{fire.vehicles}</strong> veíc.</div>}
          {fire.aerial > 0 && <div><strong>{fire.aerial}</strong> aéreos</div>}
        </div>
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

  useEffect(() => { load({ reset: true }) }, [filter, apiKey])
  useEffect(() => {
    const id = setInterval(() => load({ reset: true }), 60_000)
    return () => clearInterval(id)
  }, [load])

  const loadMore = () => {
    if (!hasMore || loadingMore) return
    load({ reset: false, currentCursor: cursor })
  }

  const triaged = fires.filter(f => f.triage).length
  const critical = fires.filter(f => f.triage && ['P0', 'P1', 'P2'].includes(f.triage.priority_class)).length

  return (
    <div className="content-scroll">
      {/* Stats row */}
      <div className="stats-row">
        <div className="stat-card y">
          <div className="stat-label">Ocorrências ativas</div>
          <div className="stat-val y">{loading ? '…' : total}</div>
        </div>
        <div className="stat-card r">
          <div className="stat-label">Com triagem</div>
          <div className="stat-val r">{loading ? '…' : triaged}</div>
        </div>
        <div className="stat-card d">
          <div className="stat-label">Alta prioridade (P0–P2)</div>
          <div className="stat-val d">{loading ? '…' : critical}</div>
        </div>
      </div>

      {/* Section header + filter bar */}
      <div className="section-hdr">
        <div className="section-title">
          Lista
          <span>{loading ? 'a carregar…' : `${total} ocorrência${total !== 1 ? 's' : ''}`}</span>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
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
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div className="state-center" style={{ height: 280 }}>
          <div>A carregar…</div>
        </div>
      ) : error ? (
        <div className="state-center" style={{ height: 280, color: 'var(--danger)' }}>
          <div>Erro ao carregar</div>
          <div style={{ fontSize: 11, opacity: 0.7 }}>{error}</div>
        </div>
      ) : fires.length === 0 ? (
        <div className="state-center" style={{ height: 280 }}>
          <div>Nenhuma ocorrência ativa</div>
        </div>
      ) : (
        <>
          <div className="fire-grid">
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
              <button className="btn btn-ghost" onClick={loadMore} disabled={loadingMore}>
                {loadingMore ? 'A carregar…' : 'Carregar mais'}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
