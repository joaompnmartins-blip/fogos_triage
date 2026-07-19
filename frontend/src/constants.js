// Severidade 1-7 (Tedim et al. 2018, Tabela 3) — 7 = mais grave (numeração
// nativa do artigo, inverte a intuição do antigo esquema P0-P4). Categorias
// 5-7 = Extreme Wildfire Event (EWE); ver src/fogos_triage/severity.py.
//
// Cores extraídas directamente da Tabela 3 do artigo (rasterização a
// 150 DPI, ver ewe_cores_tedim2018.md) — fidelidade à fonte, em vez da
// rampa CVD-safe calculada anteriormente. #EFF50B (cat. 2) e #FC311C
// (cat. 4) têm contraste baixo sobre fundo claro; a cor nunca é o único
// sinal — o número da categoria e o rótulo acompanham sempre o badge.
export const SEVERITY_COLOR = {
  1: '#538135',
  2: '#EFF50B',
  3: '#F9A307',
  4: '#FC311C',
  5: '#D21804',
  6: '#A51203',
  7: '#630A01',
}

export const SEVERITY_LABEL = {
  1: 'FÁCIL',
  2: 'MODERADO',
  3: 'DIFÍCIL',
  4: 'MUITO DIFÍCIL',
  5: 'EXTREMO 1',
  6: 'EXTREMO 2',
  7: 'EXTREMO 3',
}

export const SEVERITY_IS_EWE = { 1: false, 2: false, 3: false, 4: false, 5: true, 6: true, 7: true }

// Capacidade de controlo por categoria (Tedim et al. 2018, Tabela 3) —
// substitui o antigo TACTIC_LABEL (esquema de 4 níveis por comprimento de
// chama, duplicado em 3 sítios independentes antes desta migração).
export const CONTROL_LABEL = {
  1: 'Bastante fácil',
  2: 'Moderadamente difícil',
  3: 'Muito difícil',
  4: 'Extremamente difícil',
  5: 'Virtualmente impossível',
  6: 'Impossível',
  7: 'Impossível',
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
