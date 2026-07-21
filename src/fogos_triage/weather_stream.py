"""
Weather Stream File (.WXS) — formato nativo do FARSITE.

Série meteorológica horária real (tipicamente de uma estação RAWS),
usada como override no Simulador em vez do Open-Meteo — mesmo
propósito de `fetch_open_meteo()`, mesmo tipo de devolução
(`list[WeatherConditions]` por enriquecer via `derive_fire_weather()`
no chamador), só a origem dos dados muda.

Formato (confirmado via documentação FARSITE, owfflammaphelp62.
firenet.gov):

    RAWS_ELEVATION: 6
    RAWS_UNITS: METRIC
    Year Mth Day Time Temp RH HrlyPcp WindSpd WindDir CloudCov
    2026 7 21 0000 19 93 0 15 343 45
    ...

`RAWS_UNITS: METRIC` — vento a 10m em km/h (inteiro), temperatura em
°C, precipitação em mm. O ficheiro não converte valores ao mudar de
unidade, só o cabeçalho — por isso só METRIC é suportado aqui (o
ficheiro tem de estar mesmo nessas unidades). `Time` em HHMM.

Sem coluna de rajada (gust) neste formato — `wind_gust_10m_ms` fica
igual a `wind_speed_10m_ms` (mesmo padrão já usado no fallback estático
de `routes_meta.py` quando não há rajada real).

Timestamps devolvidos são naive (sem tzinfo), representando hora local
de Portugal — mesma convenção já usada pelos datetimes devolvidos por
`fetch_open_meteo()` (que já vêm em hora de Lisboa da API, sem tzinfo
explícito).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .schemas import WeatherConditions

_EXPECTED_COLUMNS = ["Year", "Mth", "Day", "Time", "Temp", "RH", "HrlyPcp", "WindSpd", "WindDir", "CloudCov"]


def parse_weather_stream(text: str) -> list[WeatherConditions]:
    """Parseia um Weather Stream File (.WXS) FARSITE em condições
    horárias brutas — hora 0 = primeira linha de dados do ficheiro.

    Levanta ValueError com o número da linha em causa se o cabeçalho
    não tiver RAWS_UNITS: METRIC, ou se alguma linha de dados não tiver
    o número de colunas esperado ou valores não numéricos.
    """
    lines = text.splitlines()

    units: Optional[str] = None
    header_end_idx: Optional[int] = None
    for i, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        if line.upper().startswith("RAWS_UNITS"):
            _, _, value = line.partition(":")
            units = value.strip().upper()
        elif line.upper().startswith("RAWS_ELEVATION"):
            continue
        elif line.split()[0] == "Year":
            header_end_idx = i
            break

    if header_end_idx is None:
        raise ValueError(
            "Weather Stream: não encontrei a linha de cabeçalho de colunas "
            "(\"Year Mth Day Time Temp RH HrlyPcp WindSpd WindDir CloudCov\")"
        )
    if units is None:
        raise ValueError("Weather Stream: falta RAWS_UNITS no cabeçalho")
    if units != "METRIC":
        raise ValueError(
            f"Weather Stream: RAWS_UNITS={units!r} não suportado — só METRIC "
            "é aceite (vento km/h, temperatura °C, precipitação mm)"
        )

    precip_mm: list[float] = []
    rows_raw: list[tuple[int, list[str]]] = []
    for i in range(header_end_idx + 1, len(lines)):
        line = lines[i].strip()
        if not line:
            continue
        rows_raw.append((i + 1, line.split()))

    if not rows_raw:
        raise ValueError("Weather Stream: nenhuma linha de dados encontrada após o cabeçalho")

    for line_num, fields in rows_raw:
        if len(fields) != len(_EXPECTED_COLUMNS):
            raise ValueError(
                f"Weather Stream: linha {line_num}: esperava {len(_EXPECTED_COLUMNS)} "
                f"colunas ({' '.join(_EXPECTED_COLUMNS)}), encontrei {len(fields)}"
            )
        try:
            hrly_pcp = float(fields[6])
        except ValueError as exc:
            raise ValueError(f"Weather Stream: linha {line_num}: HrlyPcp inválido ({fields[6]!r})") from exc
        precip_mm.append(hrly_pcp)

    out: list[WeatherConditions] = []
    for idx, (line_num, fields) in enumerate(rows_raw):
        try:
            year, mth, day = int(fields[0]), int(fields[1]), int(fields[2])
            time_raw = fields[3].zfill(4)
            hour, minute = int(time_raw[:2]), int(time_raw[2:])
            timestamp = datetime(year, mth, day, hour, minute)

            temperature_c = float(fields[4])
            relative_humidity_pct = float(fields[5])
            wind_speed_10m_ms = float(fields[7]) / 3.6  # km/h -> m/s
            wind_direction_deg = float(fields[8])
            cloud_cover_pct = float(fields[9])
        except ValueError as exc:
            raise ValueError(f"Weather Stream: linha {line_num}: valor inválido ({exc})") from exc

        precip_24h = sum(precip_mm[max(0, idx - 24):idx + 1])

        out.append(WeatherConditions(
            timestamp=timestamp,
            temperature_c=temperature_c,
            relative_humidity_pct=relative_humidity_pct,
            wind_speed_10m_ms=wind_speed_10m_ms,
            wind_gust_10m_ms=wind_speed_10m_ms,
            wind_direction_deg=wind_direction_deg,
            precipitation_mm_24h=precip_24h,
            cloud_cover_pct=cloud_cover_pct,
        ))

    return out
