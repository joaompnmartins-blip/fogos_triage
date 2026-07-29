#!/usr/bin/env python3
"""
Ajusta a climatologia de humidade dos combustíveis vivos (LFMC) às
medições de campo do ICNF e escreve `data/lfmc_climatologia_pt.csv`.

    python scripts/ajusta_lfmc_climatologia.py

Modelo (ver LFMC_CLIMATOLOGIA_PLAN.md para a justificação e para o que
foi testado e rejeitado):

    LFMC = a0 + a1·cos(θ) + a2·sin(θ) + a3·cos(2θ) + a4·sin(2θ) + β·P180
    θ = 2π · dia_do_ano / 365
    P180 = precipitação acumulada nos 180 dias anteriores, mm

Correr isto de novo quando chegarem medições novas (2023+). O CSV que
produz é a fonte de verdade em runtime; este script é o registo
reproduzível de como os coeficientes saíram.

Precisa da série diária de precipitação nos sítios de amostragem, que vem
do arquivo Open-Meteo (ERA5, sem autenticação) e fica em cache — o
primeiro arranque demora alguns minutos, os seguintes são instantâneos.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics as st
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
CAMPO = RAIZ / "LFM" / "lfmc_pt_field_measurements_clean.csv"
DESTINO = RAIZ / "data" / "lfmc_climatologia_pt.csv"
CACHE = RAIZ / "LFM" / ".meteo_cache_1991_2022.json"

# ATENÇÃO: coordenadas APROXIMADAS. O ficheiro de campo não traz
# coordenada nenhuma (ver LFM/README_lfmc_pt.md — geocodificar os sítios é
# apontado lá como o pré-requisito em falta), e estas foram atribuídas a
# partir do nome do sítio, ao nível da freguesia/concelho. Só são usadas
# para ir buscar precipitação, que é espacialmente suave (a grelha do
# ERA5 tem 9-31 km), por isso um erro de 1-2 km é irrelevante aqui. NÃO
# servem para extrair índices espectrais — ver o plano.
SITIOS = {
    "Anelhe - Chaves":            (41.70, -7.50),
    "Lamares - Vila Real":        (41.29, -7.80),
    "Granja - Castro Daire":      (40.93, -7.87),
    "Viseu":                      (40.66, -7.91),
    "França - Bragança":          (41.92, -6.75),
    "S.Penha - Portalegre":       (39.32, -7.37),
    "Felgueira - Vale de Cambra": (40.83, -8.35),
    "Arrábida - Setúbal":         (38.47, -8.98),
    "Santarém":                   (39.24, -8.69),
    "Vile - Caminha":             (41.83, -8.79),
}

# grupo do ficheiro de campo -> escalar do motor.
# Pinhais e Eucalipto ficam de fora por razão física, não por falta de
# dados: são folhagem de COPA, e o LiveW_FL de um modelo Rothermel é a
# folhagem viva do leito de SUPERFÍCIE. Giestais são mato mas medidos
# pioram o ajuste do lenhoso (27.5 -> 28.0 de RMSE).
GRUPOS = {
    "herbaceo": ["Herbáceas"],
    "lenhoso": ["Matos atlânticos", "Matos mediterrânicos"],
}

DIAS_P180 = 180


def base(dj: float) -> list[float]:
    """Harmónicas de 2ª ordem no dia do ano."""
    t = 2 * math.pi * dj / 365.0
    return [1.0, math.cos(t), math.sin(t), math.cos(2 * t), math.sin(2 * t)]


def busca_meteo() -> dict:
    """Série diária de precipitação 1991-2022 nos sítios, com cache.

    O arquivo do Open-Meteo devolve 429 depois de 6-7 pedidos seguidos
    (apanhado a fazer isto) — daí o backoff e a gravação incremental.
    """
    import httpx

    out = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    falta = [s for s in SITIOS if s not in out]
    if falta:
        print(f"a buscar precipitação para {len(falta)} sítio(s) (cache em {CACHE.name})")
    for nome in falta:
        lat, lon = SITIOS[nome]
        for tentativa in range(1, 10):
            try:
                r = httpx.get(
                    "https://archive-api.open-meteo.com/v1/archive",
                    params={
                        "latitude": lat, "longitude": lon,
                        "start_date": "1991-01-01", "end_date": "2022-12-31",
                        "daily": "precipitation_sum", "timezone": "Europe/Lisbon",
                    },
                    timeout=180,
                )
                r.raise_for_status()
                out[nome] = r.json()["daily"]
                CACHE.write_text(json.dumps(out))
                print(f"  {nome:<28} {len(out[nome]['time'])} dias")
                break
            except Exception as exc:
                espera = 25 * tentativa
                print(f"  {nome}: {type(exc).__name__} — nova tentativa em {espera}s")
                time.sleep(espera)
        else:
            raise RuntimeError(f"não foi possível obter meteo para {nome}")
        time.sleep(12)
    return out


def carrega_registos(meteo: dict) -> list[dict]:
    """Medições de campo com o P180 já calculado."""
    idx = {(s, t): i for s, d in meteo.items() for i, t in enumerate(d["time"])}
    registos = []
    for r in csv.DictReader(CAMPO.open(encoding="utf-8")):
        sitio, data = r["local_recolha"], r["data"]
        i = idx.get((sitio, data))
        if i is None or i < DIAS_P180:
            continue
        chuva = [x for x in meteo[sitio]["precipitation_sum"][i - DIAS_P180:i] if x is not None]
        if not chuva:
            continue
        registos.append({
            "grupo": r["grupo"], "sitio": sitio, "ano": int(r["ano"]),
            "dj": int(r["dia_juliano"]), "y": float(r["hcv_pct"]),
            "p180": sum(chuva),
        })
    return registos


def ajusta(sub: list[dict]) -> np.ndarray:
    X = np.array([base(d["dj"]) + [d["p180"]] for d in sub])
    return np.linalg.lstsq(X, np.array([d["y"] for d in sub]), rcond=None)[0]


def rmse_cv(sub: list[dict]) -> float:
    """RMSE deixando um ano de fora — o número a reportar.

    Distinto dos coeficientes, que são ajustados a tudo: um serve para
    dizer quanto o modelo erra, o outro para o usar.
    """
    erros = []
    for ano in sorted({d["ano"] for d in sub}):
        treino = [d for d in sub if d["ano"] != ano]
        teste = [d for d in sub if d["ano"] == ano]
        if len(treino) < 40 or not teste:
            continue
        b = ajusta(treino)
        erros += [(float(np.dot(base(d["dj"]) + [d["p180"]], b)) - d["y"]) ** 2 for d in teste]
    return math.sqrt(st.mean(erros))


def janela_util(sub: list[dict], min_por_mes: int = 15) -> tuple[int, int, str]:
    """Intervalo de dia-do-ano em que a curva é usável.

    Fora do intervalo com medições a harmónica extrapola para valores
    impossíveis — o herbáceo, que só tem dados de Abril a Setembro, dá
    −354% em Janeiro. Por isso o intervalo é gravado e respeitado em
    runtime.

    Os dois limites não se tratam da mesma maneira, de propósito:

    - **Início** exige densidade (mês com `min_por_mes` medições). O
      herbáceo tem 2 registos em Abril, ambos de sítio seco, e sozinhos
      arrastam a harmónica para 30% a meio de Abril — o que diria
      herbácea totalmente curada na primavera, contra 106% a meio de
      Maio. Não é monótono nem é credível: 2 pontos não definem o
      arranque da cura.
    - **Fim** aceita a cauda com poucos pontos, porque continua uma
      tendência monótona já estabelecida pelos meses densos. Cortar aqui
      seria pior: Setembro é época de fogos a sério e assumi-lo verde
      estaria errado com certeza.
    """
    por_mes_n = defaultdict(int)
    por_mes_dj = defaultdict(list)
    for d in sub:
        m = datetime.strptime(f"2021-{d['dj']:03d}", "%Y-%j").month
        por_mes_n[m] += 1
        por_mes_dj[m].append(d["dj"])
    densos = sorted(m for m, n in por_mes_n.items() if n >= min_por_mes)
    if not densos:
        raise ValueError(f"nenhum mês com >= {min_por_mes} medições")
    dj_min = min(por_mes_dj[densos[0]])
    dj_max = max(d["dj"] for d in sub)
    nota = (f"inicio no 1o mes com n>={min_por_mes} (meses densos: "
            f"{','.join(str(m) for m in densos)}); fim no ultimo dado")
    return dj_min, dj_max, nota


def valor_fora_janela(sub: list[dict]) -> float:
    """Valor a assumir fora da janela com dados.

    Média do mês mais verde amostrado. Para o herbáceo isso é Maio
    (128.9%, n=21): fora da época de fogos a herbácea portuguesa está
    verde ou ausente, e qualquer valor >=120% satura a fracção curada de
    Andrews 2018 em zero, que é o resultado fisicamente certo. Preferido
    a um número inventado por ser medido.
    """
    por_mes = defaultdict(list)
    for d in sub:
        por_mes[datetime.strptime(f"2021-{d['dj']:03d}", "%Y-%j").month].append(d["y"])
    mes = max(por_mes, key=lambda m: st.mean(por_mes[m]))
    return st.mean(por_mes[mes])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--saida", type=Path, default=DESTINO)
    args = ap.parse_args()

    if not CAMPO.exists():
        print(f"ERRO: não encontrei {CAMPO}", file=sys.stderr)
        return 1

    registos = carrega_registos(busca_meteo())
    print(f"\n{len(registos)} medições com P180 calculável")

    linhas = []
    for escalar, grupos in GRUPOS.items():
        sub = [d for d in registos if d["grupo"] in grupos]
        if len(sub) < 40:
            print(f"ERRO: {escalar} só tem {len(sub)} registos", file=sys.stderr)
            return 1
        b = ajusta(sub)
        dj_min, dj_max, nota = janela_util(sub)
        p180 = [d["p180"] for d in sub]
        linhas.append({
            "escalar": escalar,
            "a0": f"{b[0]:.4f}", "cos1": f"{b[1]:.4f}", "sin1": f"{b[2]:.4f}",
            "cos2": f"{b[3]:.4f}", "sin2": f"{b[4]:.4f}", "beta_p180": f"{b[5]:.6f}",
            "dj_min": dj_min, "dj_max": dj_max,
            "fora_janela_pct": f"{valor_fora_janela(sub):.1f}",
            "p180_min": f"{min(p180):.0f}", "p180_max": f"{max(p180):.0f}",
            "lfmc_min": f"{min(d['y'] for d in sub):.0f}",
            "lfmc_max": f"{max(d['y'] for d in sub):.0f}",
            "n": len(sub), "rmse_cv_pp": f"{rmse_cv(sub):.1f}",
            "grupos": "|".join(grupos), "nota": nota,
        })
        print(f"\n{escalar}: n={len(sub)}  RMSE(CV por ano)={linhas[-1]['rmse_cv_pp']}pp")
        print(f"  DJ {dj_min}-{dj_max}  ({nota})")
        print(f"  fora da janela: {linhas[-1]['fora_janela_pct']}%")
        print(f"  P180 no ajuste: {min(p180):.0f}-{max(p180):.0f}mm")

    args.saida.parent.mkdir(parents=True, exist_ok=True)
    with args.saida.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        w.writeheader()
        w.writerows(linhas)
    print(f"\nescrito {args.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
