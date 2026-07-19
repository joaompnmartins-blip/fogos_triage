"""
Cliente para a API fogos.pt.

Endpoint principal: https://api-dev.fogos.pt/new/fires

NOTA SOBRE ACESSO:
A API fogos.pt está atrás de Cloudflare e bloqueia clientes HTTP comuns por
TLS fingerprint (mesmo com User-Agent de browser). Em produção há três opções:

1. Usar `curl_cffi` (impersona TLS de Chrome). É a opção default deste módulo
   quando disponível. Instalar com: pip install curl_cffi
2. Pedir whitelist/API-key à fogos.pt (Tiago Henriques).
3. Usar fonte oficial direta da ANEPC/PROCIV (requer acesso institucional).

O cliente tenta na seguinte ordem:
- curl_cffi se instalado (transparente)
- httpx como fallback (provavelmente falha com 403)

Estrutura observada da resposta (Maio 2026):
- success: bool
- data: lista de ocorrências, cada uma com:
  - id, _id.$id, sadoId, sharepointId — identificadores
  - dateTime.sec — timestamp Unix do alerta
  - date, hour — strings formatadas
  - location, district, concelho, freguesia, localidade
  - dico — código DICO INE da freguesia
  - lat, lng — coordenadas WGS84
  - coords — boolean: True se coordenadas fiáveis
  - naturezaCode, natureza — tipo de ocorrência
  - statusCode, status, statusColor
  - man, terrain, aerial — recursos operacionais e veículos terrestres/aéreos
  - heliFight, heliCoord, planeFight, meios_aquaticos
  - important — flag boolean
  - active, disappear — estado de visibilidade
  - regiao, sub_regiao — divisão geográfica
  - weather — bloco com meteo IPMA da estação mais próxima:
    - stationId, stationLocation, stationDistance (km)
    - temperatura (°C), humidade (%), intensidadeVento (m/s),
      intensidadeVentoKM (km/h), direccVento (N/NE/E/SE/S/SW/W/NW),
      idDireccVento, precAcumulada (mm), radiacao, pressao
    - date (ISO timestamp)
  - created.sec, updated.sec — timestamps Unix
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Optional

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False


FOGOS_API_URL = "https://api-dev.fogos.pt/new/fires"

# A API parece bloquear pedidos sem User-Agent reconhecível (CloudFlare/Vercel).
# Em produção vale a pena pedir à fogos.pt para nos pôr numa whitelist ou
# fornecer API key. Por ora, identificamo-nos como browser moderno.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
    "Referer": "https://fogos.pt/",
    "Origin": "https://fogos.pt",
}


class NaturezaCode(IntEnum):
    """Códigos de natureza das ocorrências fogos.pt."""
    POVOAMENTO_FLORESTAL = 3101
    MATO = 3103
    AGRICOLA = 3105
    GESTAO_COMBUSTIVEL = 3109
    QUEIMA = 3111
    PREVENCAO_QUEIMADAS = 4335


class StatusCode(IntEnum):
    """
    Códigos de estado das ocorrências.

    Confirmados por consulta directa à BD de produção (occurrences +
    occurrence_history, 4778 ocorrências) — 3 e 9 não estavam
    documentados nem modelados antes, apesar de aparecerem com
    frequência (Despacho: 19 activas/307 no histórico; Vigilância:
    273 activas/1725 no histórico).
    """
    DESPACHO = 3
    DESPACHO_1_ALERTA = 4
    EM_CURSO = 5
    CHEGADA_TO = 6
    EM_RESOLUCAO = 7
    CONCLUSAO = 8
    VIGILANCIA = 9


# Naturezas que disparam triagem completa
TRIAGE_RELEVANT_NATUREZAS = {
    NaturezaCode.POVOAMENTO_FLORESTAL,
    NaturezaCode.MATO,
    NaturezaCode.AGRICOLA,
    NaturezaCode.GESTAO_COMBUSTIVEL,
}


# Direção do vento: a API dá texto cardinal; convertemos para azimute em graus
WIND_DIR_TO_DEGREES = {
    "N": 0, "NE": 45, "E": 90, "SE": 135,
    "S": 180, "SW": 225, "W": 270, "NW": 315,
}


@dataclass
class FogosWeatherSnapshot:
    """Snapshot meteorológico IPMA anexado a uma ocorrência."""
    station_id: Optional[int]
    station_location: Optional[str]
    station_distance_km: Optional[float]
    temperature_c: Optional[float]
    humidity_pct: Optional[float]
    wind_speed_ms: Optional[float]
    wind_speed_kmh: Optional[float]
    wind_direction_text: Optional[str]
    wind_direction_deg: Optional[float]
    precipitation_mm: Optional[float]
    radiation: Optional[float]
    pressure: Optional[float]
    timestamp: Optional[datetime]

    @classmethod
    def from_api(cls, w: Optional[dict]) -> Optional["FogosWeatherSnapshot"]:
        if not w:
            return None
        wind_dir = w.get("direccVento")
        wind_dir_deg = WIND_DIR_TO_DEGREES.get(wind_dir) if wind_dir else None
        date_str = w.get("date")
        ts = None
        if date_str:
            try:
                ts = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                ts = None
        return cls(
            station_id=w.get("stationId"),
            station_location=w.get("stationLocation"),
            station_distance_km=w.get("stationDistance"),
            temperature_c=w.get("temperatura"),
            humidity_pct=w.get("humidade"),
            wind_speed_ms=w.get("intensidadeVento"),
            wind_speed_kmh=w.get("intensidadeVentoKM"),
            wind_direction_text=wind_dir,
            wind_direction_deg=wind_dir_deg,
            precipitation_mm=w.get("precAcumulada"),
            radiation=w.get("radiacao"),
            pressure=w.get("pressao"),
            timestamp=ts,
        )


@dataclass
class FogosFire:
    """Ocorrência normalizada vinda da fogos.pt."""
    fire_id: str
    sado_id: Optional[str]
    sharepoint_id: Optional[int]
    started_at: datetime
    latitude: float
    longitude: float
    has_reliable_coords: bool
    location: str
    district: str
    municipality: str
    parish: str
    dico: Optional[str]
    locality: Optional[str]
    region: Optional[str]
    subregion: Optional[str]
    natureza_code: int
    natureza_name: str
    status_code: int
    status_name: str
    is_important: bool
    is_active: bool
    # Recursos
    operatives: int
    vehicles: int
    aerial: int
    heli_fight: int
    heli_coord: int
    plane_fight: int
    water_means: int
    # Timestamps
    created_at: datetime
    updated_at: datetime
    # Meteo anexa
    weather: Optional[FogosWeatherSnapshot] = None
    # Raw (para debug)
    raw: dict = field(default_factory=dict)

    @property
    def is_triage_relevant(self) -> bool:
        """True se a natureza justifica triagem completa."""
        try:
            nat = NaturezaCode(self.natureza_code)
            return nat in TRIAGE_RELEVANT_NATUREZAS
        except ValueError:
            return False

    @property
    def is_terminated(self) -> bool:
        """True se a ocorrência está concluída — inclui Vigilância (9),
        monitorização pós-rescaldo, tratada como resolvida para efeitos
        de triagem, tal como Conclusão (8)."""
        return self.status_code in (StatusCode.CONCLUSAO, StatusCode.VIGILANCIA)

    @classmethod
    def from_api(cls, raw: dict) -> Optional["FogosFire"]:
        """
        Constrói a partir do dict da API. Rejeita ocorrências sem coordenadas
        fiáveis ou sem campos críticos.
        """
        if not raw.get("coords"):
            return None
        if raw.get("lat") is None or raw.get("lng") is None:
            return None

        dt_sec = raw.get("dateTime", {}).get("sec")
        if not dt_sec:
            return None

        created_sec = raw.get("created", {}).get("sec") or dt_sec
        updated_sec = raw.get("updated", {}).get("sec") or dt_sec

        return cls(
            fire_id=str(raw["id"]),
            sado_id=raw.get("sadoId"),
            sharepoint_id=raw.get("sharepointId"),
            started_at=datetime.fromtimestamp(dt_sec, tz=timezone.utc),
            latitude=float(raw["lat"]),
            longitude=float(raw["lng"]),
            has_reliable_coords=bool(raw.get("coords")),
            location=raw.get("location", ""),
            district=raw.get("district", ""),
            municipality=raw.get("concelho", ""),
            parish=raw.get("freguesia", ""),
            dico=raw.get("dico"),
            locality=(raw.get("localidade") or "").strip() or None,
            region=raw.get("regiao"),
            subregion=raw.get("sub_regiao"),
            natureza_code=int(raw.get("naturezaCode", 0)),
            natureza_name=raw.get("natureza", ""),
            status_code=int(raw.get("statusCode", 0)),
            status_name=raw.get("status", ""),
            is_important=bool(raw.get("important", False)),
            is_active=bool(raw.get("active", False)),
            operatives=int(raw.get("man", 0) or 0),
            vehicles=int(raw.get("terrain", 0) or 0),
            aerial=int(raw.get("aerial", 0) or 0),
            heli_fight=int(raw.get("heliFight", 0) or 0),
            heli_coord=int(raw.get("heliCoord", 0) or 0),
            plane_fight=int(raw.get("planeFight", 0) or 0),
            water_means=int(raw.get("meios_aquaticos", 0) or 0),
            created_at=datetime.fromtimestamp(created_sec, tz=timezone.utc),
            updated_at=datetime.fromtimestamp(updated_sec, tz=timezone.utc),
            weather=FogosWeatherSnapshot.from_api(raw.get("weather")),
            raw=raw,
        )


# ---------------------------------------------------------------------------
# Cliente HTTP
# ---------------------------------------------------------------------------


async def fetch_fires(
    client: Optional["httpx.AsyncClient"] = None,
    timeout_s: float = 15.0,
) -> list[FogosFire]:
    """
    Vai buscar a lista atual de ocorrências à fogos.pt.

    Estratégia:
    - Se curl_cffi estiver instalado, usa-o (passa Cloudflare).
    - Caso contrário, tenta httpx (pode falhar com 403).

    Filtra ocorrências sem coordenadas fiáveis e parses errados.
    Devolve lista de FogosFire normalizados.
    """
    if HAS_CURL_CFFI:
        payload = await _fetch_with_curl_cffi(timeout_s)
    elif HAS_HTTPX:
        payload = await _fetch_with_httpx(client, timeout_s)
    else:
        raise ImportError(
            "Necessário curl_cffi ou httpx. Recomendado: pip install curl_cffi"
        )

    if not payload.get("success"):
        raise ValueError(f"fogos.pt devolveu success=false: {payload}")

    fires = []
    for raw in payload.get("data", []):
        try:
            fire = FogosFire.from_api(raw)
            if fire is not None:
                fires.append(fire)
        except (KeyError, ValueError, TypeError) as e:
            import logging
            logging.warning(f"Erro a parsear ocorrência {raw.get('id', '?')}: {e}")
            continue

    return fires


async def _fetch_with_curl_cffi(timeout_s: float) -> dict:
    """Fetch usando curl_cffi (impersona TLS de Chrome). Atravessa Cloudflare."""
    def _sync_fetch():
        response = cffi_requests.get(
            FOGOS_API_URL,
            headers=DEFAULT_HEADERS,
            impersonate="chrome120",
            timeout=timeout_s,
        )
        response.raise_for_status()
        return response.json()
    # curl_cffi.requests é sync; corremos em executor para não bloquear o loop
    return await asyncio.to_thread(_sync_fetch)


async def _fetch_with_httpx(client, timeout_s: float) -> dict:
    """Fallback httpx (provavelmente falha com 403 em produção)."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=timeout_s, headers=DEFAULT_HEADERS)
    try:
        response = await client.get(FOGOS_API_URL, headers=DEFAULT_HEADERS)
        response.raise_for_status()
        return response.json()
    finally:
        if own_client:
            await client.aclose()
