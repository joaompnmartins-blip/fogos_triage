import { useCallback, useEffect, useRef, useState } from 'react'

// Painel inferior redimensionável das vistas de simulação.
//
// Antes o mapa era `flex: '0 0 60%'` e o painel `flex: '0 0 40%'` fixos:
// a 1366×768 dava 414px de mapa e 276px de painel, mesmo antes de haver
// resultado nenhum para mostrar (ver SIMULATION_UI_PLAN.md). Agora:
//
//   - sem altura escolhida, o painel ajusta-se ao conteúdo até um tecto
//     (`MAX_FRACTION`) — antes de correr são só os controlos, e o mapa
//     fica com o resto;
//   - o utilizador pode arrastar a pega e essa altura fica guardada em
//     localStorage, por vista.
//
// O mapa passa a `flex: 1` com `minHeight: 0` (sem o minHeight, um filho
// flex não encolhe abaixo do conteúdo e o painel voltaria a empurrá-lo
// para fora do ecrã).

const MIN_PX = 72
const MAX_FRACTION = 0.7   // nunca deixar o mapa com menos de 30%
const AUTO_MAX_FRACTION = '45%'  // tecto enquanto ninguém arrastou

export function useResizableBottomPanel(storageKey) {
  const containerRef = useRef(null)
  const [height, setHeight] = useState(() => {
    const raw = typeof localStorage !== 'undefined' && localStorage.getItem(storageKey)
    const n = raw ? Number(raw) : NaN
    return Number.isFinite(n) && n >= MIN_PX ? n : null
  })
  const draggingRef = useRef(false)

  const onPointerDown = useCallback(e => {
    e.preventDefault()
    draggingRef.current = true
  }, [])

  useEffect(() => {
    function onMove(e) {
      if (!draggingRef.current || !containerRef.current) return
      const box = containerRef.current.getBoundingClientRect()
      const next = Math.min(
        Math.max(box.bottom - e.clientY, MIN_PX),
        box.height * MAX_FRACTION,
      )
      setHeight(next)
    }
    function onUp() {
      if (!draggingRef.current) return
      draggingRef.current = false
      // Só se persiste no fim do arrasto — escrever em cada mousemove
      // seria dezenas de escritas por segundo em localStorage.
      setHeight(h => {
        if (h != null) localStorage.setItem(storageKey, String(Math.round(h)))
        return h
      })
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [storageKey])

  const reset = useCallback(() => {
    localStorage.removeItem(storageKey)
    setHeight(null)
  }, [storageKey])

  const panelStyle = height != null
    ? { height, flexShrink: 0, overflowY: 'auto' }
    : { flex: '0 0 auto', maxHeight: AUTO_MAX_FRACTION, overflowY: 'auto' }

  return { containerRef, panelStyle, onPointerDown, reset, isCustom: height != null }
}

// Pega de arrasto entre o mapa e o painel. Alvo de 7px (fino de mais e
// não se acerta com o rato), com uma marca visual ao centro.
export function ResizeHandle({ onPointerDown, onDoubleClick, title }) {
  const [hover, setHover] = useState(false)
  return (
    <div
      onMouseDown={onPointerDown}
      onDoubleClick={onDoubleClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      title={title}
      style={{
        height: 7, flexShrink: 0, cursor: 'row-resize',
        borderTop: '1px solid var(--border)',
        background: hover ? 'var(--border)' : 'transparent',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        transition: 'background .12s',
      }}>
      <div style={{
        width: 36, height: 2, borderRadius: 1,
        background: hover ? 'var(--muted)' : 'var(--border)',
      }} />
    </div>
  )
}
