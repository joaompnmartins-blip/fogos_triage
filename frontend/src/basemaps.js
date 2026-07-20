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

export function basemapStyle(basemap, theme) {
  if (basemap === 'satellite') return SATELLITE_STYLE
  return theme === 'dark' ? OSM_STYLE_DARK : OSM_STYLE_LIGHT
}
