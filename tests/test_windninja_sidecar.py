"""
Sidecar WindNinja — `services/windninja/main.py`.

Precisa do `WindNinja_cli` no PATH; sem ele os testes que correm o solver
são saltados (o resto continua a correr). Para o instalar:

    mamba create -y -p ~/.cache/windninja-test/env -c conda-forge windninja
    export PATH=~/.cache/windninja-test/env/bin:$PATH
    export WINDNINJA_DATA=~/.cache/windninja-test/env/share/windninja

    python tests/test_windninja_sidecar.py
"""
import math
import shutil
import sys
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "services" / "windninja"))
sys.path.insert(0, str(RAIZ / "src"))

from main import PedidoVento, health, run  # noqa: E402

TEM_CLI = shutil.which("WindNinja_cli") is not None

passou = falhou = saltou = 0


def check(nome, cond, extra=""):
    global passou, falhou
    print(f"  [{'OK' if cond else 'FAIL'}] {nome}" + (f" — {extra}" if extra and not cond else ""))
    if cond:
        passou += 1
    else:
        falhou += 1


def salta(nome):
    global saltou
    saltou += 1
    print(f"  [SKIP] {nome} — WindNinja_cli não está no PATH")


def terreno_sintetico(n=160, celula=100.0):
    """Uma serra E-W no meio de um domínio plano.

    Sintético e não um recorte do landscape real de propósito: o teste
    tem de correr em CI sem os 3.87 GB do COG, e uma crista isolada torna
    a expectativa física inequívoca — acelera por cima, abriga a
    sotavento.
    """
    y, x = np.mgrid[0:n, 0:n]
    centro = n / 2
    crista = 600.0 * np.exp(-((x - centro) ** 2) / (2 * (n / 12) ** 2))
    dem = (200.0 + crista).astype("float32")
    transform = [celula, 0.0, 0.0, 0.0, -celula, n * celula]
    return dem, transform


def pede(dem, transform, direccao=270.0, velocidade=6.0, malha="coarse"):
    return run(PedidoVento(
        elevacao=dem.tolist(), transform=transform, epsg=3763, nodata=-9999.0,
        input_speed_ms=velocidade, input_dir_deg=direccao,
        mesh=malha, num_threads=1,
    ))


def matriz(resposta, campo):
    a = np.array(getattr(resposta, campo), dtype="float64")
    a[a == resposta.nodata] = np.nan
    return a


def main():
    print("health:")
    h = health()
    check("responde com o nome do binário", h.get("cli") == "WindNinja_cli")
    check("estado reflecte a presença do CLI",
          h.get("status") == ("ok" if TEM_CLI else "sem_windninja"), str(h))

    if not TEM_CLI:
        for n in ("unidades mps e não mph", "campo não-uniforme",
                  "acelera sobre a crista", "abriga a sotavento",
                  "invariância à inversão", "o padrão depende da direcção"):
            salta(n)
        print(f"\n{'='*52}\nRESULTADO: {passou} passados, {falhou} falhados, "
              f"{saltou} saltados\n{'='*52}")
        return 1 if falhou else 0

    dem, tr = terreno_sintetico()
    r = pede(dem, tr)
    vel = matriz(r, "velocidade_ms")

    print("\nunidades — a armadilha que custa 2.24x:")
    # O default de --output_speed_units do WindNinja é mph, mesmo com a
    # entrada em mps. Se alguém tirar a flag do main.py, a média salta de
    # ~6 para ~13 e o fogo passa a propagar ao dobro, sem erro nenhum.
    media = np.nanmean(vel)
    check(f"média perto da entrada de 6 m/s (deu {media:.2f})", 4.0 < media < 8.0)
    check(f"NÃO está em mph (mph daria ~{6*2.2369:.1f})", media < 10.0, f"{media:.2f}")

    print("\nfísica do campo:")
    check(f"não-uniforme (dp {np.nanstd(vel):.2f} m/s)", np.nanstd(vel) > 0.3)
    check("sem valores negativos", np.nanmin(vel) >= 0.0)

    # Crista a meio, vento de oeste (270°): o topo acelera, o flanco
    # nascente (sotavento) abriga.
    n = vel.shape[1]
    topo = vel[:, int(n * 0.45):int(n * 0.55)]
    sotavento = vel[:, int(n * 0.62):int(n * 0.78)]
    barlavento = vel[:, int(n * 0.22):int(n * 0.38)]
    check(f"acelera sobre a crista ({np.nanmean(topo):.2f} > {np.nanmean(barlavento):.2f})",
          np.nanmean(topo) > np.nanmean(barlavento))
    check(f"abriga a sotavento ({np.nanmean(sotavento):.2f} < {np.nanmean(topo):.2f})",
          np.nanmean(sotavento) < np.nanmean(topo))

    print("\ninvariância à inversão — propriedade exacta, não bug:")
    # O solver mass-consistent minimiza o desvio face ao campo inicial
    # sujeito a divergência nula. O problema é LINEAR: inverter a entrada
    # inverte a solução e deixa o MÓDULO inalterado. Logo 270° e 90° dão
    # velocidades bit a bit iguais, e só a direcção roda 180°.
    #
    # Confirmado também no terreno real (Gerês): |dif| máxima 0.000000 m/s.
    # Está aqui como teste para ninguém voltar a lê-lo como avaria — foi
    # exactamente assim que este teste falhou da primeira vez, por ter
    # escolhido o único par de direcções onde não há diferença nenhuma.
    v_oposto = matriz(pede(dem, tr, direccao=90.0), "velocidade_ms")
    difmax = np.nanmax(np.abs(v_oposto - vel))
    check(f"270° e 90° dão a MESMA velocidade (|dif| máx {difmax:.6f})", difmax < 1e-6)

    print("\ndependência da direcção — é o que obriga a uma corrida por hora:")
    # 45° e não 180°: a 180° a invariância acima garante campos iguais.
    v45 = matriz(pede(dem, tr, direccao=225.0), "velocidade_ms")
    ok = ~np.isnan(vel) & ~np.isnan(v45)
    r_dir = np.corrcoef(vel[ok], v45[ok])[0, 1]
    difmed = np.nanstd(v45 - vel)
    check(f"45° de rotação muda o campo (r={r_dir:+.3f}, dp da dif {difmed:.2f} m/s)",
          r_dir < 0.99 and difmed > 0.05)

    print("\ncontrato da resposta:")
    check("dimensões coerentes", vel.shape == (r.altura, r.largura))
    check("transform com 6 elementos", len(r.transform) == 6)
    check("célula de saída positiva", r.transform[0] > 0)
    check("direcção dentro de 0-360",
          np.nanmin(matriz(r, "direccao_deg")) >= 0 and np.nanmax(matriz(r, "direccao_deg")) <= 360)
    check(f"reporta o tempo ({r.segundos}s)", r.segundos > 0)

    print(f"\n{'='*52}\nRESULTADO: {passou} passados, {falhou} falhados, "
          f"{saltou} saltados\n{'='*52}")
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
