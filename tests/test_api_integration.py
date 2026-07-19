"""
Teste de integração da API com TestClient e pool mock.

Usa TestClient como context manager para disparar o lifespan, e mocka
asyncpg.create_pool para devolver um pool falso com dados controlados.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/home/claude/fogos_triage/src")
sys.path.insert(0, "/home/claude/fogos_triage")

os.environ["DATABASE_URL"] = "postgresql://fake:fake@localhost/fake"
os.environ["API_KEYS"] = "test-key-123,other-key"
os.environ["REQUIRE_AUTH"] = "true"
os.environ["FUEL_MODELS_CSV"] = "/home/claude/fire_models_pt/data/fuel_models_pt.csv"

from unittest.mock import AsyncMock, MagicMock

NOW = datetime.now(timezone.utc)

FAKE_FIRE_ROW = {
    "fire_id": "20260674022", "latitude": 39.3586, "longitude": -8.7829,
    "location_text": "Santarém, Santarém, Alcanede",
    "district": "Santarém", "municipality": "Santarém", "parish": "Alcanede",
    "locality": "Casais Da Charneca", "natureza_code": 3103, "natureza_name": "Mato",
    "status_code": 7, "status_name": "Em Resolução", "is_important": False,
    "operatives": 16, "vehicles": 5, "aerial": 0,
    "started_at": NOW, "api_updated_at": NOW,
    "priority_class": "2", "priority_score": 1850.0,
    "central_ros_m_per_min": 4.2, "central_fireline_intensity_kw_m": 1850.0,
    "central_flame_length_m": 2.5, "central_fire_type": "surface",
    "central_direction_deg": 135.0, "fuel_model_code": "FM233",
    "triage_computed_at": NOW,
}

FAKE_OCCURRENCE_ROW = {
    **FAKE_FIRE_ROW,
    "sado_id": "20260674022", "sharepoint_id": 27196042,
    "region": "Lisboa e Vale do Tejo", "subregion": "Lezíria do Tejo",
    "dico": "1416", "is_active": True, "is_terminated": False,
    "heli_fight": 0, "heli_coord": 0, "plane_fight": 0, "water_means": 0,
    "first_seen_at": NOW, "last_seen_at": NOW,
}

FAKE_TRIAGE_ROW = {
    "fire_id": "20260674022", "computed_at": NOW,
    "priority_class": "2", "priority_score": 1850.0,
    "fuel_model_code": "FM233", "fuel_model_num": 233,
    "elevation_m": 120.0, "slope_degrees": 8.0, "aspect_degrees": 200.0,
    "stand_height_m": 2.0, "canopy_cover_pct": 0.0, "canopy_base_height_m": None,
    "wind_midflame_ms": 2.1, "wind_adjustment_factor": 0.42,
    "fuel_moisture_1h_pct": 9.5,
    "scenarios_json": [
        {"scenario": "central", "ros_m_per_min": 4.2,
         "fireline_intensity_kw_m": 1850.0, "flame_length_m": 2.5,
         "heat_per_unit_area_kj_m2": 12000.0, "reaction_intensity_kw_m2": 250.0,
         "direction_max_spread_deg": 135.0, "effective_wind_ms": 2.1,
         "fire_type": "surface"},
        {"scenario": "gusts", "ros_m_per_min": 7.1,
         "fireline_intensity_kw_m": 3200.0, "flame_length_m": 3.3,
         "heat_per_unit_area_kj_m2": 13500.0, "reaction_intensity_kw_m2": 270.0,
         "direction_max_spread_deg": 135.0, "effective_wind_ms": 2.5,
         "fire_type": "surface"},
    ],
    "notes": ["Cenário de teste"],
}

FAKE_WEATHER_ROW = {
    "temperature_c": 18.8, "relative_humidity_pct": 61.0,
    "wind_speed_ms": 5.2, "wind_speed_kmh": 18.7,
    "wind_direction_deg": 0.0, "wind_direction_text": "N",
    "source": "open_meteo", "ipma_station_location": "Rio Maior",
    "ipma_station_distance_km": 13.0, "observation_at": NOW,
}


def _make_record(d: dict):
    """Objeto que se comporta como asyncpg.Record."""
    rec = MagicMock()
    rec.__getitem__ = lambda self, k: d.get(k)
    rec.get = lambda k, default=None: d.get(k, default)
    rec.keys = lambda: d.keys()
    return rec


def make_mock_connection():
    conn = AsyncMock()

    async def fetch(query, *args):
        if "active_fires_with_triage" in query and "COUNT" not in query:
            return [_make_record(FAKE_FIRE_ROW)]
        if "occurrences o" in query and "ST_MakeEnvelope" in query:
            return [_make_record({**FAKE_OCCURRENCE_ROW,
                                  "central_flame_length_m": 2.5,
                                  "central_fire_type": "surface"})]
        if "occurrence_history" in query:
            return [_make_record({
                "snapshot_at": NOW, "change_type": "created",
                "status_code": 5, "status_name": "Em Curso",
                "previous_status_code": None,
                "operatives": 16, "vehicles": 5, "aerial": 0,
                "heli_fight": 0, "plane_fight": 0,
            })]
        return []

    async def fetchrow(query, *args):
        if "active_fires_with_triage" in query and "COUNT" in query:
            return _make_record({"c": 1})
        if "FROM occurrences WHERE fire_id" in query:
            fire_id = args[0] if args else None
            if fire_id == "20260674022":
                return _make_record(FAKE_OCCURRENCE_ROW)
            return None
        if "FROM triage_results" in query:
            return _make_record(FAKE_TRIAGE_ROW)
        if "FROM weather_snapshots" in query:
            return _make_record(FAKE_WEATHER_ROW)
        if "COUNT" in query:
            return _make_record({"c": 1})
        return None

    async def fetchval(query, *args):
        if "SELECT 1" in query and "occurrences" not in query:
            return 1
        if "MAX(last_seen_at)" in query:
            return NOW
        if "SELECT 1 FROM occurrences" in query:
            fire_id = args[0] if args else None
            return 1 if fire_id == "20260674022" else None
        return None

    async def execute(query, *args):
        return "INSERT 0 1"

    conn.fetch = fetch
    conn.fetchrow = fetchrow
    conn.fetchval = fetchval
    conn.execute = execute
    return conn


def make_mock_pool():
    pool = MagicMock()
    conn = make_mock_connection()
    acquire_cm = AsyncMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=acquire_cm)
    pool.close = AsyncMock()
    return pool


async def fake_create_pool(*args, **kwargs):
    return make_mock_pool()


import asyncpg
asyncpg.create_pool = fake_create_pool

from fastapi.testclient import TestClient
from services.api.main import create_app


app = create_app()
passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label}")


with TestClient(app) as client:
    AUTH = {"Authorization": "Bearer test-key-123"}

    print("=== 1. Autenticacao ===")
    r = client.get("/fuel-models")
    check(f"sem key -> 401 (got {r.status_code})", r.status_code == 401)
    r = client.get("/fuel-models", headers={"Authorization": "Bearer errada"})
    check(f"key errada -> 401 (got {r.status_code})", r.status_code == 401)
    r = client.get("/fuel-models", headers=AUTH)
    check(f"key boa -> 200 (got {r.status_code})", r.status_code == 200)

    print("\n=== 2. Health ===")
    r = client.get("/health")
    check(f"/health -> 200 (got {r.status_code})", r.status_code == 200)
    if r.status_code == 200:
        body = r.json()
        check(f"database_ok=True", body.get("database_ok") is True)
        check(f"status=ok", body.get("status") == "ok")

    print("\n=== 3. Fuel Models ===")
    r = client.get("/fuel-models", headers=AUTH)
    models = r.json()
    check(f"lista com >=18 modelos (got {len(models)})", len(models) >= 18)
    fm213 = next((m for m in models if m["num"] == 213), None)
    check("FM213 presente", fm213 is not None)
    r = client.get("/fuel-models/233", headers=AUTH)
    check(f"/fuel-models/233 -> 200 (got {r.status_code})", r.status_code == 200)
    r = client.get("/fuel-models/999", headers=AUTH)
    check(f"/fuel-models/999 -> 404 (got {r.status_code})", r.status_code == 404)

    print("\n=== 4. Lista de fogos ===")
    r = client.get("/fires", headers=AUTH)
    check(f"/fires -> 200 (got {r.status_code})", r.status_code == 200)
    if r.status_code == 200:
        body = r.json()
        check(f"1 item (got {len(body['items'])})", len(body["items"]) == 1)
        check(f"total=1 (got {body['total']})", body["total"] == 1)
        if body["items"]:
            item = body["items"][0]
            check("fire_id correto", item["fire_id"] == "20260674022")
            check("tem triagem", item["triage"] is not None)
            if item["triage"]:
                check("categoria 2 (Tedim et al. 2018)", item["triage"]["priority_class"] == "2")
                cd = item["triage"]["central"]["control_description"]
                check(f"control_description={cd}", cd == "Moderadamente difícil")

    print("\n=== 5. Detalhe de fogo ===")
    r = client.get("/fires/20260674022", headers=AUTH)
    check(f"/fires/{{id}} -> 200 (got {r.status_code})", r.status_code == 200)
    if r.status_code == 200:
        body = r.json()
        check("triagem no detalhe", body.get("triage") is not None)
        if body.get("triage"):
            scs = body["triage"]["scenarios"]
            check(f"2 cenarios (got {len(scs)})", len(scs) == 2)
            check("meteo presente",
                  body["triage"]["weather"]["source"] == "open_meteo")
    r = client.get("/fires/inexistente", headers=AUTH)
    check(f"/fires/inexistente -> 404 (got {r.status_code})", r.status_code == 404)

    print("\n=== 6. Historico ===")
    r = client.get("/fires/20260674022/history", headers=AUTH)
    check(f"/history -> 200 (got {r.status_code})", r.status_code == 200)

    print("\n=== 7. GeoJSON ===")
    r = client.get(
        "/fires/geo/within",
        params={"min_lat": 38, "min_lng": -10, "max_lat": 42, "max_lng": -6},
        headers=AUTH,
    )
    check(f"/geo/within -> 200 (got {r.status_code})", r.status_code == 200)
    if r.status_code == 200:
        body = r.json()
        check("FeatureCollection", body.get("type") == "FeatureCollection")
        check(f">=1 feature (got {len(body.get('features', []))})",
              len(body.get("features", [])) >= 1)

    print("\n=== 8. Simulacao ===")
    r = client.post("/simulate",
                     json={"fire_id": "20260674022", "duration_h": 3.0},
                     headers=AUTH)
    check(f"POST /simulate -> 202 (got {r.status_code})", r.status_code == 202)
    if r.status_code == 202:
        check("job pending", r.json().get("status") == "pending")


print(f"\n{'='*40}")
print(f"RESULTADO: {passed} passados, {failed} falhados")
print('='*40)
sys.exit(0 if failed == 0 else 1)
