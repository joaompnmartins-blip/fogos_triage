"""
Teste end-to-end: ingestão + triagem + persistência contra Postgres REAL.

Em vez de ir à fogos.pt (sandbox bloqueia), usa um payload real capturado.
Valida toda a cadeia: FogosFire → upsert → triagem → save → query.
"""
import asyncio
import json
import os
import sys
import warnings

sys.path.insert(0, "/home/claude/fogos_triage/src")
sys.path.insert(0, "/home/claude/fogos_triage")
warnings.filterwarnings("ignore", category=RuntimeWarning)

# DSN configurável: usa DATABASE_URL se definida, senão localhost.
# Para testar localmente:  export DATABASE_URL=postgresql://localhost/fogos
DSN = os.environ.get("DATABASE_URL", "postgresql://localhost/fogos")
os.environ["FUEL_MODELS_CSV"] = "/home/claude/fogos_triage/data/fuel_models_pt.csv"

from fogos_triage.db.repository import OccurrenceRepository, init_pool
from fogos_triage.db.triage_repo import TriageResultRepository
from fogos_triage.fuel_models import load_fuel_models_csv
from fogos_triage.ingestion.fogos_client import FogosFire
from fogos_triage.ingestion.adapters import fogos_to_occurrence, fogos_weather_to_conditions
from fogos_triage.landscape import MockLandscapeReader
from fogos_triage.schemas import TerrainConditions, WeatherConditions
from fogos_triage.triage import triage_occurrence
from fogos_triage.weather import derive_fire_weather


# Payload real fogos.pt — inclui ocorrências de várias naturezas
PAYLOAD = {"success": True, "data": [
    # Mato (relevante para triagem) - simulamos "Em Curso" para forçar triagem
    {"_id": {"$id": "20260674022"}, "id": "20260674022", "coords": True,
     "dateTime": {"sec": 1778764080}, "date": "14-05-2026", "hour": "14:08",
     "location": "Santarém, Santarém, Alcanede", "aerial": 0, "meios_aquaticos": 0,
     "man": 16, "terrain": 5, "district": "Santarém", "concelho": "Santarém",
     "freguesia": "Alcanede", "dico": "1416", "lat": 39.358625, "lng": -8.782855,
     "naturezaCode": "3103", "natureza": "Mato", "statusCode": 5,
     "status": "Em Curso", "important": False, "localidade": "Casais Da Charneca ",
     "active": True, "sadoId": "20260674022", "sharepointId": 27196042,
     "heliFight": 0, "heliCoord": 0, "planeFight": 0, "regiao": "Lisboa e Vale do Tejo",
     "sub_regiao": "Lezíria do Tejo",
     "weather": {"stationId": 1210729, "stationLocation": "Rio Maior",
                 "stationDistance": 13, "temperatura": 28.8, "humidade": 35,
                 "intensidadeVento": 6.2, "intensidadeVentoKM": 22.3,
                 "idDireccVento": 9, "direccVento": "N", "precAcumulada": 0,
                 "radiacao": 3213.3, "date": "2026-05-14T13:00:00.000000Z"},
     "created": {"sec": 1778764335}, "updated": {"sec": 1778767573}},

    # Povoamento Florestal (relevante)
    {"_id": {"$id": "20260674112"}, "id": "20260674112", "coords": True,
     "dateTime": {"sec": 1778765100}, "date": "14-05-2026", "hour": "14:25",
     "location": "Coimbra, Oliveira do Hospital, Lagos Da Beira", "aerial": 1,
     "meios_aquaticos": 0, "man": 13, "terrain": 4, "district": "Coimbra",
     "concelho": "Oliveira Do Hospital", "freguesia": "Lagos Da Beira E Lajeosa",
     "dico": "0611", "lat": 40.37694, "lng": -7.84944,
     "naturezaCode": "3101", "natureza": "Povoamento Florestal", "statusCode": 6,
     "status": "Chegada ao TO", "important": False, "localidade": "Lajeosa ",
     "active": True, "sadoId": "20260674112", "sharepointId": 27196132,
     "heliFight": 1, "heliCoord": 0, "planeFight": 0, "regiao": "Centro",
     "sub_regiao": "Região de Coimbra",
     "weather": {"stationId": 6213620, "stationLocation": "Oliveira do Hospital",
                 "stationDistance": 4.3, "temperatura": 31.0, "humidade": 30,
                 "intensidadeVento": 4.5, "intensidadeVentoKM": 16.2,
                 "idDireccVento": 6, "direccVento": "SW", "precAcumulada": 0,
                 "radiacao": 3500, "date": "2026-05-14T13:00:00.000000Z"},
     "created": {"sec": 1778765294}, "updated": {"sec": 1778769375}},

    # Prevenção a Queimadas (NÃO relevante — não dispara triagem)
    {"_id": {"$id": "20260674206"}, "id": "20260674206", "coords": True,
     "dateTime": {"sec": 1778766240}, "date": "14-05-2026", "hour": "14:44",
     "location": "Bragança, Macedo de Cavaleiros", "aerial": 0, "meios_aquaticos": 0,
     "man": 3, "terrain": 1, "district": "Bragança", "concelho": "Macedo De Cavaleiros",
     "freguesia": "Vilarinho De Agrochão", "dico": "0405",
     "lat": 41.670132, "lng": -7.065156,
     "naturezaCode": "4335", "natureza": "Prevenção a Queimadas", "statusCode": 4,
     "status": "Despacho de 1º Alerta", "important": False,
     "localidade": "Vilarinho ", "active": True, "sadoId": "20260674206",
     "sharepointId": 27196226, "heliFight": 0, "heliCoord": 0, "planeFight": 0,
     "regiao": "Norte", "sub_regiao": "Terras de Trás-os-Montes",
     "weather": {"stationId": 1210612, "stationLocation": "Vinhais",
                 "stationDistance": 19.9, "temperatura": 13, "humidade": 61,
                 "intensidadeVento": 9.1, "intensidadeVentoKM": 32.8,
                 "idDireccVento": 8, "direccVento": "NW", "precAcumulada": 0,
                 "date": "2026-05-14T13:00:00.000000Z"},
     "created": {"sec": 1778766497}, "updated": {"sec": 1778766521}},
]}


