"""
Repositório (Data Access Layer) para occurrences e snapshots associados.

Usa asyncpg para acesso direto ao Postgres com performance e baixo overhead.
Optamos por SQL direto em vez de ORM porque:
1. As queries são poucas e bem definidas
2. Geometria PostGIS é mais simples com SQL puro
3. Sem dependência de SQLAlchemy → container mais leve
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from typing import Optional

try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

from ..ingestion.fogos_client import FogosFire

log = logging.getLogger(__name__)

# Quanto é que a ocorrência tem de se deslocar para valer a pena repetir
# a triagem congelada (ver needs_triage). A triagem amostra uma
# vizinhança à volta do ponto, por isso uma correcção de algumas dezenas
# de metros não muda o terreno de forma significativa; e um limiar
# diferente de zero evita repetir a triagem por arredondamentos na
# coordenada devolvida pela fogos.pt.
TRIAGE_MOVE_TOLERANCE_M = 50.0


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância aproximada em metros (equirectangular).

    Chega e sobra para comparar duas leituras da mesma ocorrência, que
    distam metros ou centenas de metros — não vale a pena Haversine nem
    uma dependência de projecção para isto.
    """
    lat_med = math.radians((lat1 + lat2) / 2.0)
    dx = math.radians(lon2 - lon1) * math.cos(lat_med)
    dy = math.radians(lat2 - lat1)
    return math.hypot(dx, dy) * 6_371_000.0


