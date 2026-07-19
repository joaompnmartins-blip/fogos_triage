import { SEVERITY_COLOR, SEVERITY_LABEL, FIRE_TYPE_COLOR, FIRE_TYPE_LABEL } from '../constants'

export function SeverityBadge({ category, size = 'sm' }) {
  const cat = Number(category)
  const color = SEVERITY_COLOR[cat] || '#4d6650'
  const label = SEVERITY_LABEL[cat] || '—'
  const isLarge = size === 'lg'

  return (
    <span
      className="badge"
      style={{
        background: `${color}20`,
        color,
        border: `1px solid ${color}40`,
        fontSize: isLarge ? 13 : 11,
        padding: isLarge ? '4px 10px' : '2px 7px',
      }}
    >
      <span style={{ opacity: 0.7 }}>{Number.isFinite(cat) ? cat : category || '—'}</span>
      <span style={{ fontSize: isLarge ? 11 : 9, opacity: 0.9 }}>{label}</span>
    </span>
  )
}

export function FireTypeBadge({ type }) {
  const color = FIRE_TYPE_COLOR[type] || '#4d6650'
  const label = FIRE_TYPE_LABEL[type] || type || '—'

  return (
    <span
      className="badge"
      style={{
        background: `${color}18`,
        color,
        border: `1px solid ${color}35`,
        fontSize: 10,
        letterSpacing: '0.08em',
      }}
    >
      {label}
    </span>
  )
}
