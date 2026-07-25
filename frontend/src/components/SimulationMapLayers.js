// Lógica de camadas do mapa (grelha ROS/FLI/Chama + perímetros) e paletas
// partilhadas entre SimulacaoView (ligada a ocorrências) e
// SimuladorLivreView (ignição livre) — mesmo motor, mesma apresentação.

// Limiares e cores de classificação dos outputs FARSITE/FlamMap — espelho
// fiel de data/limiares_outputs_farsite.txt (classificação oficial). Não
// substituir por uma rampa "mais bonita": são os intervalos e as cores com
// que estes mapas são lidos operacionalmente.
//
// São CLASSES, não um gradiente: a convenção é `min <= valor < max`, com a
// última classe aberta no topo. Por isso as camadas usam expressões
// `step` (patamares) e não `interpolate` — interpolar produziria cores
// intermédias que não correspondem a classe nenhuma, e um valor mesmo em
// cima de um limiar apareceria com a cor da classe errada.
//
// A mesma rampa (verde-escuro → verde-claro → amarelo → laranja →
// vermelho) serve os três outputs; só mudam os limiares.
const CLASS_COLORS = ['#006633', '#92D050', '#FFFF00', '#FF9900', '#FF0000']

export const OUTPUT_CLASSES = {
  ros: {
    prop: 'ros_m_min',
    unit: 'm/min',
    breaks: [0.83, 2.5, 5, 13.3],
    labels: ['0 – 0,83', '0,83 – 2,5', '2,5 – 5', '5 – 13,3', '> 13,3'],
  },
  fi: {
    prop: 'fi_kw_m',
    unit: 'kW/m',
    breaks: [1500, 3750, 7500, 10000],
    labels: ['0 – 1500', '1500 – 3750', '3750 – 7500', '7500 – 10000', '> 10000'],
  },
  flame: {
    prop: 'flame_m',
    unit: 'm',
    breaks: [1.3, 2.2, 3.4, 4.7],
    labels: ['0 – 1,3', '1,3 – 2,2', '2,2 – 3,4', '3,4 – 4,7', '> 4,7'],
  },
}

// ['step', valor, cor0, limiar1, cor1, ...] — o MapLibre atribui cor_i ao
// intervalo [limiar_i, limiar_i+1), exactamente a convenção do ficheiro.
function _stepExpr({ prop, breaks }) {
  const expr = ['step', ['coalesce', ['get', prop], 0], CLASS_COLORS[0]]
  breaks.forEach((b, i) => expr.push(b, CLASS_COLORS[i + 1]))
  return expr
}

export const COLOR_EXPRS = {
  ros: _stepExpr(OUTPUT_CLASSES.ros),
  fi: _stepExpr(OUTPUT_CLASSES.fi),
  flame: _stepExpr(OUTPUT_CLASSES.flame),
}
export const COLOR_LABELS = { ros: 'ROS m/min', fi: 'FLI kW/m', flame: 'Chama m' }
export const COLOR_STOPS = Object.fromEntries(
  Object.entries(OUTPUT_CLASSES).map(([key, { labels }]) => [
    key, labels.map((v, i) => ({ v, c: CLASS_COLORS[i] })),
  ]),
)

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

// Converte a grelha esparsa de pontos {theta_deg, ros_m_min}
// (result.spread_arrows, ver _build_direction_arrows() em simulation.py)
// em LineStrings desenháveis — uma haste por ponto (comprimento em
// metros ∝ ros_m_min, clamped) mais um "V" de ponta de seta, tudo como
// LineString (sem map.addImage/ícones — evita repetir problemas de
// ciclo de vida de imagem/camada já vistos com o TerraDraw). theta_deg
// é um azimute (0°=Norte, sentido horário) na direcção PARA ONDE o
// fogo se propaga, ao contrário da convenção "de onde vem" das
// barbelas de vento.
export function spreadArrowsToFeatureCollection(
  arrowPoints,
  { minLengthM = 8, maxLengthM = 90, maxRosMMin = 30 } = {},
) {
  const dLatPerM = 1 / 111320
  const features = []
  for (const f of arrowPoints) {
    const [lon, lat] = f.geometry.coordinates
    const { theta_deg, ros_m_min } = f.properties
    if (theta_deg == null || ros_m_min == null) continue

    const frac = Math.max(0, Math.min(1, ros_m_min / maxRosMMin))
    const lengthM = minLengthM + frac * (maxLengthM - minLengthM)
    const dLonPerM = 1 / (111320 * Math.cos((lat * Math.PI) / 180))
    const thetaRad = (theta_deg * Math.PI) / 180

    const endLon = lon + lengthM * Math.sin(thetaRad) * dLonPerM
    const endLat = lat + lengthM * Math.cos(thetaRad) * dLatPerM
    features.push({
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: [[lon, lat], [endLon, endLat]] },
      properties: { ros_m_min },
    })

    const headLenM = Math.min(lengthM * 0.35, 12)
    for (const delta of [-25, 25]) {
      const barbRad = ((theta_deg + 180 + delta) * Math.PI) / 180
      const bLon = endLon + headLenM * Math.sin(barbRad) * dLonPerM
      const bLat = endLat + headLenM * Math.cos(barbRad) * dLatPerM
      features.push({
        type: 'Feature',
        geometry: { type: 'LineString', coordinates: [[endLon, endLat], [bLon, bLat]] },
        properties: { ros_m_min },
      })
    }
  }
  return { type: 'FeatureCollection', features }
}