class OccurrenceRepository:
    """
    Operações sobre a tabela occurrences e tabelas relacionadas.

    Uso:
        pool = await asyncpg.create_pool(dsn)
        repo = OccurrenceRepository(pool)
        await repo.upsert_fire(fire)
    """

    def __init__(self, pool: "asyncpg.Pool"):
        if not HAS_ASYNCPG:
            raise ImportError("asyncpg é necessário (pip install asyncpg)")
        self.pool = pool

    async def upsert_fire(self, fire: FogosFire) -> tuple[bool, bool]:
        """
        Insere ou atualiza uma ocorrência.

        Devolve (is_new, has_changes) onde:
        - is_new: True se foi inserção
        - has_changes: True se houve mudanças relevantes (status, recursos)

        Quando há mudanças, escreve também em occurrence_history.
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Verificar estado anterior
                prev = await conn.fetchrow(
                    """
                    SELECT status_code, operatives, vehicles, aerial,
                           heli_fight, plane_fight
                    FROM occurrences WHERE fire_id = $1
                    """,
                    fire.fire_id,
                )

                is_new = prev is None
                has_changes = False
                change_type = "created"
                previous_status = None

                if not is_new:
                    status_changed = prev["status_code"] != fire.status_code
                    resources_changed = (
                        prev["operatives"] != fire.operatives
                        or prev["vehicles"] != fire.vehicles
                        or prev["aerial"] != fire.aerial
                        or prev["heli_fight"] != fire.heli_fight
                        or prev["plane_fight"] != fire.plane_fight
                    )
                    if status_changed and resources_changed:
                        change_type = "both"
                    elif status_changed:
                        change_type = "status"
                    elif resources_changed:
                        change_type = "resources"
                    has_changes = status_changed or resources_changed
                    previous_status = prev["status_code"]

                # UPSERT
                await conn.execute(
                    """
                    INSERT INTO occurrences (
                        fire_id, sado_id, sharepoint_id,
                        geom, latitude, longitude, has_reliable_coords,
                        location_text, district, municipality, parish,
                        dico, locality, region, subregion,
                        natureza_code, natureza_name, is_triage_relevant,
                        status_code, status_name, is_active, is_important,
                        operatives, vehicles, aerial, heli_fight, heli_coord,
                        plane_fight, water_means,
                        started_at, api_created_at, api_updated_at,
                        last_seen_at, raw_payload
                    )
                    VALUES (
                        $1, $2, $3,
                        ST_SetSRID(ST_MakePoint($5, $4), 4326),
                        $4, $5, $6,
                        $7, $8, $9, $10,
                        $11, $12, $13, $14,
                        $15, $16, $17,
                        $18, $19, $20, $21,
                        $22, $23, $24, $25, $26, $27, $28,
                        $29, $30, $31,
                        NOW(), $32
                    )
                    ON CONFLICT (fire_id) DO UPDATE SET
                        -- Actualizar coordenadas se a fogos.pt as corrigiu
                        geom = EXCLUDED.geom,
                        latitude = EXCLUDED.latitude,
                        longitude = EXCLUDED.longitude,
                        has_reliable_coords = EXCLUDED.has_reliable_coords,
                        location_text = EXCLUDED.location_text,
                        district = EXCLUDED.district,
                        municipality = EXCLUDED.municipality,
                        parish = EXCLUDED.parish,
                        status_code = EXCLUDED.status_code,
                        status_name = EXCLUDED.status_name,
                        is_active = EXCLUDED.is_active,
                        is_important = EXCLUDED.is_important,
                        operatives = EXCLUDED.operatives,
                        vehicles = EXCLUDED.vehicles,
                        aerial = EXCLUDED.aerial,
                        heli_fight = EXCLUDED.heli_fight,
                        heli_coord = EXCLUDED.heli_coord,
                        plane_fight = EXCLUDED.plane_fight,
                        water_means = EXCLUDED.water_means,
                        api_updated_at = EXCLUDED.api_updated_at,
                        last_seen_at = NOW(),
                        raw_payload = EXCLUDED.raw_payload
                    """,
                    fire.fire_id, fire.sado_id, fire.sharepoint_id,
                    fire.latitude, fire.longitude, fire.has_reliable_coords,
                    fire.location, fire.district, fire.municipality, fire.parish,
                    fire.dico, fire.locality, fire.region, fire.subregion,
                    fire.natureza_code, fire.natureza_name, fire.is_triage_relevant,
                    fire.status_code, fire.status_name, fire.is_active, fire.is_important,
                    fire.operatives, fire.vehicles, fire.aerial,
                    fire.heli_fight, fire.heli_coord, fire.plane_fight, fire.water_means,
                    fire.started_at, fire.created_at, fire.updated_at,
                    fire.raw,
                )

                # Registar histórico se há mudanças (ou criação)
                if is_new or has_changes:
                    await conn.execute(
                        """
                        INSERT INTO occurrence_history (
                            fire_id, status_code, status_name,
                            operatives, vehicles, aerial, heli_fight, plane_fight,
                            change_type, previous_status_code
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                        """,
                        fire.fire_id, fire.status_code, fire.status_name,
                        fire.operatives, fire.vehicles, fire.aerial,
                        fire.heli_fight, fire.plane_fight,
                        change_type, previous_status,
                    )

                # Registar snapshot de meteo IPMA se vem na payload
                if fire.weather:
                    w = fire.weather
                    await conn.execute(
                        """
                        INSERT INTO weather_snapshots (
                            fire_id, source,
                            ipma_station_id, ipma_station_location, ipma_station_distance_km,
                            temperature_c, relative_humidity_pct,
                            wind_speed_ms, wind_speed_kmh,
                            wind_direction_deg, wind_direction_text,
                            precipitation_mm, radiation, pressure_hpa,
                            observation_at
                        )
                        VALUES ($1, 'ipma_fogos', $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                        """,
                        fire.fire_id,
                        w.station_id, w.station_location, w.station_distance_km,
                        w.temperature_c, w.humidity_pct,
                        w.wind_speed_ms, w.wind_speed_kmh,
                        w.wind_direction_deg, w.wind_direction_text,
                        w.precipitation_mm, w.radiation, w.pressure,
                        w.timestamp,
                    )

                return is_new, has_changes

    async def mark_inactive_missing(self, current_ids: set[str]) -> int:
        """
        Marca como inativas as ocorrências que estavam ativas mas já não vêm
        na resposta da API. A fogos.pt remove ocorrências terminadas após algum
        tempo — quando isso acontece marcamos como inativas (mantemos histórico).

        Devolve número de ocorrências marcadas.
        """
        if not current_ids:
            # Não fazer nada — pode ser erro da API; melhor não tocar
            return 0

        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE occurrences
                SET is_active = FALSE
                WHERE is_active = TRUE
                  AND NOT (fire_id = ANY($1::text[]))
                """,
                list(current_ids),
            )
            # asyncpg retorna "UPDATE N"
            count = int(result.split()[-1]) if result.startswith("UPDATE") else 0
            return count

    async def get_active_fires_for_triage(self, limit: int = 200) -> list[dict]:
        """
        Devolve ocorrências ativas que precisam de triagem rápida.
        Filtra por natureza relevante e não terminadas.
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT fire_id, latitude, longitude, district, municipality,
                       natureza_code, status_code, started_at,
                       operatives, vehicles, aerial
                FROM occurrences
                WHERE is_active = TRUE
                  AND NOT is_terminated
                  AND is_triage_relevant = TRUE
                ORDER BY started_at DESC
                LIMIT $1
                """,
                limit,
            )
            return [dict(r) for r in rows]

    async def needs_triage(
        self,
        fire_id: str,
        latitude: float,
        longitude: float,
        move_tolerance_m: float = TRIAGE_MOVE_TOLERANCE_M,
    ) -> bool:
        """
        True se esta ocorrência ainda não tem triagem, ou se a localização
        se afastou mais de `move_tolerance_m` da que foi usada na triagem
        congelada.

        A triagem é **congelada no arranque da ocorrência**: vale como
        protocolo de despacho, que é uma decisão do minuto zero, e não faz
        sentido recalculá-la de dois em dois minutos porque a fogos.pt
        actualizou o número de operacionais. Antes, qualquer mudança de
        efectivos ou de estado — mais uma triagem a cada 15 minutos —
        disparava tudo outra vez: terreno, Open-Meteo, VIIRS e motor de
        fogo. Num incêndio grande isso são centenas de triagens idênticas.

        A excepção é a localização: a fogos.pt corrige-a com frequência
        nas primeiras horas, e uma triagem congelada na coordenada errada
        descreve o terreno errado.

        A comparação é contra a coordenada **guardada na própria triagem**
        (migração 006), não contra a linha anterior de `occurrences`: um
        diff entre ciclos só apanharia a correcção no instante em que
        acontece, e perdia-a se o worker estivesse em baixo nesse momento.

        Nota: uma triagem que falhe por excepção não grava linha nenhuma,
        por isso repete-se sozinha no ciclo seguinte. O que fica congelado
        é a triagem que **grava** com dados degradados (Open-Meteo em
        defaults, ou sem LFMC) — decisão deliberada.
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT latitude, longitude
                FROM triage_results
                WHERE fire_id = $1 AND is_latest = TRUE
                """,
                fire_id,
            )
        if row is None:
            return True
        if row["latitude"] is None or row["longitude"] is None:
            # Triagem anterior à migração 006 — sem coordenada guardada
            # não há como saber se a ocorrência se moveu. Mantém-se
            # congelada; forçar uma re-triagem aqui faria com que o
            # deploy desta alteração retriasse tudo o que está activo.
            return False
        return _distance_m(row["latitude"], row["longitude"], latitude, longitude) > move_tolerance_m

    async def save_open_meteo_snapshot(
        self,
        fire_id: str,
        weather,
        forecast_hour_offset: int = 0,
    ) -> None:
        """
        Grava um snapshot meteorológico Open-Meteo na tabela weather_snapshots.

        `weather` é um WeatherConditions. forecast_hour_offset = 0 significa
        a hora atual; 1, 3, 5 seriam previsões futuras.

        Sem isto, a meteo usada na triagem não fica persistida e a API
        devolve o bloco weather a null.
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO weather_snapshots (
                    fire_id, source,
                    forecast_for, forecast_hour_offset,
                    temperature_c, relative_humidity_pct,
                    wind_speed_ms, wind_gust_ms, wind_direction_deg,
                    precipitation_24h_mm, cloud_cover_pct,
                    fire_weather_index,
                    observation_at
                )
                VALUES ($1, 'open_meteo', $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                """,
                fire_id,
                weather.timestamp,
                forecast_hour_offset,
                weather.temperature_c,
                weather.relative_humidity_pct,
                weather.wind_speed_10m_ms,
                weather.wind_gust_10m_ms,
                weather.wind_direction_deg,
                weather.precipitation_mm_24h,
                weather.cloud_cover_pct,
                weather.fire_weather_index,
                weather.timestamp,
            )


async def _init_connection(conn) -> None:
    """
    Inicializador de cada conexão do pool.

    Regista codecs JSON/JSONB para que asyncpg desserialize automaticamente
    colunas jsonb em dict/list (por defeito devolve string).

    O encoder usa default=str para tolerar tipos não-nativos (datetime, etc.)
    que possam vir no raw_payload da fogos.pt.
    """
    def _json_encoder(value):
        return json.dumps(value, default=str)

    await conn.set_type_codec(
        "jsonb",
        encoder=_json_encoder,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=_json_encoder,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def init_pool(dsn: str, min_size: int = 2, max_size: int = 10) -> "asyncpg.Pool":
    """
    Cria pool de conexões Postgres com codecs JSON registados.

    O parâmetro `init` garante que toda a conexão do pool desserializa
    jsonb automaticamente — sem isto, colunas jsonb vêm como string.
    """
    if not HAS_ASYNCPG:
        raise ImportError("asyncpg é necessário (pip install asyncpg)")
    return await asyncpg.create_pool(
        dsn,
        min_size=min_size,
        max_size=max_size,
        init=_init_connection,
    )
