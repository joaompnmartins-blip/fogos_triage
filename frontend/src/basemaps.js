// Estilos de mapa partilhados por MapView, SimulacaoView e
// SimuladorLivreView. O basemap "rua" (OSM) segue o tema da app (ver
// theme em App.jsx) — o satélite é imagem, não muda com o tema.

import { API_BASE } from './api'

export const OSM_STYLE_LIGHT = 'https://tiles.openfreemap.org/styles/liberty'
export const OSM_STYLE_DARK = 'https://tiles.openfreemap.org/styles/dark'

export const SATELLITE_STYLE = {
  version: 8,
  sources: {
    satellite: {
      type: 'raster',
      tiles: [
        'https://mt0.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
        'https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
      ],
      tileSize: 256,
      attribution: '© Google',
      maxzoom: 20,
    },
  },
  layers: [{ id: 'satellite-bg', type: 'raster', source: 'satellite' }],
}

// OpenTopoMap — curvas de nível + relevo sombreado (SRTM), útil para
// avaliar declive/exposição visualmente sem sair do Simulador/Mapa.
// Tiles servidos até zoom 17 nativo; acima disso o browser faz upscale
// do último nível (comportamento normal de raster tiles).
export const TOPO_STYLE = {
  version: 8,
  sources: {
    topo: {
      type: 'raster',
      tiles: [
        'https://a.tile.opentopomap.org/{z}/{x}/{y}.png',
        'https://b.tile.opentopomap.org/{z}/{x}/{y}.png',
        'https://c.tile.opentopomap.org/{z}/{x}/{y}.png',
      ],
      tileSize: 256,
      attribution: '© OpenStreetMap contributors, SRTM | © OpenTopoMap (CC-BY-SA)',
      maxzoom: 17,
    },
  },
  layers: [{ id: 'topo-bg', type: 'raster', source: 'topo' }],
}

export function basemapStyle(basemap, theme) {
  if (basemap === 'satellite') return SATELLITE_STYLE
  if (basemap === 'topo') return TOPO_STYLE
  return theme === 'dark' ? OSM_STYLE_DARK : OSM_STYLE_LIGHT
}

export const BASEMAP_LABEL = { osm: 'OSM', satellite: 'SAT', topo: 'TOPO' }

// Overlay de tiles raster do modelo de combustível — dado do terreno,
// independente de qualquer simulação (ver services/api/routes_tiles.py).
// Diferente de OSM/SAT/Topo: não é um basemap (não substitui nenhum dos
// outros), é uma source/layer à parte, alternada por visibilidade —
// mesmo padrão já estabelecido em initSimulationLayers/
// updateSimulationLayerStyle (SimulationMapLayers.js).
// Tem de acompanhar MIN_ZOOM em services/api/routes_tiles.py — abaixo
// disto o servidor devolve 404 (ver lá o porquê e as medições).
// Exportado para a UI poder avisar que é preciso aproximar, em vez de o
// overlay ficar em branco sem explicação.
//
// Baixou de 10 para 8 quando o landscape file passou a ter overviews e o
// renderizador passou a ler decimado: um tile de z=8 custava 278 MB e
// ~11 s, custa agora 18 MB e 1,5 s. A 8 já se vê o país inteiro.
export const FUEL_MODEL_MIN_ZOOM = 8

export const FUEL_MODEL_TILE_SOURCE = {
  type: 'raster',
  tiles: [`${API_BASE}/tiles/fuel-model/{z}/{x}/{y}.png`],
  tileSize: 256,
  minzoom: FUEL_MODEL_MIN_ZOOM,
  maxzoom: 16,
}

// Adiciona a source/layer do overlay uma única vez (idempotente —
// getSource antes de adicionar), começa escondida. Toggle é só
// setLayoutProperty depois (ver setFuelModelLayerVisible) — nunca
// remover/readicionar a cada clique, mesmo padrão já estabelecido em
// initSimulationLayers/updateSimulationLayerStyle (SimulationMapLayers.js).
// Chamar sempre que o estilo do mapa é (re)carregado (mount, troca de
// basemap) — map.setStyle() destrói tudo, incluindo isto.
export function addFuelModelLayer(map, { visible = false, opacity = 0.7 } = {}) {
  if (map.getSource('fuel-model-tiles')) return
  map.addSource('fuel-model-tiles', FUEL_MODEL_TILE_SOURCE)
  map.addLayer({
    id: 'fuel-model-tiles-layer',
    type: 'raster',
    source: 'fuel-model-tiles',
    layout: { visibility: visible ? 'visible' : 'none' },
    paint: { 'raster-opacity': opacity },
  })
}

export function setFuelModelLayerVisible(map, visible) {
  if (map.getLayer('fuel-model-tiles-layer')) {
    map.setLayoutProperty('fuel-model-tiles-layer', 'visibility', visible ? 'visible' : 'none')
  }
}

