import { useState, useEffect, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { TerraDraw, TerraDrawPointMode, TerraDrawLineStringMode, TerraDrawSelectMode } from 'terra-draw'
import { TerraDrawMapLibreGLAdapter } from 'terra-draw-maplibre-gl-adapter'
import { postFreeSimulate, getFreeSimulationJob } from '../api'
import { fmt, FUEL_MOISTURE_SCENARIO_LABEL } from '../constants'
import { REGION_CENTER, REGION_ZOOM } from '../region'
import {
  COLOR_LABELS, COLOR_STOPS, msToKmh, perimStyle,
  initSimulationLayers, updateSimulationLayerStyle,
  downloadGeoJSON, perimetersToFeatureCollection,
} from '../components/SimulationMapLayers'
import { Legend, ResultsTable, DurationSelect, FuelMoistureScenarioSelect, FileTextInput } from '../components/SimulationPanels'
import { basemapStyle, BASEMAP_LABEL } from '../basemaps'

// Extrai [[lat,lon], ...] das features desenhadas/importadas (Point ou
// LineString) — filtra por properties.mode, não só geometry.type: com o
// select mode activo, o TerraDraw pode injectar feições auxiliares no
// snapshot (ex. midpoints para inserir vértices numa linha seleccionada),
// que não têm a tag 'point'/'linestring' das feições reais.
function _ignitionFromSnapshot(snapshot) {
  const feature = snapshot.find(f => f.properties?.mode === 'point' || f.properties?.mode === 'linestring')
  if (!feature) return []
  const coords = feature.geometry.type === 'Point'
    ? [feature.geometry.coordinates]
    : feature.geometry.coordinates
  return coords.map(([lon, lat]) => [lat, lon])
}

// Parseia um ficheiro GeoJSON (Feature ou FeatureCollection) com uma
// geometria Point ou LineString para usar como ignição — mesma conversão
// de coordenadas de _ignitionFromSnapshot, e a feição devolvida já vem
// na forma mínima que TerraDraw.addFeatures() aceita (confirmado
// empiricamente: não precisa de id explícito, TerraDraw gera um).
function parseIgnitionGeoJSON(text) {
  let data
  try {
    data = JSON.parse(text)
  } catch (e) {
    throw new Error(`GeoJSON inválido: ${e.message}`)
  }

  const features = data?.type === 'FeatureCollection' ? data.features : [data]
  const found = features?.find(f =>
    f?.geometry?.type === 'Point' || f?.geometry?.type === 'LineString')
  if (!found) {
    throw new Error('ficheiro deve conter uma geometria Point ou LineString')
  }

  const mode = found.geometry.type === 'Point' ? 'point' : 'linestring'
  const feature = { type: 'Feature', geometry: found.geometry, properties: { mode } }
  const coords = mode === 'point' ? [found.geometry.coordinates] : found.geometry.coordinates
  const points = coords.map(([lon, lat]) => [lat, lon])
  return { points, feature }
}

// Prefixo de sources/layers do TerraDrawMapLibreGLAdapter quando não se
// passa prefixId (ver node_modules/terra-draw-maplibre-gl-adapter) — usado
// para poder remover manualmente quaisquer resíduos antes de reinstanciar.
const _DRAW_PREFIX = 'td'

// Remove sources/layers do TerraDraw que possam ter ficado do mapa, sem
// assumir nada sobre se a instância anterior os registou/desregistou com
// sucesso — cada remoção é guardada por uma verificação de existência, para
// nunca rebentar em cima de estado que já não está lá (ex.: depois de um
// map.setStyle(), que destrói tudo).
function _teardownDrawLayers(map) {
  for (const id of [
    `${_DRAW_PREFIX}-point`, `${_DRAW_PREFIX}-point-marker`,
    `${_DRAW_PREFIX}-linestring`,
    `${_DRAW_PREFIX}-polygon`, `${_DRAW_PREFIX}-polygon-outline`,
  ]) {
    if (map.getLayer(id)) map.removeLayer(id)
  }
  for (const id of [`${_DRAW_PREFIX}-point`, `${_DRAW_PREFIX}-linestring`, `${_DRAW_PREFIX}-polygon`]) {
    if (map.getSource(id)) map.removeSource(id)
  }
}

// Cria e regista uma instância TerraDraw nova. Nunca reutiliza/reinicia uma
// instância existente (stop()/clear() assumem que as suas próprias sources
// ainda existem no mapa — depois de um map.setStyle() ou de qualquer outra
// falha de sincronização isso deixa de ser verdade e rebenta com "Cannot
// read properties of undefined (reading 'setData')"). Faz sempre tábua rasa
// primeiro, por isso é seguro chamar isto a qualquer momento.
function _attachDraw(map, onFinish, onChange) {
  _teardownDrawLayers(map)
  const draw = new TerraDraw({
    adapter: new TerraDrawMapLibreGLAdapter({ map }),
    modes: [
      new TerraDrawPointMode(),
      new TerraDrawLineStringMode(),
      // Arrasto (ponto inteiro, ou vértices individuais de uma linha) —
      // confirmado empiricamente que draw.clear() continua seguro depois
      // de usar o select mode, sem reintroduzir o crash pós-setStyle()
      // já corrigido nesta sessão.
      new TerraDrawSelectMode({
        flags: {
          point: { feature: { draggable: true } },
          linestring: { feature: { draggable: true }, coordinates: { draggable: true } },
        },
      }),
    ],
  })
  draw.on('finish', onFinish)
  draw.on('change', onChange)
  draw.start()
  return draw
}

export default function SimuladorLivreView({ apiKey, theme }) {
  const mapRef = useRef(null)
  const containerRef = useRef(null)
  const drawRef = useRef(null)
  const basemapInitRef = useRef(true)  // skip first run do efeito de basemap

  const [mapReady, setMapReady] = useState(false)
  const [drawMode, setDrawMode] = useState(null) // null | 'point' | 'linestring'
  const [ignitionPoints, setIgnitionPoints] = useState([])
  const [basemap, setBasemap] = useState('osm')
  const [layer, setLayer] = useState('ros')
  const [opacity, setOpacity] = useState(0.75)
  const [durationH, setDurationH] = useState(3)
  const [useGusts, setUseGusts] = useState(false)
  const [fuelMoistureScenario, setFuelMoistureScenario] = useState(null)
  const [weatherStreamText, setWeatherStreamText] = useState(null)
  const [weatherStreamFilename, setWeatherStreamFilename] = useState(null)
  const [fuelMoistureTableText, setFuelMoistureTableText] = useState(null)
  const [fuelMoistureTableFilename, setFuelMoistureTableFilename] = useState(null)
  const [jobStatus, setJobStatus] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [visiblePerimeters, setVisiblePerimeters] = useState(new Set())
  const [showArrows, setShowArrows] = useState(true)
  const pollRef = useRef(null)

  // Feição acabada de desenhar (finish já dá o id) — fica logo
  // seleccionada/arrastável, sem clique extra.
  const onDrawFinish = (id) => {
    const draw = drawRef.current
    if (!draw) return
    setIgnitionPoints(_ignitionFromSnapshot(draw.getSnapshot()))
    draw.setMode('select')
    draw.selectFeature(id)
    setDrawMode('select')
  }

  // Feição arrastada (select mode) — volta a ler o snapshot para
  // reflectir a posição/vértices actualizados.
  const onDrawChange = () => {
    const draw = drawRef.current
    if (draw) setIgnitionPoints(_ignitionFromSnapshot(draw.getSnapshot()))
  }

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: basemapStyle(basemap, theme),
      center: REGION_CENTER,
      zoom: REGION_ZOOM,
      attributionControl: false,
    })
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right')

    map.on('load', () => {
      drawRef.current = _attachDraw(map, onDrawFinish, onDrawChange)
      setMapReady(true)
    })

    mapRef.current = map
    return () => {
      try { drawRef.current?.stop() } catch { /* mapa vai ser destruído já a seguir */ }
      map.remove()
      mapRef.current = null
      drawRef.current = null
    }
  }, [])

  useEffect(() => {
    if (basemapInitRef.current) { basemapInitRef.current = false; return }
    const map = mapRef.current
    if (!map) return
    map.setStyle(basemapStyle(basemap, theme))
    map.once('style.load', () => {
      // setStyle() destrói todas as sources/layers, incluindo as do
      // TerraDraw — reinstancia-se em vez de reiniciar a mesma instância
      // (ver _attachDraw). O desenho em curso perde-se visualmente de
      // qualquer forma quando o estilo muda, por isso reset de estado aqui.
      drawRef.current = _attachDraw(map, onDrawFinish, onDrawChange)
      setIgnitionPoints([])
      setDrawMode(null)
      if (result) initSimulationLayers(map, result, { layer, opacity, visiblePerimeters, showArrows })
    })
  }, [basemap, theme])

  // Novo resultado — todos os perímetros começam visíveis
  useEffect(() => {
    if (result) setVisiblePerimeters(new Set(result.perimeters.map(p => p.t_h)))
  }, [result])

  // Novo result (ou mapa ainda a carregar o estilo) — construção completa
  useEffect(() => {
    const map = mapRef.current
    if (!map || !result) return
    const onReady = () => initSimulationLayers(map, result, { layer, opacity, visiblePerimeters, showArrows })
    if (map.isStyleLoaded()) onReady()
    else map.once('styledata', onReady)
  }, [result]) // eslint-disable-line

  // Mudanças de camada/transparência/visibilidade sobre o MESMO result —
  // actualização leve, nunca reconstrói sources (ver updateSimulationLayerStyle)
  useEffect(() => {
    const map = mapRef.current
    if (!map || !result || !map.isStyleLoaded()) return
    updateSimulationLayerStyle(map, result, { layer, opacity, visiblePerimeters, showArrows })
  }, [layer, opacity, visiblePerimeters, showArrows]) // eslint-disable-line

  function togglePerimeter(t_h) {
    setVisiblePerimeters(prev => {
      const next = new Set(prev)
      if (next.has(t_h)) next.delete(t_h); else next.add(t_h)
      return next
    })
  }

  function pickMode(mode) {
    const draw = drawRef.current
    if (!draw) return
    clearInterval(pollRef.current)
    // draw.clear()/setMode() na instância existente — reinstanciar via
    // _attachDraw() só é necessário a seguir a um map.setStyle() (ver
    // efeito de basemap/tema), que destrói as sources por baixo da
    // instância; aqui não houve mudança de estilo nenhuma, a instância
    // e as suas sources continuam intactas.
    draw.clear()
    setIgnitionPoints([])
    setJobStatus(null)
    setResult(null)
    setError(null)
    draw.setMode(mode)
    setDrawMode(mode)
  }

  function handleReset() {
    const draw = drawRef.current
    if (!draw) return
    clearInterval(pollRef.current)
    draw.clear()
    setIgnitionPoints([])
    setDrawMode(null)
    setJobStatus(null)
    setResult(null)
    setError(null)
  }

  function handleImportGeoJSON(text) {
    const draw = drawRef.current
    if (!draw) return
    clearInterval(pollRef.current)
    try {
      const { points, feature } = parseIgnitionGeoJSON(text)
      draw.clear()
      const [{ id, valid }] = draw.addFeatures([feature])
      if (!valid) throw new Error('geometria inválida')
      setIgnitionPoints(points)
      draw.setMode('select')
      draw.selectFeature(id)
      setDrawMode('select')
      setJobStatus(null)
      setResult(null)
      setError(null)
    } catch (e) {
      setError(`Importação falhou: ${e.message}`)
    }
  }

  function startPolling(jobId) {
    pollRef.current = setInterval(async () => {
      try {
        const job = await getFreeSimulationJob(apiKey, jobId)
        setJobStatus(job.status)
        if (job.status === 'done') {
          clearInterval(pollRef.current)
          setResult(job.result)
        } else if (job.status === 'failed') {
          clearInterval(pollRef.current)
          setError(job.error_message || 'Simulação falhou')
        }
      } catch (e) {
        clearInterval(pollRef.current)
        setError(e.message)
      }
    }, 2000)
  }

  useEffect(() => () => clearInterval(pollRef.current), [])

  function handleWeatherStreamChange(text, filename) {
    setWeatherStreamText(text)
    setWeatherStreamFilename(filename)
    if (text) setUseGusts(false) // Weather Stream não tem coluna de rajada
  }

  function handleFuelMoistureTableChange(text, filename) {
    setFuelMoistureTableText(text)
    setFuelMoistureTableFilename(filename)
    if (text) setFuelMoistureScenario(null) // mutuamente exclusivo
  }

  function handleFuelMoistureScenarioChange(value) {
    setFuelMoistureScenario(value)
    if (value) { setFuelMoistureTableText(null); setFuelMoistureTableFilename(null) }
  }

  async function handleSimulate() {
    setJobStatus('pending')
    setResult(null)
    setError(null)
    try {
      const job = await postFreeSimulate(apiKey, {
        ignitionPoints, duration_h: durationH, useGusts, fuelMoistureScenario,
        weatherStreamText, fuelMoistureTableText,
      })
      setJobStatus(job.status)
      startPolling(job.job_id)
    } catch (e) {
      setJobStatus(null)
      setError(e.message)
    }
  }

  const isRunning = jobStatus === 'pending' || jobStatus === 'running'
  const hasIgnition = ignitionPoints.length > 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>

      <div className="breadcrumb" style={{ flexShrink: 0 }}>
        <span>Simulador</span>
      </div>

      {/* Mapa */}
      <div style={{ flex: '0 0 60%', position: 'relative' }}>
        <div ref={containerRef} style={{ width: '100%', height: '100%' }} />

        <div style={{
          position: 'absolute', top: 10, left: 10, zIndex: 10,
          display: 'flex', flexDirection: 'column', gap: 6,
        }}>
          <div className="map-overlay-panel" style={{
            display: 'flex', gap: 4, borderRadius: 4, padding: 4,
          }}>
            <button className={`btn btn-ghost${drawMode === 'point' ? ' active' : ''}`}
              disabled={!mapReady}
              style={{ fontSize: 10, padding: '3px 8px' }}
              onClick={() => pickMode('point')}>
              ● Ponto
            </button>
            <button className={`btn btn-ghost${drawMode === 'linestring' ? ' active' : ''}`}
              disabled={!mapReady}
              style={{ fontSize: 10, padding: '3px 8px' }}
              onClick={() => pickMode('linestring')}>
              ╱ Linha
            </button>
            <button className="btn btn-ghost" disabled={!hasIgnition}
              style={{ fontSize: 10, padding: '3px 8px' }}
              onClick={handleReset}>
              Limpar
            </button>
            <label className="btn btn-ghost" style={{ fontSize: 10, padding: '3px 8px', cursor: mapReady ? 'pointer' : 'default', opacity: mapReady ? 1 : 0.5 }}>
              ⬆ Importar
              <input type="file" accept=".geojson,.json" disabled={!mapReady} hidden
                onChange={e => {
                  const file = e.target.files?.[0]
                  if (!file) return
                  const reader = new FileReader()
                  reader.onload = () => handleImportGeoJSON(reader.result)
                  reader.readAsText(file)
                  e.target.value = '' // permite reimportar o mesmo ficheiro
                }} />
            </label>
          </div>
          {drawMode === 'point' && (
            <div className="hint map-overlay-panel" style={{ fontSize: 10, fontFamily: 'var(--font-mono)', padding: '4px 8px', borderRadius: 4 }}>
              Clique no mapa para marcar o ponto de ignição
            </div>
          )}
          {drawMode === 'linestring' && (
            <div className="hint map-overlay-panel" style={{ fontSize: 10, fontFamily: 'var(--font-mono)', padding: '4px 8px', borderRadius: 4 }}>
              Clique para adicionar vértices, duplo clique para terminar a linha
            </div>
          )}
          {drawMode === 'select' && hasIgnition && (
            <div className="hint map-overlay-panel" style={{ fontSize: 10, fontFamily: 'var(--font-mono)', padding: '4px 8px', borderRadius: 4 }}>
              Arraste para ajustar a posição da ignição
            </div>
          )}
        </div>

        <div style={{
          position: 'absolute', top: 10, right: 10, zIndex: 10,
          display: 'flex', flexDirection: 'column', gap: 6,
        }}>
          <div className="map-overlay-panel" style={{ display: 'flex', gap: 4, borderRadius: 4, padding: 4 }}>
            {['osm', 'satellite', 'topo'].map(b => (
              <button key={b} className={`btn btn-ghost${basemap === b ? ' active' : ''}`}
                style={{ fontSize: 10, padding: '3px 8px' }}
                onClick={() => setBasemap(b)}>
                {BASEMAP_LABEL[b]}
              </button>
            ))}
          </div>

          {result && (
            <>
              <div className="map-overlay-panel" style={{ display: 'flex', gap: 4, borderRadius: 4, padding: 4 }}>
                {Object.entries(COLOR_LABELS).map(([k, label]) => (
                  <button key={k} className={`btn btn-ghost${layer === k ? ' active' : ''}`}
                    style={{ fontSize: 9, padding: '3px 6px' }}
                    onClick={() => setLayer(k)}>
                    {label.split(' ')[0]}
                  </button>
                ))}
              </div>
              <div className="map-overlay-panel" style={{
                display: 'flex', alignItems: 'center', gap: 6,
                borderRadius: 4, padding: '4px 8px',
              }}>
                <span style={{ fontSize: 9, color: 'var(--muted)', fontFamily: 'var(--font-mono)' }}>TRANSP</span>
                <input type="range" min={0} max={1} step={0.05}
                  value={opacity} onChange={e => setOpacity(parseFloat(e.target.value))}
                  style={{ width: 80, cursor: 'pointer' }} />
              </div>
              <div className="map-overlay-panel" style={{
                display: 'flex', alignItems: 'center', gap: 6,
                borderRadius: 4, padding: '4px 8px',
              }}>
                <label className="filter-check" style={{ fontSize: 9, fontFamily: 'var(--font-mono)' }}>
                  <input type="checkbox" checked={showArrows}
                    onChange={e => setShowArrows(e.target.checked)} />
                  SETAS DE PROPAGAÇÃO
                </label>
              </div>
              <Legend stops={COLOR_STOPS[layer]} label={COLOR_LABELS[layer]} />

              <div className="map-overlay-panel" style={{
                borderRadius: 4, padding: '4px 6px',
              }}>
                <div style={{ fontSize: 9, color: 'var(--muted)', fontFamily: 'var(--font-mono)', marginBottom: 3 }}>
                  PERÍMETROS
                </div>
                <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap', maxWidth: 140 }}>
                  {result.perimeters.map((p, i) => {
                    const { color } = perimStyle(i, result.perimeters.length)
                    const on = visiblePerimeters.has(p.t_h)
                    return (
                      <button key={p.t_h}
                        onClick={() => togglePerimeter(p.t_h)}
                        title={`${p.t_h}h — ${on ? 'esconder' : 'mostrar'}`}
                        style={{
                          fontSize: 9, padding: '2px 5px', borderRadius: 3,
                          fontFamily: 'var(--font-mono)', cursor: 'pointer',
                          border: `1px solid ${color}`,
                          background: on ? color : 'transparent',
                          color: on ? '#0d1410' : color,
                          opacity: on ? 1 : 0.6,
                        }}>
                        {p.t_h}h
                      </button>
                    )
                  })}
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Painel inferior */}
      <div style={{
        flex: '0 0 40%', overflowY: 'auto', borderTop: '1px solid var(--border)',
        padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 12,
      }}>

        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)', marginBottom: 4 }}>
              DURAÇÃO
            </div>
            <DurationSelect value={durationH} onChange={setDurationH} />
          </div>

          <div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)', marginBottom: 4 }}>
              HUMIDADE COMBUSTÍVEL
            </div>
            <FuelMoistureScenarioSelect
              value={fuelMoistureScenario}
              onChange={handleFuelMoistureScenarioChange}
              disabled={isRunning || !!fuelMoistureTableFilename}
            />
          </div>

          <FileTextInput
            label="HUMIDADES INICIAIS (.FMS)"
            accept=".txt,.fms"
            filename={fuelMoistureTableFilename}
            onChange={handleFuelMoistureTableChange}
            disabled={isRunning || !!fuelMoistureScenario}
          />

          <FileTextInput
            label="WEATHER STREAM (.WXS)"
            accept=".txt,.wxs"
            filename={weatherStreamFilename}
            onChange={handleWeatherStreamChange}
            disabled={isRunning}
          />

          <label className="filter-check" style={{ alignSelf: 'flex-end', marginBottom: 6 }}
            title={weatherStreamFilename ? 'Weather Stream não tem coluna de rajada' : undefined}>
            <input
              type="checkbox"
              checked={useGusts}
              disabled={isRunning || !!weatherStreamFilename}
              onChange={e => setUseGusts(e.target.checked)}
            />
            Usar rajadas (Open-Meteo)
          </label>

          <button
            className="btn btn-primary"
            disabled={isRunning || !hasIgnition}
            onClick={handleSimulate}
            style={{ padding: '6px 18px', alignSelf: 'flex-end' }}
          >
            {isRunning
              ? <><span className="dot" style={{ marginRight: 6 }} />A calcular…</>
              : '▶ Simular'}
          </button>

          {(hasIgnition || result) && (
            <button
              className="btn btn-ghost"
              onClick={handleReset}
              style={{ padding: '6px 18px', alignSelf: 'flex-end' }}
            >
              ↺ Reiniciar
            </button>
          )}

          {!hasIgnition && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--warn)' }}>
              Desenhe um ponto ou linha de ignição no mapa
            </span>
          )}
        </div>

        {error && (
          <div style={{ color: 'var(--danger)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
            ✗ {error}
          </div>
        )}

        {result && <ResultsTable perimeters={result.perimeters} weatherHourly={result.weather_hourly} />}

        {result && (
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-ghost" style={{ fontSize: 11, padding: '5px 12px' }}
              onClick={() => downloadGeoJSON(result.pixel_grid, `grelha_ignicao_${Date.now()}.geojson`)}>
              ⬇ Exportar grelha
            </button>
            <button className="btn btn-ghost" style={{ fontSize: 11, padding: '5px 12px' }}
              onClick={() => downloadGeoJSON(perimetersToFeatureCollection(result.perimeters), `perimetros_ignicao_${Date.now()}.geojson`)}>
              ⬇ Exportar perímetros
            </button>
          </div>
        )}

        {result && (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--dim)', marginTop: 4 }}>
            {`Meteo: ${result.meta.weather_source === 'weather_stream' ? 'Weather Stream' : 'Open-Meteo'} · vento `}
            {result.meta.use_gusts ? 'rajada ' : ''}
            {fmt(msToKmh(result.meta.use_gusts ? result.meta.wind_gust_ms : result.meta.wind_speed_ms), 0)} km/h {fmt(result.meta.wind_dir_deg, 0)}°
            {result.meta.fuel_moisture_source === 'table'
              ? ' · Humidade: tabela FARSITE (.FMS)'
              : result.meta.fuel_moisture_scenario
                ? ` · Humidade: cenário ${result.meta.fuel_moisture_scenario} (${FUEL_MOISTURE_SCENARIO_LABEL[result.meta.fuel_moisture_scenario]})`
                : ' · Humidade: calculada'}
            {` · Resolução: ${result.meta.resolution_m}m`}
          </div>
        )}
      </div>
    </div>
  )
}
