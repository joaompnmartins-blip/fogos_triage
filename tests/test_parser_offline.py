"""
Teste do parser com payload real cacheado da fogos.pt.

Como o ambiente de sandbox bloqueia acesso direto à fogos.pt (egress proxy
com x-deny-reason: host_not_allowed), validamos o parser e a lógica de
adapters com uma resposta real capturada via web_fetch.

Em produção (Railway/local) o curl_cffi consegue aceder normalmente.
"""
import json
import sys
sys.path.insert(0, "/home/claude/fogos_triage/src")

from fogos_triage.ingestion.fogos_client import (
    FogosFire, NaturezaCode, StatusCode,
    TRIAGE_RELEVANT_NATUREZAS,
)
from fogos_triage.ingestion.adapters import (
    fogos_to_occurrence, fogos_weather_to_conditions,
)

# Payload real capturado em 14-05-2026 14:11 via web_fetch
PAYLOAD = json.loads("""
{"success":true,"data":[
  {"_id":{"$id":"20260673657"},"id":"20260673657","coords":true,
   "dateTime":{"sec":1778759760},"date":"14-05-2026","hour":"12:56",
   "location":"Beja, Moura, Safara","aerial":0,"meios_aquaticos":0,
   "man":13,"terrain":5,"district":"Beja","concelho":"Moura",
   "freguesia":"Safara","dico":"0210","lat":38.108223,"lng":-7.227776,
   "naturezaCode":"3103","natureza":"Mato","statusCode":8,"statusColor":"BDBDBD",
   "status":"Conclus\\u00e3o","important":false,"localidade":"Safara ",
   "active":true,"sadoId":"20260673657","sharepointId":27195677,
   "heliFight":0,"heliCoord":0,"planeFight":0,"regiao":"Alentejo",
   "sub_regiao":"Baixo Alentejo","nearestWeatherStationId":1210851,
   "isFire":true,
   "weather":{"stationId":1210851,"stationLocation":"Amareleja",
     "stationDistance":10.3,"temperatura":21.5,"humidade":43,
     "intensidadeVento":3.2,"intensidadeVentoKM":11.5,
     "idDireccVento":8,"direccVento":"NW","precAcumulada":0,
     "radiacao":3718.9,"pressao":1012,
     "date":"2026-05-14T13:00:00.000000Z"},
   "created":{"sec":1778760016},"updated":{"sec":1778768892}},

  {"_id":{"$id":"20260674206"},"id":"20260674206","coords":true,
   "dateTime":{"sec":1778766240},"date":"14-05-2026","hour":"14:44",
   "location":"Bragan\\u00e7a, Macedo de Cavaleiros, Vilarinho De Agroch\\u00e3o",
   "aerial":0,"meios_aquaticos":0,"man":3,"terrain":1,
   "district":"Bragan\\u00e7a","concelho":"Macedo De Cavaleiros",
   "freguesia":"Vilarinho De Agroch\\u00e3o","dico":"0405",
   "lat":41.670132822074955,"lng":-7.065156785344159,
   "naturezaCode":"4335","natureza":"Preven\\u00e7\\u00e3o a Queimadas",
   "statusCode":4,"statusColor":"FF6E02","status":"Despacho de 1\\u00ba Alerta",
   "important":false,"localidade":"Vilarinho De Agroch\\u00e3o ",
   "active":true,"sadoId":"20260674206","sharepointId":27196226,
   "heliFight":0,"heliCoord":0,"planeFight":0,"regiao":"Norte",
   "sub_regiao":"Terras de Tr\\u00e1s-os-Montes",
   "weather":{"stationId":1210612,"stationLocation":"Vinhais",
     "stationDistance":19.9,"temperatura":13,"humidade":61,
     "intensidadeVento":9.1,"intensidadeVentoKM":32.8,
     "idDireccVento":8,"direccVento":"NW","precAcumulada":0,
     "date":"2026-05-14T13:00:00.000000Z"},
   "created":{"sec":1778766497},"updated":{"sec":1778766521}},

  {"_id":{"$id":"20260674266"},"id":"20260674266","coords":true,
   "dateTime":{"sec":1778766600},"date":"14-05-2026","hour":"14:50",
   "location":"Set\\u00fabal, Set\\u00fabal, ...",
   "aerial":0,"meios_aquaticos":0,"man":2,"terrain":1,
   "district":"Set\\u00fabal","concelho":"Set\\u00fabal",
   "freguesia":"S.Juli\\u00e3o, N.S. Da Anunciada E S. Maria Da Gra\\u00e7a",
   "dico":"1512","lat":38.520138996019014,"lng":-8.926392400892976,
   "naturezaCode":"4335","natureza":"Preven\\u00e7\\u00e3o a Queimadas",
   "statusCode":5,"statusColor":"B81E1F","status":"Em Curso",
   "important":false,"localidade":"...","active":true,
   "sadoId":"20260674266","sharepointId":27196286,
   "heliFight":0,"heliCoord":0,"planeFight":0,"regiao":"Lisboa e Vale do Tejo",
   "sub_regiao":"Pen\\u00ednsula de Set\\u00fabal",
   "weather":{"stationId":1210770,"stationLocation":"Set\\u00fabal",
     "stationDistance":4.4,"temperatura":20.2,"humidade":55,
     "intensidadeVento":3.9,"intensidadeVentoKM":14,
     "idDireccVento":8,"direccVento":"NW","precAcumulada":0,
     "radiacao":3624.1,"pressao":1014.3,
     "date":"2026-05-14T13:00:00.000000Z"},
   "created":{"sec":1778766974},"updated":{"sec":1778766999}}
]}
""")

print(f"Payload com {len(PAYLOAD['data'])} ocorrências\n")

fires = []
for raw in PAYLOAD["data"]:
    fire = FogosFire.from_api(raw)
    if fire is not None:
        fires.append(fire)

print(f"Parsed: {len(fires)} ocorrências válidas\n")

for f in fires:
    print(f"=== {f.fire_id} ===")
    print(f"  {f.district}/{f.municipality}/{f.parish}")
    print(f"  coords: ({f.latitude:.4f}, {f.longitude:.4f})")
    print(f"  natureza: {f.natureza_name} (code {f.natureza_code})")
    print(f"  status: {f.status_name} (code {f.status_code})")
    print(f"  recursos: {f.operatives} ops, {f.vehicles} veic, {f.aerial} aero")
    print(f"  triage_relevant: {f.is_triage_relevant}")
    print(f"  is_terminated: {f.is_terminated}")

    if f.weather:
        print(f"  weather: T={f.weather.temperature_c}°C "
              f"H={f.weather.humidity_pct}% "
              f"V={f.weather.wind_speed_ms}m/s "
              f"({f.weather.wind_direction_text}={f.weather.wind_direction_deg}°)")

    # Testar adapter
    occ = fogos_to_occurrence(f)
    print(f"  → Occurrence: started={occ.started_at}, status={occ.status}")
    if f.weather:
        wx = fogos_weather_to_conditions(f.weather, f.updated_at)
        print(f"  → WeatherConditions: wind={wx.wind_speed_10m_ms:.1f}m/s "
              f"gust={wx.wind_gust_10m_ms:.1f}m/s "
              f"cloud_est={wx.cloud_cover_pct:.0f}%")
    print()

# Stats
relevant = [f for f in fires if f.is_triage_relevant and not f.is_terminated]
print(f"Relevantes para triagem: {len(relevant)} de {len(fires)}")
