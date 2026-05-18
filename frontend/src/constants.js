export const PRIORITY_COLOR = {
  P0: '#e05050',
  P1: '#d4622a',
  P2: '#c89a2a',
  P3: '#8C961C',
  P4: '#429ABD',
}

export const PRIORITY_LABEL = {
  P0: 'EXTREMO',
  P1: 'CRÍTICO',
  P2: 'ELEVADO',
  P3: 'MÉDIO',
  P4: 'BAIXO',
}

export const FIRE_TYPE_LABEL = {
  surface: 'SUP',
  torching: 'TORCH',
  crowning: 'CROWN',
  no_burn: '—',
}

export const FIRE_TYPE_COLOR = {
  surface: '#429ABD',
  torching: '#c89a2a',
  crowning: '#e05050',
  no_burn: '#4d6650',
}

export const TACTIC_LABEL = {
  direct_attack_manual: 'Ataque direto manual',
  direct_attack_difficult: 'Ataque direto difícil',
  indirect_attack_machinery: 'Indireto c/ máquinas',
  indirect_attack_only: 'Indireto — desimpedir',
}

const WIND_DIRS = ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSO','SO','OSO','O','ONO','NO','NNO']

export function windDirText(deg) {
  if (deg == null) return '—'
  return WIND_DIRS[Math.round(deg / 22.5) % 16]
}

export function fmt(value, decimals = 1, unit = '') {
  if (value == null || value === undefined) return '—'
  return `${Number(value).toFixed(decimals)}${unit ? ' ' + unit : ''}`
}

export function fmtTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' })
}

export function fmtDateTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('pt-PT', {
    day: '2-digit', month: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

export function fmtDuration(startIso) {
  if (!startIso) return '—'
  const diff = Math.floor((Date.now() - new Date(startIso)) / 60000)
  if (diff < 60) return `${diff}min`
  const h = Math.floor(diff / 60)
  const m = diff % 60
  return m === 0 ? `${h}h` : `${h}h${m}min`
}
