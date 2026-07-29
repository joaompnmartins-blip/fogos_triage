import { useState } from 'react'
import { BASEMAP_LABEL, FUEL_MODEL_MIN_ZOOM } from '../basemaps'
import { COLOR_LABELS, COLOR_STOPS, perimStyle, arrowsHour } from './SimulationMapLayers'
import { CollapsibleLegend, LegendRows, FuelModelLegendRows } from './SimulationPanels'

// Coluna de controlos sobre o mapa, partilhada por SimulacaoView e
// SimuladorLivreView — antes estava duplicada nas duas vistas, com nove
// caixas `map-overlay-panel` empilhadas.
//
// Três problemas que esta versão resolve (ver SIMULATION_UI_PLAN.md):
//
// 1. A coluna não tinha limite de altura: com resultado + overlay de
//    combustível ligado, a pilha passava 223px para fora do mapa, por
//    cima da tabela de resultados, e tapava os botões de zoom do
//    MapLibre. Agora a coluna é `maxHeight: 100%` + `overflowY: auto`,
//    o que torna o transbordo estruturalmente impossível.
// 2. Nove caixas separadas gastavam ~135px só em padding, bordas e gaps.
//    Agora é UMA caixa com secções separadas por linhas finas.
// 3. As legendas ocupavam espaço permanente — a de combustível sozinha
//    tinha 260px, 63% da altura do mapa. Agora são colapsáveis, e a de
//    combustível nasce fechada: é uma tabela de referência (22 entradas),
//    consulta-se, não se olha para ela em permanência.

const SECTION_BORDER = '1px solid var(--border)'

function Section({ children, first }) {
  return (
    <div style={{
      padding: '6px 8px',
      borderTop: first ? 'none' : SECTION_BORDER,
    }}>
      {children}
    </div>
  )
}

function OpacityRow({ label, value, onChange }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 5 }}>
      {/* Rótulo específico: havia dois sliders com o mesmo "TRANSP" a
          controlar coisas diferentes (overlay de combustível vs. grelha
          da simulação), lado a lado e indistinguíveis. */}
      <span style={{
        fontSize: 9, color: 'var(--muted)', fontFamily: 'var(--font-mono)',
        flexShrink: 0,
      }}>
        {label}
      </span>
      <input type="range" min={0} max={1} step={0.05}
        value={value} onChange={e => onChange(parseFloat(e.target.value))}
        style={{ width: 72, cursor: 'pointer' }} />
    </div>
  )
}

export function SimulationOverlayControls({
  basemap, setBasemap,
  showFuelModel, setShowFuelModel, fuelModelOpacity, setFuelModelOpacity, mapZoom,
  result, layer, setLayer, opacity, setOpacity,
  showArrows, setShowArrows,
  visiblePerimeters, togglePerimeter,
}) {
  // Combustível fechada por omissão (tabela de referência de 22 linhas);
  // a de outputs aberta, porque são só 5 classes e sem ela não se lê o
  // mapa que se está a ver.
  const [fuelLegendOpen, setFuelLegendOpen] = useState(false)
  const [outputLegendOpen, setOutputLegendOpen] = useState(true)

  const arrowsT = result ? arrowsHour(result, visiblePerimeters) : null

  return (
    <div style={{
      position: 'absolute', top: 10, right: 10, zIndex: 10,
      // O par que impede o transbordo: limitar pelo fundo em vez de só
      // maxHeight faz o limite acompanhar o mapa quando este muda de
      // altura (o painel inferior é redimensionável).
      //
      // Não é `bottom: 10`: os controlos de zoom e a atribuição do
      // MapLibre ficam no canto inferior direito, por baixo desta coluna.
      // Com o painel a chegar ao fundo, voltavam a ficar tapados — foi
      // exactamente o que a medição apanhou. Reserva-se-lhes a faixa.
      bottom: 96,
      display: 'flex', flexDirection: 'column', alignItems: 'flex-end',
      pointerEvents: 'none',
    }}>
      <div className="map-overlay-panel" style={{
        borderRadius: 4, width: 212,
        maxHeight: '100%', overflowY: 'auto',
        pointerEvents: 'auto',
      }}>
        <Section first>
          <div style={{ display: 'flex', gap: 4 }}>
            {['osm', 'satellite', 'topo'].map(b => (
              <button key={b} className={`btn btn-ghost${basemap === b ? ' active' : ''}`}
                style={{ fontSize: 10, padding: '3px 8px', flex: 1 }}
                onClick={() => setBasemap(b)}>
                {BASEMAP_LABEL[b]}
              </button>
            ))}
          </div>
        </Section>

        <Section>
          <label className="filter-check" style={{ fontSize: 9, fontFamily: 'var(--font-mono)' }}>
            <input type="checkbox" checked={showFuelModel}
              onChange={e => setShowFuelModel(e.target.checked)} />
            MODELOS DE COMBUSTÍVEL
          </label>
          {showFuelModel && mapZoom < FUEL_MODEL_MIN_ZOOM && (
            <div style={{
              marginTop: 5, fontSize: 9, fontFamily: 'var(--font-mono)',
              color: 'var(--warn)', lineHeight: 1.35,
            }}>
              Aproxime o mapa para ver os modelos de combustível
            </div>
          )}
          {showFuelModel && mapZoom >= FUEL_MODEL_MIN_ZOOM && (
            <>
              <OpacityRow label="TRANSP. COMBUSTÍVEL" value={fuelModelOpacity}
                onChange={setFuelModelOpacity} />
              <div style={{ marginTop: 5 }}>
                <CollapsibleLegend title="LEGENDA DOS MODELOS"
                  open={fuelLegendOpen} onToggle={() => setFuelLegendOpen(o => !o)}>
                  <FuelModelLegendRows />
                </CollapsibleLegend>
              </div>
            </>
          )}
        </Section>

        {result && (
          <>
            <Section>
              <div style={{ display: 'flex', gap: 4 }}>
                {Object.entries(COLOR_LABELS).map(([k, label]) => (
                  <button key={k} className={`btn btn-ghost${layer === k ? ' active' : ''}`}
                    style={{ fontSize: 9, padding: '3px 6px', flex: 1 }}
                    onClick={() => setLayer(k)}>
                    {label.split(' ')[0]}
                  </button>
                ))}
              </div>
              <OpacityRow label="TRANSP. GRELHA" value={opacity} onChange={setOpacity} />
              <div style={{ marginTop: 5 }}>
                <CollapsibleLegend title={COLOR_LABELS[layer].toUpperCase()}
                  open={outputLegendOpen} onToggle={() => setOutputLegendOpen(o => !o)}>
                  <LegendRows stops={COLOR_STOPS[layer]} />
                </CollapsibleLegend>
              </div>
            </Section>

            <Section>
              {/* A hora vai no rótulo: as setas são o campo de propagação
                  de UM instante (a meteo dessa hora), não da simulação
                  toda — sem isto ficava por dizer qual. */}
              <label className="filter-check" style={{ fontSize: 9, fontFamily: 'var(--font-mono)' }}>
                <input type="checkbox" checked={showArrows}
                  onChange={e => setShowArrows(e.target.checked)} />
                SETAS DE PROPAGAÇÃO{arrowsT != null && ` (t=${arrowsT}h)`}
              </label>
            </Section>

            <Section>
              <div style={{
                fontSize: 9, color: 'var(--muted)',
                fontFamily: 'var(--font-mono)', marginBottom: 4,
              }}>
                PERÍMETROS
              </div>
              <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
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
            </Section>
          </>
        )}
      </div>
    </div>
  )
}
