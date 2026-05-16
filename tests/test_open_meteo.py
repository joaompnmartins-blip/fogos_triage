"""
Teste do fluxo Open-Meteo: fetch → snapshot → triagem → verificar persistência.

Valida a substituição da meteo IPMA por Open-Meteo, e confirma que o
snapshot fica gravado (correção do bug do weather a null na API).
"""
import asyncio
import os
import sys
import warnings

sys.path.insert(0, "/home/claude/fogos_triage/src")
warnings.filterwarnings("ignore", category=RuntimeWarning)

DSN = "postgresql://fogos@/fogos?host=/tmp/pgsock&port=5433"

from fogos_triage.db.repository import OccurrenceRepository, init_pool
from fogos_triage.weather import fetch_open_meteo, derive_fire_weather
from fogos_triage.ingestion.fogos_client import FogosFire


async def main():
    print("=" * 60)
    print("TESTE OPEN-METEO")
    print("=" * 60)

    # 1. Buscar meteo ao Open-Meteo.
    #    NOTA: o sandbox bloqueia api.open-meteo.com (host_not_allowed),
    #    tal como bloqueia a fogos.pt. Na máquina do utilizador / no Docker
    #    funciona normalmente. Aqui simulamos a resposta para validar tudo
    #    o que vem A SEGUIR da chamada de rede.
    print("\n[1] fetch_open_meteo — simulado (sandbox bloqueia o domínio real)")
    from datetime import datetime
    from fogos_triage.schemas import WeatherConditions
    forecast = [
        WeatherConditions(
            timestamp=datetime(2026, 5, 16, 15, 0),
            temperature_c=24.5, relative_humidity_pct=42.0,
            wind_speed_10m_ms=4.8, wind_gust_10m_ms=8.1,
            wind_direction_deg=315.0, precipitation_mm_24h=0.0,
            cloud_cover_pct=20.0,
        ),
        WeatherConditions(
            timestamp=datetime(2026, 5, 16, 16, 0),
            temperature_c=25.1, relative_humidity_pct=39.0,
            wind_speed_10m_ms=5.2, wind_gust_10m_ms=9.0,
            wind_direction_deg=320.0, precipitation_mm_24h=0.0,
            cloud_cover_pct=15.0,
        ),
    ]
    print(f"  {len(forecast)} horas (simuladas)")
    for w in forecast:
        print(f"  {w.timestamp:%Y-%m-%d %H:%M}  "
              f"T={w.temperature_c}°C  HR={w.relative_humidity_pct}%  "
              f"vento={w.wind_speed_10m_ms}m/s  rajada={w.wind_gust_10m_ms}m/s")

    if not forecast:
        print("  FALHA — Open-Meteo não devolveu dados")
        return

    weather_now = forecast[0]

    # 2. Inserir uma ocorrência fictícia para poder gravar o snapshot
    print("\n[2] Pool + ocorrência de teste")
    pool = await init_pool(DSN)
    repo = OccurrenceRepository(pool)

    raw = {
        "id": "TEST_OPENMETEO", "coords": True,
        "dateTime": {"sec": 1779200000}, "lat": 41.73246, "lng": -8.785496,
        "naturezaCode": "3103", "natureza": "Mato",
        "statusCode": 5, "status": "Em Curso",
        "district": "Viana Do Castelo", "concelho": "Viana Do Castelo",
        "freguesia": "Perre", "man": 10, "terrain": 3, "aerial": 0,
        "created": {"sec": 1779200000}, "updated": {"sec": 1779200000},
    }
    fire = FogosFire.from_api(raw)
    await repo.upsert_fire(fire)
    print(f"  ocorrência {fire.fire_id} inserida")

    # 3. Gravar o snapshot Open-Meteo
    print("\n[3] save_open_meteo_snapshot")
    await repo.save_open_meteo_snapshot(fire.fire_id, weather_now)
    print("  snapshot gravado")

    # 4. Verificar que ficou persistido (o bug do null era ISTO falhar)
    print("\n[4] Verificar persistência")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT source, temperature_c, wind_speed_ms, wind_direction_deg,
                   relative_humidity_pct, observation_at
            FROM weather_snapshots
            WHERE fire_id = $1
            ORDER BY snapshot_at DESC LIMIT 1
            """,
            fire.fire_id,
        )
        if row is None:
            print("  FALHA — snapshot não encontrado na BD")
        else:
            print(f"  source: {row['source']}")
            print(f"  temperatura: {row['temperature_c']}°C")
            print(f"  humidade: {row['relative_humidity_pct']}%")
            print(f"  vento: {row['wind_speed_ms']} m/s")
            print(f"  direção: {row['wind_direction_deg']}°")
            assert row["source"] == "open_meteo"
            assert row["temperature_c"] is not None
            print("  OK — meteo persistida e não-nula")

    # 5. derive_fire_weather funciona com o resultado Open-Meteo?
    print("\n[5] derive_fire_weather")
    wx = derive_fire_weather(
        weather_now, stand_height_m=15, canopy_cover_pct=50, has_overstory=True,
    )
    print(f"  vento midflame: {wx.wind_midflame_ms:.2f} m/s")
    print(f"  humidade fino morto 1h: {wx.fuel_moisture_1h_pct:.1f}%")

    # limpar
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM occurrences WHERE fire_id = 'TEST_OPENMETEO'")
    await pool.close()

    print("\n" + "=" * 60)
    print("TESTE OPEN-METEO PASSOU")
    print("=" * 60)


asyncio.run(main())
