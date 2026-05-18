import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, NavLink, Navigate, useLocation } from 'react-router-dom'
import MapView from './views/MapView'
import ListaView from './views/ListaView'
import DetalheView from './views/DetalheView'
import HistoricoView from './views/HistoricoView'
import { fetchHealth } from './api'

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
          className="modal-input"
          type="password"
          placeholder="ft_..."
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && value.trim() && onSave(value.trim())}
          autoFocus
        />
        <div className="modal-actions">
          <button
            className="btn-primary"
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
// Header
// ---------------------------------------------------------------------------

function Header({ health, apiKey, onChangeKey }) {
  const ok = health && health.database_ok
  const lastSeen = health?.worker_last_seen_at
    ? new Date(health.worker_last_seen_at).toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' })
    : null

  return (
    <header className="header">
      <span className="header-logo">F.T.</span>
      <span className="header-title">Fogos Triage</span>
      <span className="header-sep" />
      <div className="header-status">
        <span className={`status-dot ${health === null ? '' : ok ? 'ok' : 'err'}`} />
        <span>{health === null ? 'a ligar…' : ok ? 'online' : 'erro BD'}</span>
        {lastSeen && <span style={{ color: 'var(--dim)' }}>· {lastSeen}</span>}
      </div>
      {apiKey && (
        <button className="btn-ghost" onClick={onChangeKey} title="Alterar chave de API">
          API KEY
        </button>
      )}
    </header>
  )
}

// ---------------------------------------------------------------------------
// Navigation (tabs + breadcrumbs)
// ---------------------------------------------------------------------------

function NavTabs() {
  const location = useLocation()
  const isDetail = location.pathname.match(/^\/fogo\/([^/]+)$/)
  const isHistory = location.pathname.match(/^\/fogo\/([^/]+)\/historico$/)
  const fireId = (isDetail?.[1] || isHistory?.[1] || '').slice(0, 12)

  const tabs = (
    <>
      <NavLink to="/mapa">
        {({ isActive }) => (
          <button className={`nav-tab${isActive ? ' active' : ''}`}>Mapa</button>
        )}
      </NavLink>
      <NavLink to="/lista">
        {({ isActive }) => (
          <button className={`nav-tab${isActive || (isDetail && !isHistory) || isHistory ? ' active' : ''}`} style={isDetail || isHistory ? { color: 'var(--text)' } : {}}>
            Lista
          </button>
        )}
      </NavLink>
    </>
  )

  return (
    <nav className="nav-tabs">
      {tabs}
      {(isDetail || isHistory) && (
        <>
          <span className="nav-sep">›</span>
          <span className={`nav-crumb${isHistory ? '' : ' active'}`}>
            #{fireId}…
          </span>
          {isHistory && (
            <>
              <span className="nav-sep">›</span>
              <span className="nav-crumb active">Histórico</span>
            </>
          )}
        </>
      )}
    </nav>
  )
}

// ---------------------------------------------------------------------------
// App shell
// ---------------------------------------------------------------------------

function AppShell({ apiKey, onChangeKey, health }) {
  return (
    <div className="layout">
      <Header health={health} apiKey={apiKey} onChangeKey={onChangeKey} />
      <NavTabs />
      <div className="content" id="main-content">
        <Routes>
          <Route path="/" element={<Navigate to="/mapa" replace />} />
          <Route path="/mapa" element={<MapView apiKey={apiKey} />} />
          <Route path="/lista" element={<ListaView apiKey={apiKey} />} />
          <Route path="/fogo/:fireId" element={<DetalheView apiKey={apiKey} />} />
          <Route path="/fogo/:fireId/historico" element={<HistoricoView apiKey={apiKey} />} />
          <Route path="*" element={<Navigate to="/mapa" replace />} />
        </Routes>
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

  const saveKey = (key) => {
    localStorage.setItem('ft_api_key', key)
    setApiKey(key)
    setShowModal(false)
  }

  // Poll health every 30s
  useEffect(() => {
    const check = () => fetchHealth().then(setHealth)
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
        />
      )}
    </BrowserRouter>
  )
}
