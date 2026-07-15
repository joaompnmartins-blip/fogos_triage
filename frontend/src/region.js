// Configuração da região visível no mapa/topbar, parametrizável por env vars
// para permitir deploys regionais (ex. piloto Alto Minho) sem fork do
// frontend. Sem env vars definidas, mantém o comportamento atual
// (Portugal Continental).

const DEFAULT_BBOX = { minLat: 30, minLng: -32, maxLat: 42.5, maxLng: -5.5 }
const DEFAULT_CENTER = [-8.0, 39.5]
const DEFAULT_ZOOM = 6.5
const DEFAULT_LABEL = 'Portugal Continental'

function parseBbox(str) {
  if (!str) return null
  const parts = str.split(',').map(Number)
  if (parts.length !== 4 || parts.some(Number.isNaN)) return null
  const [minLat, minLng, maxLat, maxLng] = parts
  return { minLat, minLng, maxLat, maxLng }
}

function parseCenter(str) {
  if (!str) return null
  const parts = str.split(',').map(Number)
  if (parts.length !== 2 || parts.some(Number.isNaN)) return null
  return parts
}

export const REGION_BBOX = parseBbox(import.meta.env.VITE_REGION_BBOX) || DEFAULT_BBOX
export const REGION_CENTER = parseCenter(import.meta.env.VITE_REGION_CENTER) || DEFAULT_CENTER
export const REGION_ZOOM = Number(import.meta.env.VITE_REGION_ZOOM) || DEFAULT_ZOOM
export const REGION_LABEL = import.meta.env.VITE_REGION_LABEL || DEFAULT_LABEL