async def main():
    print("=" * 60)
    print("TESTE END-TO-END: worker → Postgres real")
    print("=" * 60)

    # 1. Parse do payload
    fires = []
    for raw in PAYLOAD["data"]:
        f = FogosFire.from_api(raw)
        if f:
            fires.append(f)
    print(f"\n[1] Parse: {len(fires)} ocorrências")

    # 2. Recursos
    pool = await init_pool(DSN)
    fuel_models = load_fuel_models_csv(os.environ["FUEL_MODELS_CSV"])
    print(f"[2] Pool Postgres OK, {len(fuel_models)} modelos carregados")

    occ_repo = OccurrenceRepository(pool)
    triage_repo = TriageResultRepository(pool)

    # Terreno mock — pinhal com declive (cenário realista para os fogos)
    terrain = TerrainConditions(
        elevation_m=400, slope_fraction=0.27, slope_degrees=15,
        aspect_degrees=180, fuel_model_num=227,
        stand_height_m=15, canopy_cover_pct=50, canopy_base_height_m=3.0,
    )

    # 3. Processar cada ocorrência
    print(f"\n[3] Processamento:")
    for fire in fires:
        is_new, has_changes = await occ_repo.upsert_fire(fire)
        status = "NOVA" if is_new else ("MUDOU" if has_changes else "igual")
        print(f"  {fire.fire_id} [{status}] {fire.natureza_name}")

        if not fire.is_triage_relevant:
            print(f"    → natureza não relevante, sem triagem")
            continue
        if fire.is_terminated:
            print(f"    → terminada, sem triagem")
            continue

        # Triagem
        occ = fogos_to_occurrence(fire)
        weather_raw = fogos_weather_to_conditions(fire.weather, fire.updated_at)
        weather = derive_fire_weather(
            weather_raw, stand_height_m=terrain.stand_height_m,
            canopy_cover_pct=terrain.canopy_cover_pct, has_overstory=True,
        )
        result = triage_occurrence(occ, fuel_models, terrain, weather)
        await triage_repo.save(result)
        c = result.central_prediction
        print(f"    → TRIAGEM: {result.priority.value} "
              f"(score {result.priority_score:.0f}) "
              f"chamas {c.flame_length_m:.1f}m ROS {c.ros_m_per_min:.1f}m/min "
              f"FM={result.fuel_model_used}")

    # 4. Marcar inativas (todas presentes → 0)
    current_ids = {f.fire_id for f in fires}
    inactive = await occ_repo.mark_inactive_missing(current_ids)
    print(f"\n[4] Marcadas inativas: {inactive}")

    # 5. Verificar persistência — query à view
    print(f"\n[5] Query à view active_fires_with_triage:")
    async with pool.acquire() as conn:
        # A view já filtra is_active e NOT is_terminated internamente
        rows = await conn.fetch(
            "SELECT fire_id, priority_class, priority_score, "
            "central_flame_length_m, fuel_model_code "
            "FROM active_fires_with_triage "
            "ORDER BY priority_score DESC NULLS LAST"
        )
        for r in rows:
            pc = r["priority_class"] or "—"
            ps = f"{r['priority_score']:.0f}" if r["priority_score"] else "—"
            fl = f"{r['central_flame_length_m']:.1f}m" if r["central_flame_length_m"] else "—"
            print(f"  {r['fire_id']}: {pc} (score {ps}) chamas {fl}")

        # Contar registos em cada tabela
        print(f"\n[6] Contagens nas tabelas:")
        for table in ["occurrences", "occurrence_history", "weather_snapshots",
                      "triage_results"]:
            cnt = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
            print(f"  {table}: {cnt}")

        # Verificar histórico
        print(f"\n[7] Histórico da ocorrência 20260674022:")
        hist = await conn.fetch(
            "SELECT change_type, status_code, operatives "
            "FROM occurrence_history WHERE fire_id = '20260674022' "
            "ORDER BY snapshot_at"
        )
        for h in hist:
            print(f"  {h['change_type']}: status={h['status_code']} "
                  f"ops={h['operatives']}")

    # 8. Testar idempotência — reprocessar não deve criar duplicados
    print(f"\n[8] Idempotência — reprocessar payload:")
    for fire in fires:
        is_new, has_changes = await occ_repo.upsert_fire(fire)
        assert not is_new, f"{fire.fire_id} não devia ser 'nova' na 2ª vez"
    async with pool.acquire() as conn:
        cnt = await conn.fetchval("SELECT COUNT(*) FROM occurrences")
    print(f"  occurrences após reprocessar: {cnt} (esperado 3 — sem duplicados)")
    assert cnt == 3, "DUPLICADOS DETETADOS!"

    await pool.close()
    print(f"\n{'='*60}")
    print("TESTE END-TO-END PASSOU")
    print('='*60)


asyncio.run(main())
