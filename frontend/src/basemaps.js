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
export const FUEL_MODEL_TILE_SOURCE = {
  type: 'raster',
  tiles: [`${API_BASE}/tiles/fuel-model/{z}/{x}/{y}.png`],
  tileSize: 256,
  minzoom: 8,
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

// Cores por modelo de combustível — espelha exactamente
// src/fogos_triage/fuel_model_colors.py (matiz por família 21x/22x/23x/
// 255, luminosidade a variar dentro da família, validado com a skill
// dataviz — ver docstring desse módulo). Valores hardcoded, não
// recalculados no cliente: catálogo estático, sem necessidade de pedir
// ao servidor só para isto.
export const FUEL_MODEL_COLOR = {
  211: '#2f7d32',
  212: '#478c4a',
  213: '#609b62',
  214: '#78aa7a',
  221: '#1b6ea8',
  222: '#2876ad',
  223: '#367fb2',
  224: '#4387b7',
  225: '#5090bc',
  226: '#5e98c1',
  227: '#6ba1c6',
  231: '#c2376b',
  232: '#c64374',
  233: '#c94e7c',
  234: '#cd5a85',
  235: '#d0668e',
  236: '#d47196',
  237: '#d77d9f',
  255: '#e0a300',
}
