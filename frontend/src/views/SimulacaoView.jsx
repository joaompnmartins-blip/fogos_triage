import { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { fetchFireDetail, postSimulate, getSimulationJob } from '../api'
import { fmt, fmtDateTime, FUEL_MOISTURE_SCENARIO_LABEL } from '../constants'
import {
  COLOR_LABELS, COLOR_STOPS, msToKmh, perimStyle, arrowsHour,
  initSimulationLayers, updateSimulationLayerStyle,
  downloadGeoJSON, perimetersToFeatureCollection,
} from '../components/SimulationMapLayers'
import { Legend, ResultsTable, DurationSelect, FuelMoistureScenarioSelect, FileTextInput, FuelModelLegend } from '../components/SimulationPanels'
import {
  basemapStyle, BASEMAP_LABEL, addFuelModelLayer, setFuelModelLayerVisible, setFuelModelLayerOpacity,
  FUEL_MODEL_MIN_ZOOM,
} from '../basemaps'

export default function SimulacaoView({ apiKey, theme }) {
  const { fireId } = useParams()
  const mapRef = useRef(null)
  const containerRef = useRef(null)
  const setupLayersFnRef = useRef(null)  // reposição pós-style.load, ver abaixo

  const [fire, setFire] = useState(null)
  const [basemap, setBasemap] = useState('osm')
  const [layer, setLayer] = useState('ros')
  const [opacity, setOpacity] = useState(0.75)
  const [durationH, setDurationH] = useState(3)
  const [startTime, setStartTime] = useState('')
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
  const [showFuelModel, setShowFuelModel] = useState(false)
  const [fuelModelOpacity, setFuelModelOpacity] = useState(0.7)
  // Zoom actual do mapa — só para saber se o overlay de combustível
  // tem tiles a este nível (ver FUEL_MODEL_MIN_ZOOM em basemaps.js).
  const [mapZoom, setMapZoom] = useState(0)
  const showFuelModelRef = useRef(false)
  const fuelModelOpacityRef = useRef(0.7)
  const pollRef = useRef(null)

  useEffect(() => {
    fetchFireDetail(apiKey, fireId)
      .then(setFire)
      .catch(e => setError(e.message))
  }, [apiKey, fireId])

  // Repõe o que um estilo novo destrói (overlay de combustível + camadas da
  // simulação). Guardado numa ref e reatribuído em cada render, para o
  // handler de 'style.load' — registado uma única vez — ver sempre o
  // `result`/`layer`/`opacity` actuais. Mesmo padrão do MapView.
  // (O marcador da ocorrência é um maplibregl.Marker, elemento DOM, não uma
  // camada de estilo — sobrevive ao setStyle sozinho.)
  setupLayersFnRef.current = () => {
    const map = mapRef.current
    if (!map) return
    addFuelModelLayer(map, { visible: showFuelModelRef.current, opacity: fuelModelOpacityRef.current })
    if (result) initSimulationLayers(map, result, { layer, opacity, visiblePerimeters, showArrows })
  }

  useEffect(() => {
    if (!containerRef.current || mapRef.current || !fire) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: basemapStyle(basemap, theme),
      center: [fire.longitude, fire.latitude],
      zoom: 12,
      attributionControl: false,
    })
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right')
    // Zoom vive fora do React; espelha-se em estado só para a UI poder
    // avisar quando o overlay de combustível não tem tiles a este nível.
    setMapZoom(map.getZoom())
    map.on('zoomend', () => setMapZoom(map.getZoom()))
    new maplibregl.Marker({ color: '#ef4444' })
      .setLngLat([fire.longitude, fire.latitude])
      .addTo(map)
    // Registado UMA vez: dispara no carregamento inicial e em cada
    // setStyle({ diff: false }) do efeito de basemap (ver lá porquê).
    map.on('style.load', () => setupLayersFnRef.current?.())
    mapRef.current = map
    return () => { map.remove(); mapRef.current = null }
  }, [fire])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    // `{ diff: false }` é ESSENCIAL, não uma optimização: com o valor por
    // omissão (diff: true) o MapLibre tenta transformar o estilo actual no
    // novo e **nunca volta a disparar 'style.load'** — o overlay de
    // combustível e as camadas da simulação eram destruídos e nada os
    // repunha. Medido directamente:
    //     setStyle(estilo)                -> style.load NÃO dispara, camadas perdidas
    //     setStyle(estilo, {diff:false})  -> style.load dispara, camadas repostas
    // (Antes usava-se `once('styledata')` como remendo, mas esse dispara a
    // meio do carregamento de estilos vector como o OSM/liberty, que ainda
    // substitui sources depois disso — as camadas repostas voltavam a
    // desaparecer sem aviso.)
    map.setStyle(basemapStyle(basemap, theme), { diff: false })
  }, [basemap, theme])

  // Overlay do modelo de combustível — independente de result, actualizado
  // sem reconstruir nada; ref mantida em sincronia para addFuelModelLayer
  // acima saber o valor certo mesmo depois de uma troca de basemap.
  useEffect(() => {
    showFuelModelRef.current = showFuelModel
    const map = mapRef.current
    if (map) setFuelModelLayerVisible(map, showFuelModel)
  }, [showFuelModel])

  useEffect(() => {
    fuelModelOpacityRef.current = fuelModelOpacity
    const map = mapRef.current
    if (map) setFuelModelLayerOpacity(map, fuelModelOpacity)
  }, [fuelModelOpacity])

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

  function startPolling(jobId) {
    pollRef.current = setInterval(async () => {
      try {
        const job = await getSimulationJob(apiKey, jobId)
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
      const job = await postSimulate(apiKey, fireId, {
        duration_h: durationH,
        useGusts,
        fuelMoistureScenario,
        weatherStreamText,
        fuelMoistureTableText,
        startTime,
      })
      setJobStatus(job.status)
      startPolling(job.job_id)
    } catch (e) {
      setJobStatus(null)
      setError(e.message)
    }
  }

  if (!fire) return <div className="state-center" style={{ height: '100%' }}>A carregar…</div>

  const triage = fire.triage
  const isRunning = jobStatus === 'pending' || jobStatus === 'running'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>

      <div className="breadcrumb" style={{ flexShrink: 0 }}>
        <Link to="/lista">Ocorrências</Link>
        <span className="sep">›</span>
        <Link to={`/fogo/${fireId}`}>{[fire.municipality, fire.district].filter(Boolean).join(', ')}</Link>
        <span className="sep">›</span>
        <span>Simulação</span>
      </div>

      {/* Mapa */}
      <div style={{ flex: '0 0 60%', position: 'relative' }}>
        <div ref={containerRef} style={{ width: '100%', height: '100%' }} />

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

          <div className="map-overlay-panel" style={{
            display: 'flex', alignItems: 'center', gap: 6,
            borderRadius: 4, padding: '4px 8px',
          }}>
            <label className="filter-check" style={{ fontSize: 9, fontFamily: 'var(--font-mono)' }}>
              <input type="checkbox" checked={showFuelModel}
                onChange={e => setShowFuelModel(e.target.checked)} />
              MODELOS DE COMBUSTÍVEL
            </label>
          </div>
          {showFuelModel && mapZoom < FUEL_MODEL_MIN_ZOOM && (
            <div className="map-overlay-panel" style={{
              borderRadius: 4, padding: '4px 8px', width: 210,
              fontSize: 9, fontFamily: 'var(--font-mono)',
              color: 'var(--warn)', lineHeight: 1.35,
            }}>
              Aproxime o mapa para ver os modelos de combustível
            </div>
          )}
          {showFuelModel && mapZoom >= FUEL_MODEL_MIN_ZOOM && (
            <>
              <div className="map-overlay-panel" style={{
                display: 'flex', alignItems: 'center', gap: 6,
                borderRadius: 4, padding: '4px 8px',
              }}>
                <span style={{ fontSize: 9, color: 'var(--muted)', fontFamily: 'var(--font-mono)' }}>TRANSP</span>
                <input type="range" min={0} max={1} step={0.05}
                  value={fuelModelOpacity} onChange={e => setFuelModelOpacity(parseFloat(e.target.value))}
                  style={{ width: 80, cursor: 'pointer' }} />
              </div>
              <FuelModelLegend />
            </>
          )}

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
                {/* A hora vai no rótulo: as setas são o campo de propagação
                    de UM instante (a meteo dessa hora), não da simulação
                    toda — sem isto ficava por dizer qual. */}
                <label className="filter-check" style={{ fontSize: 9, fontFamily: 'var(--font-mono)' }}>
                  <input type="checkbox" checked={showArrows}
                    onChange={e => setShowArrows(e.target.checked)} />
                  SETAS DE PROPAGAÇÃO
                  {arrowsHour(result, visiblePerimeters) != null
                    && ` (t=${arrowsHour(result, visiblePerimeters)}h)`}
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
              INÍCIO DA SIMULAÇÃO
            </div>
            <input
              type="datetime-local"
              className="form-input"
              style={{ fontSize: 12, padding: '5px 8px' }}
              value={startTime}
              disabled={isRunning || !!weatherStreamFilename}
              title={weatherStreamFilename ? 'Weather Stream já tem a sua própria linha do tempo' : 'Vazio = agora'}
              onChange={e => setStartTime(e.target.value)}
            />
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
            disabled={isRunning || !triage}
            onClick={handleSimulate}
            style={{ padding: '6px 18px', alignSelf: 'flex-end' }}
          >
            {isRunning
              ? <><span className="dot" style={{ marginRight: 6 }} />A calcular…</>
              : '▶ Simular'}
          </button>

          {!triage && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--warn)' }}>
              Sem triagem — simulação não disponível
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
              onClick={() => downloadGeoJSON(result.pixel_grid, `grelha_${fireId}_${Date.now()}.geojson`)}>
              ⬇ Exportar grelha
            </button>
            <button className="btn btn-ghost" style={{ fontSize: 11, padding: '5px 12px' }}
              onClick={() => downloadGeoJSON(perimetersToFeatureCollection(result.perimeters), `perimetros_${fireId}_${Date.now()}.geojson`)}>
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
            {triage && ` · Triagem: ${fmtDateTime(triage.computed_at)}`}
            {result.meta.start_time && ` · Início: ${fmtDateTime(result.meta.start_time)}`}
            {` · Resolução: ${result.meta.resolution_m}m`}
          </div>
        )}
      </div>
    </div>
  )
}
