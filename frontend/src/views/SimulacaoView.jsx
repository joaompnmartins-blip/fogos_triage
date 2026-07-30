import { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { fetchFireDetail, postSimulate, getSimulationJob } from '../api'
import { fmt, fmtDateTime, FUEL_MOISTURE_SCENARIO_LABEL } from '../constants'
import {
  msToKmh,
  initSimulationLayers, updateSimulationLayerStyle,
  downloadGeoJSON, perimetersToFeatureCollection,
} from '../components/SimulationMapLayers'
import { ResultsTable, DurationSelect, FuelMoistureScenarioSelect, FileTextInput } from '../components/SimulationPanels'
import { SimulationOverlayControls } from '../components/SimulationOverlayControls'
import { useResizableBottomPanel, ResizeHandle } from '../components/useResizableBottomPanel'
import {
  basemapStyle, addFuelModelLayer, setFuelModelLayerVisible, setFuelModelLayerOpacity,
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
  const [useWindninja, setUseWindninja] = useState(false)
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
  // `containerRef` já é o div do mapa nesta vista — o do hook (que mede a
  // altura total disponível) fica como rootRef.
  const { containerRef: rootRef, panelStyle, onPointerDown, reset } =
    useResizableBottomPanel('ft_simulacao_bottom_h')

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
        useWindninja,
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
    <div ref={rootRef} style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>

      <div className="breadcrumb" style={{ flexShrink: 0 }}>
        <Link to="/lista">Ocorrências</Link>
        <span className="sep">›</span>
        <Link to={`/fogo/${fireId}`}>{[fire.municipality, fire.district].filter(Boolean).join(', ')}</Link>
        <span className="sep">›</span>
        <span>Simulação</span>
      </div>

      {/* Mapa */}
      <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
        <div ref={containerRef} style={{ width: '100%', height: '100%' }} />

        <SimulationOverlayControls
          basemap={basemap} setBasemap={setBasemap}
          showFuelModel={showFuelModel} setShowFuelModel={setShowFuelModel}
          fuelModelOpacity={fuelModelOpacity} setFuelModelOpacity={setFuelModelOpacity}
          mapZoom={mapZoom}
          result={result} layer={layer} setLayer={setLayer}
          opacity={opacity} setOpacity={setOpacity}
          showArrows={showArrows} setShowArrows={setShowArrows}
          visiblePerimeters={visiblePerimeters} togglePerimeter={togglePerimeter}
        />
      </div>

      <ResizeHandle onPointerDown={onPointerDown} onDoubleClick={reset}
        title="Arraste para redimensionar; duplo clique repõe" />

      {/* Painel inferior */}
      <div style={{
        ...panelStyle,
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

          {/* Vento de terreno. O aviso de tempo usa os números medidos
              (ver WINDNINJA_PLAN.md): ~6,5 s por hora simulada, o que dá
              +26 s numa simulação de 3h. */}
          <label className="filter-check" style={{ alignSelf: 'flex-end', marginBottom: 6 }}
            title="Ajusta o vento ao relevo (WindNinja): aceleração em cumeadas, abrigo em vales. Acrescenta ~6 s por hora simulada.">
            <input
              type="checkbox"
              checked={useWindninja}
              disabled={isRunning}
              onChange={e => setUseWindninja(e.target.checked)}
            />
            Vento de terreno (WindNinja)
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
            {result.meta.wind_field_source === 'windninja'
              ? ` · Vento: terreno (${result.meta.wind_field_runs} corridas)`
              : result.meta.use_windninja
                ? ''
                : ' · Vento: uniforme'}
          </div>
        )}
        {/* Pedido e não cumprido: sem isto o utilizador marcava a caixa,
            o sidecar falhava, e a simulação corria com vento uniforme sem
            que nada o dissesse fora do meta. Falhar aberto não pode ser
            falhar em silêncio. */}
        {result && result.meta.use_windninja
          && result.meta.wind_field_source !== 'windninja' && (
          <div style={{
            fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--warn)',
            marginTop: 4,
          }}>
            Vento de terreno pedido mas indisponível — simulação corrida com
            vento uniforme.
          </div>
        )}

      </div>
    </div>
  )
}