function _perimVisibility(visiblePerimeters, t_h) {
  return (visiblePerimeters && !visiblePerimeters.has(t_h)) ? 'none' : 'visible'
}

// Construção completa — remove e recria todas as layers/sources.
// Chamar só quando `result` muda (nova simulação) ou depois de uma
// mudança de estilo (map.setStyle() já destrói tudo, reconstrução é
// inevitável nesse caso). Para simples mudanças de camada/transparência/
// visibilidade sobre o MESMO result, usar updateSimulationLayerStyle —
// muito mais barato (não mexe em sources).
export function initSimulationLayers(map, result, { layer, opacity, visiblePerimeters, showArrows }) {
  // getLayer/getSource + removeLayer/removeSource, não try/catch: o
  // MapLibre não lança excepção para um id inexistente, dispara um evento
  // 'error' interno que é impresso na consola quando não há listener —
  // o try/catch não o apanha.
  const perimIds = result.perimeters.flatMap(({ t_h }) => [`perim-${t_h}h-fill`, `perim-${t_h}h-line`]);
  ['sim-pixels-fill', 'sim-pixels-outline', 'sim-arrows-line', ...perimIds]
    .forEach(id => { if (map.getLayer(id)) map.removeLayer(id) });
  ['sim-pixels', 'sim-arrows', ...result.perimeters.map(({ t_h }) => `perim-${t_h}h`)]
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

  if (result.spread_arrows?.features?.length) {
    map.addSource('sim-arrows', {
      type: 'geojson',
      data: spreadArrowsToFeatureCollection(result.spread_arrows.features),
    })
    map.addLayer({
      id: 'sim-arrows-line',
      type: 'line',
      source: 'sim-arrows',
      layout: { visibility: showArrows ? 'visible' : 'none' },
      paint: {
        'line-color': 'rgba(20, 20, 20, 0.85)',
        'line-width': 1.1,
      },
    })
  }

  // Todos os perímetros são adicionados desde logo (não só os visíveis)
  // — a visibilidade é controlada depois via setLayoutProperty
  // (updateSimulationLayerStyle), sem precisar de recriar a source.
  const maxTH = Math.max(...result.perimeters.map(p => p.t_h))
  result.perimeters.forEach(({ t_h, geojson }, i) => {
    const style = perimStyle(i, result.perimeters.length)
    const id = `perim-${t_h}h`
    const visibility = _perimVisibility(visiblePerimeters, t_h)
    map.addSource(id, { type: 'geojson', data: geojson })
    map.addLayer({
      id: `${id}-fill`,
      type: 'fill',
      source: id,
      layout: { visibility },
      paint: { 'fill-color': style.color, 'fill-opacity': style.fillOpacity },
    })
    map.addLayer({
      id: `${id}-line`,
      type: 'line',
      source: id,
      layout: { visibility },
      paint: {
        'line-color': style.color,
        'line-width': t_h === maxTH ? 2 : 1,
      },
    })
  })
}

// Actualização leve — só setPaintProperty/setLayoutProperty, nunca
// remove/adiciona sources ou layers. Usar para qualquer mudança que não
// seja um novo `result` (trocar camada ROS/FLI/Chama, arrastar o slider
// de transparência, mostrar/esconder perímetros, ligar/desligar setas).
export function updateSimulationLayerStyle(map, result, { layer, opacity, visiblePerimeters, showArrows }) {
  if (map.getLayer('sim-pixels-fill')) {
    map.setPaintProperty('sim-pixels-fill', 'fill-color', COLOR_EXPRS[layer])
    map.setPaintProperty('sim-pixels-fill', 'fill-opacity', opacity)
  }
  if (map.getLayer('sim-arrows-line')) {
    map.setLayoutProperty('sim-arrows-line', 'visibility', showArrows ? 'visible' : 'none')
  }
  for (const { t_h } of result.perimeters) {
    const visibility = _perimVisibility(visiblePerimeters, t_h)
    const fillId = `perim-${t_h}h-fill`
    const lineId = `perim-${t_h}h-line`
    if (map.getLayer(fillId)) map.setLayoutProperty(fillId, 'visibility', visibility)
    if (map.getLayer(lineId)) map.setLayoutProperty(lineId, 'visibility', visibility)
  }
}
