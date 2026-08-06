// Configuração da região visível no mapa/topbar, parametrizável por env vars
// para permitir deploys regionais (ex. piloto Alto Minho) sem fork do
// frontend. Sem env vars definidas, mantém o comportamento atual
// (Portugal Continental).

const DEFAULT_BBOX = { minLat: 30, minLng: -32, maxLat: 42.5, maxLng: -5.5 }
const DEFAULT_CENTER = [-8.0, 39.5]
const DEFAULT_ZOOM = 6.5
const DEFAULT_LABEL = 'Portugal Continental'

// Limites de ENQUADRAMENTO — o que o mapa mostra ao abrir. Distintos do
// DEFAULT_BBOX acima, que é a janela de CONSULTA à API e se estende até
// aos Açores (lng -32) para apanhar ocorrências insulares. Enquadrar por
// essa caixa deixaria Portugal continental como um risco no canto.
//
// Portugal continental: Cabo da Roca a oeste (-9.50), Miranda do Douro a
// leste (-6.19), Cabo de Santa Maria a sul (36.96), Melgaço a norte
// (42.15), com folga para o enquadramento não ficar colado.
const DEFAULT_FIT_BOUNDS = [[-9.55, 36.90], [-6.15, 42.20]]

// Margem em píxeis entre os limites e as bordas do mapa. 24 chega para o
// contorno não encostar aos painéis flutuantes da legenda.
export const REGION_FIT_PADDING = 24

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

function parseFitBounds(str) {
  if (!str) return null
  const p = str.split(',').map(Number)
  if (p.length !== 4 || p.some(Number.isNaN)) return null
  const [minLng, minLat, maxLng, maxLat] = p
  return [[minLng, minLat], [maxLng, maxLat]]
}

export const REGION_BBOX = parseBbox(import.meta.env.VITE_REGION_BBOX) || DEFAULT_BBOX
export const REGION_CENTER = parseCenter(import.meta.env.VITE_REGION_CENTER) || DEFAULT_CENTER
export const REGION_ZOOM = Number(import.meta.env.VITE_REGION_ZOOM) || DEFAULT_ZOOM
export const REGION_LABEL = import.meta.env.VITE_REGION_LABEL || DEFAULT_LABEL
export const REGION_FIT_BOUNDS =
  parseFitBounds(import.meta.env.VITE_REGION_FIT_BOUNDS) || DEFAULT_FIT_BOUNDS

// Um deploy regional que fixe centro/zoom continua a mandar; sem isso,
// enquadra-se pelos limites. Era assim que o piloto do Alto Minho estava
// pensado (ver cabeçalho), e tirar-lhe o mecanismo por causa do default
// seria uma regressão silenciosa.
const CENTRO_EXPLICITO = parseCenter(import.meta.env.VITE_REGION_CENTER) !== null
  && Number(import.meta.env.VITE_REGION_ZOOM) > 0

/** Opções de abertura do mapa — usar com spread nas opções do maplibregl.Map. */
export const REGION_INITIAL_VIEW = CENTRO_EXPLICITO
  ? { center: REGION_CENTER, zoom: REGION_ZOOM }
  : { bounds: REGION_FIT_BOUNDS, fitBoundsOptions: { padding: REGION_FIT_PADDING } }

/** Repõe o enquadramento da região num mapa já aberto. */
export function flyToRegion(map, duration = 600) {
  if (CENTRO_EXPLICITO) {
    map.flyTo({ center: REGION_CENTER, zoom: REGION_ZOOM, duration })
  } else {
    map.fitBounds(REGION_FIT_BOUNDS, { padding: REGION_FIT_PADDING, duration })
  }
}
