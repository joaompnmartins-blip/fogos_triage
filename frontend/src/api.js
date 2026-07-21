// Em dev, o Vite faz proxy /api → Railway. Em produção, usa VITE_API_URL direto.
const API_BASE = import.meta.env.DEV
  ? '/api'
  : (import.meta.env.VITE_API_URL || '')

function auth(apiKey) {
  return { Authorization: `Bearer ${apiKey}` }
}

async function get(path, apiKey, params) {
  const url = new URL(`${API_BASE}${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v != null && v !== '') url.searchParams.set(k, v)
    })
  }
  const res = await fetch(url.toString(), {
    headers: apiKey ? auth(apiKey) : {},
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status}: ${text}`)
  }
  return res.json()
}

export async function fetchHealth() {
  try {
    const res = await fetch(`${API_BASE}/health`)
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

export async function fetchFires(apiKey, { limit = 50, cursor, district, minCategory, onlyTriaged } = {}) {
  return get('/fires', apiKey, {
    limit,
    cursor,
    district: district || undefined,
    min_category: minCategory || undefined,
    only_triaged: onlyTriaged ? 'true' : undefined,
  })
}

export async function fetchFiresGeo(apiKey, { minLat = 30, minLng = -32, maxLat = 42.5, maxLng = -5.5 } = {}) {
  return get('/fires/geo/within', apiKey, {
    min_lat: minLat,
    min_lng: minLng,
    max_lat: maxLat,
    max_lng: maxLng,
    only_active: 'true',
  })
}

export async function fetchFireDetail(apiKey, fireId) {
  return get(`/fires/${encodeURIComponent(fireId)}`, apiKey)
}

export async function fetchFireHistory(apiKey, fireId) {
  return get(`/fires/${encodeURIComponent(fireId)}/history`, apiKey)
}

export async function postSimulate(apiKey, fireId, {
  duration_h = 3, wind_speed_ms, wind_direction_deg, useGusts, fuelMoistureScenario, bbox_km,
  weatherStreamText, fuelMoistureTableText,
} = {}) {
  const res = await fetch(`${API_BASE}/simulate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...auth(apiKey) },
    body: JSON.stringify({
      fire_id: fireId,
      duration_h,
      wind_speed_ms: wind_speed_ms || null,
      wind_direction_deg: wind_direction_deg || null,
      use_gusts: !!useGusts,
      fuel_moisture_scenario: fuelMoistureScenario || null,
      bbox_km: bbox_km || null,
      weather_stream_text: weatherStreamText || null,
      fuel_moisture_table_text: fuelMoistureTableText || null,
    }),
  })
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
  return res.json()
}

export async function getSimulationJob(apiKey, jobId) {
  return get(`/jobs/${encodeURIComponent(jobId)}`, apiKey)
}

export async function postFreeSimulate(apiKey, {
  ignitionPoints, duration_h = 3, useGusts, fuelMoistureScenario, bbox_km,
  weatherStreamText, fuelMoistureTableText,
} = {}) {
  const res = await fetch(`${API_BASE}/free-simulate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...auth(apiKey) },
    body: JSON.stringify({
      ignition_points: ignitionPoints,
      duration_h,
      use_gusts: !!useGusts,
      fuel_moisture_scenario: fuelMoistureScenario || null,
      bbox_km: bbox_km || null,
      weather_stream_text: weatherStreamText || null,
      fuel_moisture_table_text: fuelMoistureTableText || null,
    }),
  })
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
  return res.json()
}

export async function getFreeSimulationJob(apiKey, jobId) {
  return get(`/free-jobs/${encodeURIComponent(jobId)}`, apiKey)
}
