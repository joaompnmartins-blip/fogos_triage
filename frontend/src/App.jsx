import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, NavLink, Navigate, useLocation } from 'react-router-dom'
import MapView from './views/MapView'
import ListaView from './views/ListaView'
import DetalheView from './views/DetalheView'
import HistoricoView from './views/HistoricoView'
import SimulacaoView from './views/SimulacaoView'
import { fetchHealth } from './api'

// ---------------------------------------------------------------------------
// Clock — live time for sidebar footer
// ---------------------------------------------------------------------------

function Clock() {
  const [time, setTime] = useState(new Date())
  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  return <>{time.toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</>
}

// ---------------------------------------------------------------------------
// API Key modal
// ---------------------------------------------------------------------------

function KeyModal({ onSave }) {
  const [value, setValue] = useState('')
  return (
    <div className="modal-overlay">
      <div className="modal">
        <div className="modal-title">Chave de API</div>
        <p className="modal-desc">
          Introduz a chave de API para aceder ao sistema de triagem.
          A chave fica guardada localmente no browser.
        </p>
        <input
          className="form-input"
          type="password"
          placeholder="ft_..."
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && value.trim() && onSave(value.trim())}
          autoFocus
        />
        <div className="modal-actions">
          <button
            className="btn btn-primary"
            disabled={!value.trim()}
            onClick={() => onSave(value.trim())}
          >
            Guardar
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------

function Sidebar({ health, onChangeKey, apiKey, theme, onToggleTheme }) {
  const location = useLocation()
  const isListArea = location.pathname.startsWith('/lista') || location.pathname.startsWith('/fogo')
  const ok = health && health.database_ok
  const workerTs = health?.worker_last_seen_at
    ? new Date(health.worker_last_seen_at).toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' })
    : null

  const footerBtn = {
    background: 'none', border: 'none', color: 'var(--dim)',
    fontFamily: 'var(--font-mono)', fontSize: 9, cursor: 'pointer',
    padding: 0, letterSpacing: '.1em', display: 'block', marginTop: 6,
  }

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-tag">
          <span className="dot" />
          <span>ICNF / GFR</span>
        </div>
        <div className="sidebar-title">Triagem<span>Ocorrências</span></div>
      </div>

      <nav className="nav">
        <NavLink
          to="/mapa"
          className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
        >
          <span className="nav-icon">◎</span>
          <span>Mapa</span>
        </NavLink>
        <NavLink
          to="/lista"
          className={() => `nav-item${isListArea ? ' active' : ''}`}
        >
          <span className="nav-icon">≡</span>
          <span>Ocorrências</span>
        </NavLink>
        <div className="nav-sep" />
      </nav>

      <div className="sidebar-footer">
        <div>
          <span
            className="dot"
            style={!ok ? { background: 'var(--danger)', boxShadow: 'none' } : {}}
          />
          {ok ? 'SISTEMA OK' : health === null ? 'A LIGAR…' : 'BD OFFLINE'}
        </div>
        {workerTs && <div style={{ marginLeft: 11 }}>WORKER {workerTs}</div>}
        <div style={{ marginTop: 4, color: 'var(--dim)' }}><Clock /></div>
        <button style={footerBtn} onClick={onToggleTheme}>
          {theme === 'dark' ? '◑ TEMA CLARO' : '◐ TEMA ESCURO'}
        </button>
        {apiKey && (
          <button style={footerBtn} onClick={onChangeKey}>ALTERAR KEY</button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Topbar — dynamic title from route
// ---------------------------------------------------------------------------

function Topbar() {
  const location = useLocation()
  const isDetail = location.pathname.match(/^\/fogo\/([^/]+)$/)
  const isHistory = location.pathname.match(/^\/fogo\/([^/]+)\/historico$/)
  const isSimulation = location.pathname.match(/^\/fogo\/([^/]+)\/simulacao$/)

  let title, sub
  if (isSimulation) {
    title = 'Simulação'
    sub = `#${isSimulation[1]}`
  } else if (isHistory) {
    title = 'Histórico'
    sub = `#${isHistory[1]}`
  } else if (isDetail) {
    title = 'Ocorrência'
    sub = `#${isDetail[1]}`
  } else if (location.pathname.startsWith('/mapa')) {
    title = 'Mapa'
    sub = 'Portugal Continental'
  } else {
    title = 'Ocorrências Ativas'
    sub = null
  }

  return (
    <div className="topbar">
      <div className="topbar-left">
        <div>
          <div className="page-label">{title}</div>
          {sub && <div className="page-sub">{sub}</div>}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// App shell
// ---------------------------------------------------------------------------

function AppShell({ apiKey, onChangeKey, health, theme, onToggleTheme }) {
  return (
    <div id="shell">
      <Sidebar health={health} onChangeKey={onChangeKey} apiKey={apiKey} theme={theme} onToggleTheme={onToggleTheme} />
      <div className="main">
        <Topbar />
        <div className="content">
          <Routes>
            <Route path="/" element={<Navigate to="/mapa" replace />} />
            <Route path="/mapa" element={<MapView apiKey={apiKey} />} />
            <Route path="/lista" element={<ListaView apiKey={apiKey} />} />
            <Route path="/fogo/:fireId" element={<DetalheView apiKey={apiKey} />} />
            <Route path="/fogo/:fireId/historico" element={<HistoricoView apiKey={apiKey} />} />
            <Route path="/fogo/:fireId/simulacao" element={<SimulacaoView apiKey={apiKey} />} />
            <Route path="*" element={<Navigate to="/mapa" replace />} />
          </Routes>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

export default function App() {
  const [apiKey, setApiKey] = useState(localStorage.getItem('ft_api_key') || '')
  const [showModal, setShowModal] = useState(!localStorage.getItem('ft_api_key'))
  const [health, setHealth] = useState(null)
  const [theme, setTheme] = useState(() => localStorage.getItem('ft_theme') || 'light')

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('ft_theme', theme)
  }, [theme])

  const saveKey = (key) => {
    localStorage.setItem('ft_api_key', key)
    setApiKey(key)
    setShowModal(false)
  }

  useEffect(() => {
    const check = () => fetchHealth().then(setHealth).catch(() => {})
    check()
    const id = setInterval(check, 30_000)
    return () => clearInterval(id)
  }, [])

  return (
    <BrowserRouter>
      {showModal && <KeyModal onSave={saveKey} />}
      {apiKey && (
        <AppShell
          apiKey={apiKey}
          onChangeKey={() => setShowModal(true)}
          health={health}
          theme={theme}
          onToggleTheme={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
        />
      )}
    </BrowserRouter>
  )
}
