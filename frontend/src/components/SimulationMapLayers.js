// Lógica de camadas do mapa (grelha ROS/FLI/Chama + perímetros) e paletas
// partilhadas entre SimulacaoView (ligada a ocorrências) e
// SimuladorLivreView (ignição livre) — mesmo motor, mesma apresentação.

export const ROS_COLOR_EXPR = [
  'interpolate', ['linear'], ['coalesce', ['get', 'ros_m_min'], 0],
  1, '#3b82f6', 5, '#22c55e', 15, '#f97316', 30, '#ef4444',
]
export const FLI_COLOR_EXPR = [
  'interpolate', ['linear'], ['coalesce', ['get', 'fi_kw_m'], 0],
  500, '#3b82f6', 2000, '#22c55e', 4000, '#f97316', 10000, '#ef4444',
]
export const FLAME_COLOR_EXPR = [
  'interpolate', ['linear'], ['coalesce', ['get', 'flame_m'], 0],
  1.5, '#3b82f6', 2.5, '#22c55e', 3.5, '#f97316', 10, '#ef4444',
]

export const COLOR_EXPRS = { ros: ROS_COLOR_EXPR, fi: FLI_COLOR_EXPR, flame: FLAME_COLOR_EXPR }
export const COLOR_LABELS = { ros: 'ROS m/min', fi: 'FLI kW/m', flame: 'Chama m' }
export const COLOR_STOPS = {
  ros:   [{ v: 1, c: '#3b82f6' }, { v: 5, c: '#22c55e' }, { v: 15, c: '#f97316' }, { v: '30+', c: '#ef4444' }],
  fi:    [{ v: 500, c: '#3b82f6' }, { v: 2000, c: '#22c55e' }, { v: 4000, c: '#f97316' }, { v: '10000+', c: '#ef4444' }],
  flame: [{ v: 1.5, c: '#3b82f6' }, { v: 2.5, c: '#22c55e' }, { v: 3.5, c: '#f97316' }, { v: '10+', c: '#ef4444' }],
}

// Rampa sequencial (tempo decorrido é uma grandeza ordenada) — um único
// matiz, claro→escuro, entre os mesmos extremos usados antes (âncoras
// visuais já conhecidas na app: laranja cedo → vermelho-escuro tarde).
const PERIM_RAMP_FROM = [0xf9, 0x73, 0x16]
const PERIM_RAMP_TO = [0x7f, 0x1d, 0x1d]

export function msToKmh(v) {
  return v == null ? v : v * 3.6
}

export function perimStyle(index, total) {
  const frac = total > 1 ? index / (total - 1) : 0
  const rgb = PERIM_RAMP_FROM.map((c0, i) =>
    Math.round(c0 + (PERIM_RAMP_TO[i] - c0) * frac))
  const color = `#${rgb.map(v => v.toString(16).padStart(2, '0')).join('')}`
  return { color, fillOpacity: 0.08 + 0.18 * frac }
}

// Combina os perímetros (cada um só com a geometria em `geojson`, ver
// _make_snapshot() em simulation.py) numa única FeatureCollection, uma
// Feature por timestep, com as estatísticas desse instante como
// propriedades — para exportar todos os timesteps num só ficheiro.
export function perimetersToFeatureCollection(perimeters) {
  return {
    type: 'FeatureCollection',
    features: perimeters.map(p => ({
      type: 'Feature',
      geometry: p.geojson,
      properties: {
        t_h: p.t_h,
        area_ha: p.area_ha,
        ros_max_m_min: p.ros_max_m_min,
        fli_max_kw_m: p.fli_max_kw_m,
        flame_max_m: p.flame_max_m,
      },
    })),
  }
}

// Dispara a descarga de um objecto GeoJSON como ficheiro .geojson —
// sem endpoint no backend, os dados já estão completos no `result`
// carregado no frontend.
export function downloadGeoJSON(data, filename) {
  const blob = new Blob([JSON.stringify(data)], { type: 'application/geo+json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function renderSimulationLayers(map, result, layer, opacity, visiblePerimeters) {
  // getLayer/getSource + removeLayer/removeSource, não try/catch: o
  // MapLibre não lança excepção para um id inexistente, dispara um evento
  // 'error' interno que é impresso na consola quando não há listener —
  // o try/catch não o apanha.
  const perimIds = result.perimeters.flatMap(({ t_h }) => [`perim-${t_h}h-fill`, `perim-${t_h}h-line`]);
  ['sim-pixels-fill', 'sim-pixels-outline', ...perimIds]
    .forEach(id => { if (map.getLayer(id)) map.removeLayer(id) });
  ['sim-pixels', ...result.perimeters.map(({ t_h }) => `perim-${t_h}h`)]
    .forEach(id => { if (map.getSource(id)) map.removeSource(id) })

  if (result.pixel_grid) {
    map.addSource('sim-pixels', { type: 'geojson', data: result.pixel_grid })
    map.addLayer({
      id: 'sim-pixels-fill',
      type: 'fill',
      source: 'sim-pixels',
      paint: {
        'fill-color': COLOR_EXPRS[layer],
        'fill-opacity': opacity,
      },
    })
  }

  const maxTH = Math.max(...result.perimeters.map(p => p.t_h))
  result.perimeters.forEach(({ t_h, geojson }, i) => {
    if (visiblePerimeters && !visiblePerimeters.has(t_h)) return
    const style = perimStyle(i, result.perimeters.length)
    const id = `perim-${t_h}h`
    map.addSource(id, { type: 'geojson', data: geojson })
    map.addLayer({
      id: `${id}-fill`,
      type: 'fill',
      source: id,
      paint: { 'fill-color': style.color, 'fill-opacity': style.fillOpacity },
    })
    map.addLayer({
      id: `${id}-line`,
      type: 'line',
      source: id,
      paint: {
        'line-color': style.color,
        'line-width': t_h === maxTH ? 2 : 1,
      },
    })
  })
}
