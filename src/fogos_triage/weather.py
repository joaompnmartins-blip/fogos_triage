"""
Módulo de meteorologia.

Tem duas funções principais:
1. fetch_weather() - vai buscar dados à Open-Meteo para uma coordenada
2. derive_fire_weather() - calcula humidades dos combustíveis e wind midflame
   a partir das condições atmosféricas + características da vegetação

Humidades dos combustíveis mortos: equações Simard 1968 (temperatura em
Fahrenheit, limiares de RH: ≤10%, 11-50%, >50%).

Humidades dos combustíveis vivos: NÃO se calculam aqui — vêm de
`fogos_triage.lfmc_climatologia` (climatologia sazonal + precipitação
acumulada a 180 dias, ajustada a medições de campo do ICNF) e entram em
derive_fire_weather como `live_h_pct`/`live_w_pct`. A precipitação
acumulada obtém-se com fetch_precipitation_sum, abaixo.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
from datetime import datetime, timedelta
from typing import Optional

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from .schemas import WeatherConditions
from .waf import waf_albini_baughman

log = logging.getLogger(__name__)

# Factor de conversão do vento a 10 m (altura meteorológica padrão) para
# 20 pés = 6.1 m (altura de referência do NFDRS, sobre a qual o WAF de
# Albini & Baughman 1979 é definido).
#
# É uma DIVISÃO por 1.15, seguindo o RMRS-GTR-266 §1 (Andrews 2012, USDA
# FS, citando Turner & Lawson 1978) — `WAF/RMRS-GTR-266_WAF_reference.md`.
#
# Diverge de `modelos_PFernandes/MODELO_FOGO_REFERENCIA.md` §3, que
# manda multiplicar. A divergência é deliberada e está documentada no
# WAF_PLAN.md: 20 pés são 6.10 m, ABAIXO dos 10 m, e o vento cresce com a
# altura, logo U(20 ft) tem de ser MENOR que U(10 m). O perfil
# logarítmico confirma o próprio 1.15 — resolver
# ln(10/z0)/ln(6.096/z0) = 1.15 dá z0 ~= 0.23 m, rugosidade de pastagem
# alta ou mato baixo, plausível para estações de meteorologia de
# incêndios. O que estava em disputa era só de que lado da fracção ficava.
#
# Custo desta escolha: a tabela §7.3 do Fernandes deixou de poder validar
# a cadeia toda, porque foi gerada com o x1.15. O
# `test_referencia_fernandes.py` passou a alimentar o motor com o vento a
# 20 pés que a referência usou, isolando o passo em disputa — continua a
# validar o Rothermel e o WAF, já não valida esta linha.
WIND_10M_TO_20FT = 1.0 / 1.15

# WAF usado quando o modelo de combustível não é conhecido — não dá para
# calcular a fórmula do leito sem a espessura. É o valor que a escada
# anterior devolvia no ramo sem coberto, e mantém-se para o caminho da
# simulação não mudar de comportamento sem ser por decisão explícita.
WAF_SEM_MODELO = 0.40

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Variáveis horárias pedidas — mesma lista para previsão e arquivo
# histórico (a API de arquivo usa exactamente os mesmos nomes).
_HOURLY_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "wind_gusts_10m",
    "wind_direction_10m",
    "precipitation",
    "cloud_cover",
]

# Acima disto (dias), a API de previsão (só até 92 dias de past_days)
# deixa de conseguir cobrir start_time — passa-se para a API de arquivo
# histórico (ERA5, desde 1940).
_FORECAST_PAST_DAYS_MAX = 92


def _parse_open_meteo_hourly(data: dict, start_time: datetime, hours_ahead: int) -> list[WeatherConditions]:
    """Converte a resposta 'hourly' (comum às APIs de previsão e de
    arquivo — mesma forma, mesmos nomes de variável) em WeatherConditions,
    a partir de start_time (inclusive) até hours_ahead horas."""
    hourly = data["hourly"]
    out: list[WeatherConditions] = []
    precip_arr = hourly["precipitation"]

    for i, time_str in enumerate(hourly["time"]):
        t = datetime.fromisoformat(time_str)
        if t < start_time:
            continue
        if len(out) >= hours_ahead:
            break

        precip_24h = sum(precip_arr[max(0, i-24):i+1])

        out.append(WeatherConditions(
            timestamp=t,
            temperature_c=hourly["temperature_2m"][i],
            relative_humidity_pct=hourly["relative_humidity_2m"][i],
            wind_speed_10m_ms=hourly["wind_speed_10m"][i],
            wind_gust_10m_ms=hourly["wind_gusts_10m"][i],
            wind_direction_deg=hourly["wind_direction_10m"][i],
            precipitation_mm_24h=precip_24h,
            cloud_cover_pct=hourly["cloud_cover"][i],
        ))

    return out


async def fetch_open_meteo(
    latitude: float,
    longitude: float,
    hours_ahead: int = 5,
    client: Optional["httpx.AsyncClient"] = None,
    start_time: Optional[datetime] = None,
) -> list[WeatherConditions]:
    """
    Vai buscar condições à Open-Meteo (API de previsão) a partir de
    start_time (default None = agora) para as próximas hours_ahead horas.
    Devolve uma lista de WeatherConditions horárias.

    start_time no passado (até 92 dias atrás — limite da API de
    previsão) usa o parâmetro `past_days`; mais antigo do que isso não
    é coberto por esta função — ver fetch_weather_for_start_time, que
    escolhe automaticamente a API de arquivo histórico nesse caso.
    start_time no futuro estende `forecast_days` conforme necessário
    (máximo 16 dias, limite da própria API).

    Notas:
    - Usa o modelo 'best_match' que para Portugal é tipicamente ECMWF IFS
    - Inclui rajadas (gusts) para cenário de pior caso
    """
    if not HAS_HTTPX:
        raise ImportError("httpx é necessário para fetch_open_meteo")

    effective_start = start_time or datetime.now()

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(_HOURLY_VARS),
        "models": "best_match",
        "timezone": "Europe/Lisbon",
        "wind_speed_unit": "ms",
    }

    days_ahead = max(0, (effective_start.date() - datetime.now().date()).days)
    params["forecast_days"] = min(16, days_ahead + math.ceil(hours_ahead / 24) + 1)

    days_past = max(0, (datetime.now().date() - effective_start.date()).days)
    if days_past > 0:
        params["past_days"] = min(_FORECAST_PAST_DAYS_MAX, days_past)

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=10.0)

    try:
        response = await client.get(OPEN_METEO_URL, params=params)
        response.raise_for_status()
        data = response.json()
    finally:
        if own_client:
            await client.aclose()

    return _parse_open_meteo_hourly(data, effective_start, hours_ahead)


async def fetch_open_meteo_archive(
    latitude: float,
    longitude: float,
    start_time: datetime,
    hours_ahead: int = 5,
    client: Optional["httpx.AsyncClient"] = None,
) -> list[WeatherConditions]:
    """
    Vai buscar condições históricas à API de arquivo Open-Meteo
    (ERA5, dados desde 1940) — usada quando start_time é mais antigo do
    que o limite de past_days da API de previsão (92 dias). Mesmas
    variáveis/nomes, mas parâmetros start_date/end_date em vez de
    forecast_days/past_days, e sem o parâmetro `models` (é reanálise,
    não previsão por modelo).

    Aviso: ERA5 é reanálise, não previsão operacional — resolução
    espacial mais grosseira (grelha ~9-31km) do que o modelo de
    previsão usado para datas recentes/futuras; vento histórico é por
    isso menos preciso localmente.
    """
    if not HAS_HTTPX:
        raise ImportError("httpx é necessário para fetch_open_meteo_archive")

    end_date = start_time + timedelta(days=math.ceil(hours_ahead / 24) + 1)
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(_HOURLY_VARS),
        "start_date": start_time.date().isoformat(),
        "end_date": end_date.date().isoformat(),
        "timezone": "Europe/Lisbon",
        "wind_speed_unit": "ms",
    }

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=10.0)

    try:
        response = await client.get(OPEN_METEO_ARCHIVE_URL, params=params)
        response.raise_for_status()
        data = response.json()
    finally:
        if own_client:
            await client.aclose()

    return _parse_open_meteo_hourly(data, start_time, hours_ahead)


async def fetch_precipitation_sum(
    latitude: float,
    longitude: float,
    ate: Optional[datetime] = None,
    dias: int = 180,
    client: Optional["httpx.AsyncClient"] = None,
    tentativas: int = 4,
) -> Optional[float]:
    """
    Precipitação acumulada (mm) nos `dias` anteriores a `ate`.

    É o preditor da climatologia de humidade dos combustíveis vivos —
    ver `lfmc_climatologia`. O acumulado de 180 dias é o que capta a
    recarga hídrica do Inverno/Primavera, e é isso que distingue um ano
    seco de um ano normal: nas medições de campo do ICNF, 2022 (308 mm)
    deu 81.6% de LFMC contra 99.5% em 2021 (604 mm).

    Usa o arquivo (ERA5), que cobre 1940 até ao presente — por isso
    funciona para qualquer `start_time` de simulação, incluindo incêndios
    anteriores a haver satélite com estas bandas.

    O arquivo devolve 429 depois de poucos pedidos seguidos, daí o
    backoff. Devolve None se não conseguir — quem chama decide o
    fallback (não se inventa precipitação).
    """
    if not HAS_HTTPX:
        raise ImportError("httpx é necessário para fetch_precipitation_sum")

    # O arquivo serve até hoje inclusive e devolve 400 para datas
    # futuras (confirmado: end_date=amanhã dá "out of allowed range").
    # Numa simulação com start_time no futuro, a janela relevante é
    # mesmo a que termina agora — a chuva que ainda não caiu não conta
    # para a água que está no solo hoje.
    fim = min((ate or datetime.now()).date(), datetime.now().date())
    inicio = fim - timedelta(days=dias)
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": inicio.isoformat(),
        "end_date": fim.isoformat(),
        "daily": "precipitation_sum",
        "timezone": "Europe/Lisbon",
    }

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0)
    try:
        for tentativa in range(1, tentativas + 1):
            try:
                resp = await client.get(OPEN_METEO_ARCHIVE_URL, params=params)
                resp.raise_for_status()
                valores = [v for v in resp.json()["daily"]["precipitation_sum"] if v is not None]
                if not valores:
                    log.warning("Open-Meteo arquivo sem precipitação para %.4f,%.4f", latitude, longitude)
                    return None
                return float(sum(valores))
            except Exception as exc:
                if tentativa == tentativas:
                    log.warning(
                        "Precipitação acumulada falhou para %.4f,%.4f (%s tentativas): %s",
                        latitude, longitude, tentativas, exc,
                    )
                    return None
                await asyncio.sleep(2 ** tentativa)
    finally:
        if own_client:
            await client.aclose()
    return None


async def fetch_weather_for_start_time(
    latitude: float,
    longitude: float,
    start_time: Optional[datetime],
    hours_ahead: int = 5,
    client: Optional["httpx.AsyncClient"] = None,
) -> list[WeatherConditions]:
    """
    Dispatcher: escolhe a API de previsão (com past_days) ou a de
    arquivo histórico consoante o quão antigo start_time é.
    start_time=None mantém o comportamento actual ("agora").
    """
    days_ago = (datetime.now() - start_time).days if start_time else -1
    if days_ago <= _FORECAST_PAST_DAYS_MAX:
        return await fetch_open_meteo(latitude, longitude, hours_ahead, client, start_time=start_time)
    return await fetch_open_meteo_archive(latitude, longitude, start_time, hours_ahead, client)


def estimate_fine_dead_moisture_pct(
    temperature_c: float,
    rh_pct: float,
    cloud_cover_pct: float,
    is_shaded: bool = False,
) -> float:
    """
    Estimativa da humidade do combustível fino morto (1h) em percentagem.

    Equações de Simard 1968 (Reference Fuel Moisture). A temperatura deve
    ser convertida para Fahrenheit conforme o artigo original.
    Limiares de RH: ≤10%, 11–50%, >50%.
    """
    T_f = temperature_c * 9.0 / 5.0 + 32.0  # Celsius → Fahrenheit

    if rh_pct <= 10:
        rfm = 0.03229 + 0.281073 * rh_pct - 0.000578 * T_f
    elif rh_pct <= 50:
        rfm = 2.22749 + 0.160107 * rh_pct - 0.014784 * T_f
    else:
        rfm = 21.0606 + 0.005565 * rh_pct**2 - 0.0003505 * rh_pct * T_f - 0.483199 * rh_pct

    rfm = max(1.0, min(rfm, 40.0))

    # Ajuste por exposição solar
    sun_factor = (100.0 - cloud_cover_pct) / 100.0
    if not is_shaded and sun_factor > 0.5:
        rfm -= 2.0 * (sun_factor - 0.5) * 2.0
    elif is_shaded or sun_factor < 0.5:
        rfm += 1.0 * (1.0 - sun_factor)

    return max(2.0, min(rfm, 40.0))


# ---------------------------------------------------------------------------
# Nota: a estimativa de humidade dos combustíveis vivos por VIIRS/GEE
# (Yebra 2007) esteve aqui e foi removida. Validada contra 654 medições de
# campo do ICNF (LFM/), reprovou: no herbáceo dava viés de +110 pontos
# percentuais e correlação ZERO (r = -0.03) com o terreno, porque o NDVI de
# um píxel de 500 m mede o verde das árvores enquanto a herbácea está
# morta. Substituída por `fogos_triage.lfmc_climatologia` (climatologia
# sazonal + precipitação acumulada a 180 dias, ajustada aos dados
# portugueses). Ver LFMC_CLIMATOLOGIA_PLAN.md, incluindo o que mais foi
# testado e rejeitado — os modelos MODIS que os autores recomendam saem
# ainda piores.
# ---------------------------------------------------------------------------



def derive_fire_weather(
    wx: WeatherConditions,
    stand_height_m: float = 0.0,
    canopy_cover_pct: float = 0.0,
    has_overstory: bool = False,
    live_h_pct: Optional[float] = None,
    live_w_pct: Optional[float] = None,
    fuel_bed_depth_ft: Optional[float] = None,
) -> WeatherConditions:
    """
    Enriquece WeatherConditions com derivadas necessárias para o motor de fogo:
    - vento midflame (após aplicar WAF)
    - humidades dos combustíveis 1h, 10h, 100h (Simard 1968)
    - humidades dos combustíveis vivos (Yebra 2007 via GEE, ou fallback sazonal)

    m_10h  = 1.28 × m_1h        (Rothermel 1972)
    m_100h = m_10h + 1.0%

    live_h_pct / live_w_pct: se fornecidos (de lfmc_climatologia), usados
    directamente; caso contrário, fallback conservador (Portugal, verão).

    O WAF (Wind Adjustment Factor) vem de Albini & Baughman 1979 e depende de:
    - presença de coberto (overstory)
    - altura da vegetação
    - cobertura de copas

    Tabelas típicas (Andrews 2012, BehavePlus):
    - Sem coberto, vegetação curta (<3 ft): WAF ≈ 0.4
    - Sem coberto, vegetação alta (>6 ft): WAF ≈ 0.5
    - Com coberto fechado (>50% cover): WAF ≈ 0.1-0.2
    - Com coberto aberto: WAF ≈ 0.2-0.3
    """
    # WAF de Albini & Baughman 1979 — ver fogos_triage.waf, que substituiu
    # uma escada de quatro degraus fixos (0.10/0.25/0.40/0.50). Medido
    # contra os 18 modelos da tabela §7.3 da referência: a escada dava
    # |erro| mediano de 10.3% no ROS e 12/18 dentro da tolerância; a
    # fórmula dá 0.1% e 18/18.
    #
    # Sem `fuel_bed_depth_ft` não há como calcular a fórmula do leito, e
    # cai-se no valor por omissão.
    #
    # O copado entra sempre que existe, sem passar pelo `has_overstory`.
    # Os dois não são a mesma pergunta: o `has_overstory` decide se o
    # combustível está à sombra (humidades), e para isso um limiar faz
    # sentido; o abrigo do vento é contínuo, e quem arbitra se o copado
    # chega a abrigar é o `min()` das duas fórmulas lá dentro.
    # `> 0` e não só `is not None`: o FM98 (não combustível — urbano,
    # água, os códigos NB do Scott & Burgan) tem `depth = 0`, e a fórmula
    # do leito tem um `ln` que não o aceita. O `waf_sem_abrigo` levanta
    # ValueError, e sem este guarda a excepção subia até ao worker e
    # matava a triagem INTEIRA da ocorrência — não só a do píxel não
    # combustível. Apanhado em produção a 2026-07-30, nos logs do worker:
    # "Erro a triar 20261073916: espessura do leito tem de ser positiva".
    #
    # Um píxel não combustível dá ROS 0 de qualquer maneira, portanto o
    # valor do WAF é indiferente — o que não é indiferente é rebentar.
    # Mesmo tratamento que `simulation._midflame_no_ponto` já fazia.
    wind_20ft = wx.wind_speed_10m_ms * WIND_10M_TO_20FT
    if fuel_bed_depth_ft is not None and fuel_bed_depth_ft > 0:
        waf = waf_albini_baughman(
            fuel_bed_depth_ft,
            altura_copado_m=stand_height_m,
            cobertura_frac=(canopy_cover_pct / 100.0) if canopy_cover_pct else None,
        )
    else:
        waf = WAF_SEM_MODELO

    # Cadeia completa de conversão (MODELO_FOGO_REFERENCIA.md §3):
    #     U(10 m) -> U(20 ft) = U(10 m) x 1.15 -> U_midflame = U(20 ft) x WAF
    #
    # O passo dos 10 m para os 20 pés faltava, e sem ele o vento midflame
    # saía 13% abaixo em TUDO — triagem e simulação, todos os modelos.
    # O WAF de Albini & Baughman é definido sobre o vento a 20 pés (6.1 m),
    # que é a altura de referência do NFDRS; a meteorologia dá 10 m.
    wind_midflame = wind_20ft * waf

    # Humidades dos combustíveis mortos (Simard 1968 + Rothermel 1972)
    m_1h = estimate_fine_dead_moisture_pct(
        wx.temperature_c, wx.relative_humidity_pct, wx.cloud_cover_pct,
        is_shaded=has_overstory,
    )
    m_10h = 1.28 * m_1h
    m_100h = m_10h + 1.0

    # Live fuel moisture — de GEE/VIIRS se disponível, senão fallback
    m_live_h = live_h_pct if live_h_pct is not None else 60.0
    m_live_w = live_w_pct if live_w_pct is not None else 80.0

    return WeatherConditions(
        timestamp=wx.timestamp,
        temperature_c=wx.temperature_c,
        relative_humidity_pct=wx.relative_humidity_pct,
        wind_speed_10m_ms=wx.wind_speed_10m_ms,
        wind_gust_10m_ms=wx.wind_gust_10m_ms,
        wind_direction_deg=wx.wind_direction_deg,
        precipitation_mm_24h=wx.precipitation_mm_24h,
        cloud_cover_pct=wx.cloud_cover_pct,
        wind_midflame_ms=wind_midflame,
        wind_20ft_ms=wind_20ft,
        fuel_moisture_1h_pct=m_1h,
        fuel_moisture_10h_pct=m_10h,
        fuel_moisture_100h_pct=m_100h,
        fuel_moisture_live_h_pct=m_live_h,
        fuel_moisture_live_w_pct=m_live_w,
    )
