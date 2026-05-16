"""Teste do cliente fogos.pt contra a API real."""
import asyncio
import sys
sys.path.insert(0, "/home/claude/fogos_triage/src")

from fogos_triage.ingestion.fogos_client import fetch_fires, NaturezaCode, StatusCode


async def main():
    print("A ir à fogos.pt...")
    fires = await fetch_fires()
    print(f"\n{len(fires)} ocorrências válidas\n")

    # Resumo por natureza
    by_nat = {}
    for f in fires:
        by_nat.setdefault(f.natureza_name, 0)
        by_nat[f.natureza_name] += 1

    print("Por natureza:")
    for k, v in sorted(by_nat.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")

    # Resumo por estado
    print("\nPor estado:")
    by_status = {}
    for f in fires:
        by_status.setdefault(f.status_name, 0)
        by_status[f.status_name] += 1
    for k, v in sorted(by_status.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")

    # Ocorrências relevantes para triagem
    relevant = [f for f in fires if f.is_triage_relevant and not f.is_terminated]
    print(f"\nOcorrências relevantes para triagem (não terminadas): {len(relevant)}")
    for f in relevant[:5]:
        w_str = "sem meteo"
        if f.weather:
            w_str = (f"T={f.weather.temperature_c}°C "
                     f"H={f.weather.humidity_pct}% "
                     f"V={f.weather.wind_speed_ms}m/s ({f.weather.wind_direction_text})")
        print(f"  {f.fire_id}: {f.district}/{f.municipality} - {f.natureza_name} - {f.status_name}")
        print(f"     coords=({f.latitude:.4f},{f.longitude:.4f}) "
              f"meios={f.operatives}m/{f.vehicles}v/{f.aerial}a")
        print(f"     meteo: {w_str}")

    # Verificar campos críticos
    print("\nDiagnóstico campos:")
    print(f"  com coordenadas fiáveis: {sum(1 for f in fires if f.has_reliable_coords)}")
    print(f"  com meteo IPMA anexa: {sum(1 for f in fires if f.weather and f.weather.temperature_c is not None)}")
    print(f"  com direção vento: {sum(1 for f in fires if f.weather and f.weather.wind_direction_deg is not None)}")
    print(f"  importantes: {sum(1 for f in fires if f.is_important)}")


asyncio.run(main())
