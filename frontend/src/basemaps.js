// Estilos de mapa partilhados por MapView, SimulacaoView e
// SimuladorLivreView. O basemap "rua" (OSM) segue o tema da app (ver
// theme em App.jsx) — o satélite é imagem, não muda com o tema.

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