export function setFuelModelLayerOpacity(map, opacity) {
  if (map.getLayer('fuel-model-tiles-layer')) {
    map.setPaintProperty('fuel-model-tiles-layer', 'raster-opacity', opacity)
  }
}

// Catálogo oficial dos modelos de combustível PT — cores e designações
// espelham exactamente src/fogos_triage/fuel_model_colors.py, que por sua
// vez espelha data/modelos_combustivel_PT_cores.csv (cartografia oficial).
// **Não "melhorar" estas cores**: são as que os utilizadores já reconhecem
// da cartografia oficial. Valores hardcoded, não pedidos ao servidor:
// catálogo estático, e a legenda tem de aparecer mesmo sem rede.
//
// Nota: 98 = "Planos de água" é uma classe real (azul), não "sem dados" —
// o fundo do raster (0) e o nodata ficam transparentes por não estarem
// aqui. Em simulação/triagem, 91-99 são todos tratados como não
// combustível (ver normalize_fuel_model_num em fuel_models.py); isto aqui
// é só desenho.
export const FUEL_MODEL_GROUP_ORDER = [
  'Povoamento sem sub-coberto',
  'Povoamento com sub-coberto',
  'Herbáceas / Matos',
  'Não combustível',
]

export const FUEL_MODELS = {
  211: { hex: '#00ff00', label: 'Eucalipto sem sub-coberto', grupo: 'Povoamento sem sub-coberto' },
  212: { hex: '#007900', label: 'Folhosas sem sub-coberto', grupo: 'Povoamento sem sub-coberto' },
  213: { hex: '#004d00', label: 'Pinheiro-bravo sem sub-coberto', grupo: 'Povoamento sem sub-coberto' },
  214: { hex: '#c9e9ff', label: 'Resinosas de agulha-curta', grupo: 'Povoamento sem sub-coberto' },
  221: { hex: '#086664', label: 'Caducifólias com sub-coberto', grupo: 'Povoamento com sub-coberto' },
  222: { hex: '#00a010', label: 'Esclerófilas com sub-coberto', grupo: 'Povoamento com sub-coberto' },
  223: { hex: '#00d814', label: 'Eucalipto com sub-coberto', grupo: 'Povoamento com sub-coberto' },
  224: { hex: '#a2e000', label: 'Seleção de varas de Eucalipto', grupo: 'Povoamento com sub-coberto' },
  225: { hex: '#16bc64', label: 'Povoamentos com sub-coberto de fetos', grupo: 'Povoamento com sub-coberto' },
  226: { hex: '#94664e', label: 'Povoamentos com sub-coberto de herbáceas', grupo: 'Povoamento com sub-coberto' },
  227: { hex: '#273700', label: 'Pinheiro-bravo com sub-coberto', grupo: 'Povoamento com sub-coberto' },
  231: { hex: '#ffe040', label: 'Herbáceas altas (>0,5 metros)', grupo: 'Herbáceas / Matos' },
  232: { hex: '#ffff00', label: 'Herbáceas baixas (<0,5 metros)', grupo: 'Herbáceas / Matos' },
  233: { hex: '#ff7533', label: 'Matos atlânticos altos (>1 metro)', grupo: 'Herbáceas / Matos' },
  234: { hex: '#ff9868', label: 'Matos atlânticos baixos (<1 metro)', grupo: 'Herbáceas / Matos' },
  235: { hex: '#ade544', label: 'Matos jovens', grupo: 'Herbáceas / Matos' },
  236: { hex: '#e1c32b', label: 'Matos mediterrânicos altos (>1 metro)', grupo: 'Herbáceas / Matos' },
  237: { hex: '#dee020', label: 'Matos mediterrânicos baixos (<1 metro)', grupo: 'Herbáceas / Matos' },
  91: { hex: '#d40000', label: 'Urbano', grupo: 'Não combustível' },
  93: { hex: '#42cfb7', label: 'Agricultura de regadios', grupo: 'Não combustível' },
  98: { hex: '#0057f7', label: 'Planos de água', grupo: 'Não combustível' },
  99: { hex: '#bdbdbd', label: 'Rocha', grupo: 'Não combustível' },
}

// Rótulo legível de um modelo de combustível, a partir do código que a API
// devolve ("FM232") ou do número. Mostrar só "FM232" obriga quem lê a ir
// à legenda traduzir — e o código sozinho não diz nada a quem não decorou
// a tabela.
//
// Devolve o código tal e qual se o modelo não estiver no catálogo: os
// códigos NB do raster (91-99) estão cá, mas um modelo novo que apareça
// nos dados não deve fazer desaparecer a informação que já existe.
export function fuelModelLabel(code) {
  if (code == null) return null
  const num = parseInt(String(code).replace(/\D/g, ''), 10)
  const m = FUEL_MODELS[num]
  return m ? `${code} · ${m.label}` : String(code)
}
