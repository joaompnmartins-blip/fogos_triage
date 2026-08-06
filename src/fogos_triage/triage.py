"""
Serviço de triagem.

Orquestra: ocorrência → terreno + meteo → motor → resultado priorizado.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Optional

from .engine import check_crown_fire_transition, predict_surface_fire
from .fuel_models import FuelModelPT, normalize_fuel_model_num
from .schemas import (
    FireBehaviorPrediction,
    FireType,
    Occurrence,
    SeverityCategory,
    TerrainConditions,
    TriageResult,
    WeatherConditions,
)
from .severity import classify_severity
from .weather import WIND_10M_TO_20FT, derive_fire_weather


NEIGHBOURHOOD_RADIUS_M = 50.0

_DEFAULT_TERRAIN = TerrainConditions(
    elevation_m=0.0, slope_fraction=0.0, slope_degrees=0.0,
    aspect_degrees=0.0, fuel_model_num=98,
)


def _maior_combustivel(pixeis: list[tuple]) -> str:
    """Código do modelo combustível mais frequente na vizinhança.

    Só para a nota que acompanha o caso "dominante não combustível":
    diz ao operador o que existe à volta que pode arder, para a
    categoria 1 não se confundir com ausência de combustível.
    """
    c = Counter(fm.code for _, fm in pixeis if not fm.is_empty)
    return c.most_common(1)[0][0] if c else "—"


def triage_neighbourhood(
    occurrence: Occurrence,
    fuel_models: dict[int, FuelModelPT],
    terrains: list[TerrainConditions],
    weather_raw: WeatherConditions,
    live_h_pct: Optional[float] = None,
    live_w_pct: Optional[float] = None,
) -> TriageResult:
    """
    Triagem com amostragem de vizinhança (grelha densa à resolução do
    raster, até 50 m — ver LandscapeReader.sample_neighbourhood).

    O combustível é escolhido por **maioria simples sobre a vizinhança
    inteira**, não combustíveis incluídos, e tudo o resto é calculado
    para esse modelo. Entre os píxeis que o têm, o de comportamento
    mediano dá o declive e o copado; sobre ele correm os 2 cenários:
      "Vento Geral" (central) → vento sustentado (Open-Meteo)
      "Rajadas"     (gusts)   → vento de rajada (Open-Meteo), mesmo WAF

    Antes escolhia-se o píxel de ROS mediano entre os que ardiam. A
    mediana protegia contra o píxel excepcional mas não contra a
    filtragem que a precedia — os não combustíveis saíam antes de
    entrar, e a classificação descrevia só a fracção que ardia, por
    pequena que fosse.

    **O reverso desta regra**: onde o dominante é não combustível, a
    ocorrência fica sem previsão de fogo mesmo havendo combustível por
    perto (47% das ocorrências, medido sobre 400 reais). As notas dizem
    sempre quanto combustível ficou de fora, para a categoria 1 não ser
    lida como ausência de combustível.
    """
    # (terreno, modelo) de cada píxel — TODOS, incluindo os não
    # combustíveis. É deliberado que os NB entrem: a maioria conta-se
    # sobre a vizinhança inteira, não sobre a parte que arde.
    pixeis: list[tuple[TerrainConditions, FuelModelPT]] = []
    for terrain in terrains:
        fm = fuel_models.get(normalize_fuel_model_num(terrain.fuel_model_num))
        if fm is not None:
            pixeis.append((terrain, fm))

    if not pixeis:
        wx0 = derive_fire_weather(weather_raw, live_h_pct=live_h_pct, live_w_pct=live_w_pct)
        return triage_occurrence(occurrence, fuel_models, _DEFAULT_TERRAIN, wx0)

    # Modelo dominante por MAIORIA SIMPLES sobre a vizinhança toda.
    #
    # Substituiu a mediana do ROS sobre os píxeis que ardiam. A mediana
    # era robusta contra o píxel excepcional, mas não contra a filtragem
    # que a precedia: os não combustíveis eram descartados antes de
    # entrar, e a mediana dos sobreviventes descrevia só a fracção que
    # ardia. Numa ocorrência em Paranhos (Porto), 69 dos 81 píxeis eram
    # urbanos e a classificação saiu de 12 píxeis de mato disperso.
    #
    # A consequência desta regra tem de ser conhecida por quem a lê:
    # quando o dominante é não combustível, a ocorrência fica sem
    # previsão de fogo, mesmo havendo combustível na vizinhança. Medido
    # sobre 400 ocorrências reais, acontece em 47% delas. É por isso que
    # as notas abaixo dizem sempre quanto combustível ficou de fora — a
    # categoria 1 nunca deve chegar ao operador sem esse contexto.
    contagem = Counter(fm.num for _, fm in pixeis)
    num_dominante, n_dominante = contagem.most_common(1)[0]
    do_dominante = [(t, fm) for t, fm in pixeis if fm.num == num_dominante]
    fm_dominante = do_dominante[0][1]

    n_arde = sum(1 for _, fm in pixeis if not fm.is_empty)
    # O `normalize_fuel_model_num` colapsa os códigos NB do Scott &
    # Burgan (91-99) todos em FM98, portanto o código do modelo não
    # distingue urbano de água, rocha ou regadio. Para quem lê a
    # triagem a diferença importa — 91 num centro urbano e 93 em
    # regadio pedem decisões diferentes —, por isso o código do raster
    # vai na nota quando difere do normalizado.
    brutos = Counter(t.fuel_model_num for t, fm in do_dominante)
    bruto_dominante = brutos.most_common(1)[0][0]
    sufixo_bruto = (f" (raster: {bruto_dominante})"
                    if bruto_dominante != num_dominante else "")
    notas_base = [
        f"Modelo dominante {fm_dominante.code}{sufixo_bruto}: "
        f"{n_dominante}/{len(pixeis)} px, raio {NEIGHBOURHOOD_RADIUS_M:.0f}m"
    ]

    resultados = []
    for terrain, fm in do_dominante:
        # `fm.depth` (pés) é o que permite calcular o WAF do leito —
        # sem ele cai-se no valor por omissão. O WAF continua a ser
        # calculado por píxel: mesmo dentro de um só modelo, a cobertura
        # e a altura do copado variam de píxel para píxel.
        wx = derive_fire_weather(
            weather_raw,
            stand_height_m=terrain.stand_height_m or 0.0,
            canopy_cover_pct=terrain.canopy_cover_pct or 0.0,
            has_overstory=(terrain.canopy_cover_pct or 0) > 10,
            live_h_pct=live_h_pct,
            live_w_pct=live_w_pct,
            fuel_bed_depth_ft=fm.depth,
        )
        try:
            resultados.append((predict_surface_fire(fm, terrain, wx, ""), terrain, fm, wx))
        except Exception:
            continue

    if not resultados:
        wx0 = derive_fire_weather(weather_raw, live_h_pct=live_h_pct, live_w_pct=live_w_pct)
        return triage_occurrence(occurrence, fuel_models, do_dominante[0][0], wx0)

    # Píxel representativo: o de comportamento mediano DENTRO do modelo
    # dominante. Já não decide qual o combustível — só de que ponto vêm o
    # declive e o copado —, e continua a proteger contra o píxel de
    # declive excepcional.
    resultados.sort(key=lambda x: x[0].ros_m_per_min)
    central_pred, central_terrain, central_fm, central_wx = resultados[len(resultados) // 2]
    central_pred = replace(central_pred, scenario="central")

    gust_wx = gust_weather(central_wx)
    gust_pred = predict_surface_fire(central_fm, central_terrain, gust_wx, "gusts")

    notes = list(notas_base)
    if fm_dominante.is_empty:
        # O caso que o operador tem de conseguir distinguir de "não há
        # nada a arder aqui".
        notes.append(
            f"Dominante NÃO COMBUSTÍVEL — sem previsão de fogo. "
            f"{n_arde}/{len(pixeis)} px combustíveis na vizinhança"
            + (f" (maior: {_maior_combustivel(pixeis)})" if n_arde else "")
        )
    elif n_arde < len(pixeis):
        notes.append(f"{n_arde}/{len(pixeis)} px combustíveis na vizinhança")

    central_pred = _check_crown(central_pred, central_terrain, notes)
    gust_pred = _check_crown(gust_pred, central_terrain, notes)

    dominant_fm_code = fm_dominante.code

    waf = (central_wx.wind_midflame_ms / central_wx.wind_speed_10m_ms
           if (central_wx.wind_speed_10m_ms or 0) > 0 else 0.0)

    priority, score = compute_priority(central_pred, occurrence)

    return TriageResult(
        occurrence=occurrence,
        terrain=central_terrain,
        weather=central_wx,
        predictions=[central_pred, gust_pred],
        priority=priority,
        priority_score=score,
        fuel_model_used=dominant_fm_code,
        wind_adjustment_factor=waf,
        notes=notes,
    )


def triage_occurrence(
    occurrence: Occurrence,
    fuel_models: dict[int, FuelModelPT],
    terrain: TerrainConditions,
    weather: WeatherConditions,
) -> TriageResult:
    """
    Faz a triagem completa de uma ocorrência.

    Inputs já preparados (separation of concerns):
    - occurrence: vem da fogos.pt
    - terrain: já feita amostragem dos rasters
    - weather: já enriquecida com derivações de fogo

    Devolve TriageResult com 2 cenários: "Vento Geral" (central, vento
    sustentado) e "Rajadas" (gusts, vento de rajada do Open-Meteo).
    """
    normalized_num = normalize_fuel_model_num(terrain.fuel_model_num)
    fm = fuel_models.get(normalized_num)
    if normalized_num != terrain.fuel_model_num:
        notes = [f"FM{terrain.fuel_model_num} (NB Scott&Burgan) → não combustível"]
    elif fm is None:
        fm = fuel_models.get(98)
        notes = [f"Modelo {terrain.fuel_model_num} desconhecido, usando FM98"]
    else:
        notes = []

    # Verificar overstory para WAF
    has_overstory = (terrain.canopy_cover_pct is not None
                     and terrain.canopy_cover_pct > 10)
    stand_h = terrain.stand_height_m or 0.0

    # Enriquecer meteo se ainda não foi feito
    if weather.wind_midflame_ms is None:
        weather = derive_fire_weather(
            weather,
            stand_height_m=stand_h,
            canopy_cover_pct=terrain.canopy_cover_pct or 0.0,
            has_overstory=has_overstory,
            fuel_bed_depth_ft=fm.depth,
        )

    # 2 cenários: "Vento Geral" (central) e "Rajadas" (gusts)
    central = _predict_scenario(fm, terrain, weather, "central")
    gusts = _predict_scenario(fm, terrain, gust_weather(weather), "gusts")

    central = _check_crown(central, terrain, notes)
    gusts = _check_crown(gusts, terrain, notes)

    predictions = [central, gusts]

    # WAF efetivo usado
    waf = (weather.wind_midflame_ms / weather.wind_speed_10m_ms
           if weather.wind_speed_10m_ms > 0 else 0)

    # Prioridade
    priority, score = compute_priority(central, occurrence)

    return TriageResult(
        occurrence=occurrence,
        terrain=terrain,
        weather=weather,
        predictions=predictions,
        priority=priority,
        priority_score=score,
        fuel_model_used=fm.code,
        wind_adjustment_factor=waf,
        notes=notes,
    )


def _predict_scenario(
    fm: FuelModelPT,
    terrain: TerrainConditions,
    weather: WeatherConditions,
    scenario_name: str,
) -> FireBehaviorPrediction:
    return predict_surface_fire(fm, terrain, weather, scenario_name)


def gust_weather(wx: WeatherConditions) -> WeatherConditions:
    """
    Substitui o vento sustentado pela velocidade de rajada
    (wind_gusts_10m, Open-Meteo) no vento midflame (única entrada de vento
    que o motor Rothermel lê — engine.py nunca usa wind_speed_10m_ms),
    aplicando o mesmo WAF já calculado para o vento sustentado (não uma
    percentagem sintética). Humidades dos combustíveis mantêm-se — uma
    rajada dura segundos, não muda a humidade.

    wind_speed_10m_ms e wind_gust_10m_ms mantêm-se ambos no valor
    original (não sobrepostos) — só são campos de referência/exibição,
    para o vento sustentado e a rajada continuarem distintos mesmo
    quando é a rajada a conduzir a simulação.

    `wind_20ft_ms` **tem** de acompanhar, ao contrário do vento a 10 m.
    Não é um campo de exibição: é a entrada de quem aplica o WAF por
    píxel (a simulação) e de quem monta o campo de vento do WindNinja.
    Deixá-lo no valor sustentado fazia o fogo propagar com a rajada
    enquanto essas duas peças usavam o vento sustentado — que é
    exactamente a avaria apanhada em produção a 2026-07-30, quando o
    windfield lia o `wind_speed_10m_ms` e mandava 3.0 m/s ao sidecar com
    o fogo a correr a 5.9.

    Usada pelo cenário "Rajadas" da triagem (ver triage_occurrence /
    triage_neighbourhood) e pelo override "usar rajadas" da simulação
    ForeFire (services/api/routes_meta.py, routes_freesim.py).
    """
    if not wx.wind_speed_10m_ms or wx.wind_gust_10m_ms is None:
        return wx
    waf = (wx.wind_midflame_ms or 0) / wx.wind_speed_10m_ms
    return replace(
        wx,
        wind_midflame_ms=wx.wind_gust_10m_ms * waf,
        # Só quando já vinha preenchido: `wind_20ft_ms` estar a None
        # significa que o `derive_fire_weather` não correu, e inventá-lo
        # aqui esconderia esse facto a quem o lê a jusante.
        wind_20ft_ms=(wx.wind_gust_10m_ms * WIND_10M_TO_20FT
                      if wx.wind_20ft_ms is not None else None),
    )


def _check_crown(
    pred: FireBehaviorPrediction,
    terrain: TerrainConditions,
    notes: list[str],
) -> FireBehaviorPrediction:
    """Aplica o critério de transição para fogo de copas (Van Wagner) a um
    cenário. Independente por cenário — vento de rajada pode cruzar o
    limiar de copas mesmo quando o vento sustentado não cruza."""
    if not (terrain.canopy_base_height_m and pred.fireline_intensity_kw_m > 0):
        return pred
    transition, I_crit = check_crown_fire_transition(
        pred.fireline_intensity_kw_m,
        terrain.canopy_base_height_m,
        foliar_moisture_pct=100.0,
    )
    if transition:
        pred = replace(pred, fire_type=FireType.TORCHING)
        notes.append(
            f"Transição para fogo de copas possível no cenário '{pred.scenario}' "
            f"(I_critical={I_crit:.0f} kW/m)"
        )
    return pred


def compute_priority(
    behavior: FireBehaviorPrediction,
    occurrence: Occurrence,
) -> tuple[SeverityCategory, float]:
    """
    Classificação de severidade 1-7 (Tedim et al. 2018, Tabela 3) — ver
    src/fogos_triage/severity.py para os limiares, a fonte completa, e
    a justificação da substituição do antigo score composto 0-100
    (sem fonte publicada — ver CLASSIFICACAO_TRIAGEM.md).

    A FLI (fireline intensity) é o critério pivô — é o que a própria
    Tabela 3 usa para capacidade de controlo. `occurrence` mantém-se
    como parâmetro por compatibilidade de assinatura (não usado na
    classificação; era também ignorado na fórmula anterior).
    """
    category = classify_severity(behavior.fireline_intensity_kw_m)
    return SeverityCategory(category), behavior.fireline_intensity_kw_m
