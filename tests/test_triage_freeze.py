"""
Congelamento da triagem — OccurrenceRepository.needs_triage.

Não precisa de Postgres: usa um pool falso que devolve a linha que o
teste quiser. O que se testa é a política de decisão, não o SQL.

    python tests/test_triage_freeze.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fogos_triage.db.repository import (  # noqa: E402
    TRIAGE_MOVE_TOLERANCE_M, OccurrenceRepository, _distance_m,
)


class _FakeConn:
    def __init__(self, row):
        self._row = row

    async def fetchrow(self, *args, **kwargs):
        return self._row


class _FakeAcquire:
    def __init__(self, row):
        self._row = row

    async def __aenter__(self):
        return _FakeConn(self._row)

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    """Pool mínimo: `async with pool.acquire() as conn`."""
    def __init__(self, row):
        self._row = row

    def acquire(self):
        return _FakeAcquire(self._row)


def repo_com(row):
    r = OccurrenceRepository.__new__(OccurrenceRepository)  # sem __init__ (exige asyncpg)
    r.pool = _FakePool(row)
    return r


LAT, LON = 41.636695, -7.33691

passou = falhou = 0


def check(nome, obtido, esperado):
    global passou, falhou
    ok = obtido == esperado
    print(f"  [{'OK' if ok else 'FAIL'}] {nome}" + ("" if ok else f" (obtido {obtido}, esperado {esperado})"))
    if ok:
        passou += 1
    else:
        falhou += 1


def main():
    print("needs_triage:")

    # nunca triada -> tem de triar
    check("sem triagem anterior -> True",
          asyncio.run(repo_com(None).needs_triage("x", LAT, LON)), True)

    # triada na mesma coordenada -> congelada
    check("mesma coordenada -> False",
          asyncio.run(repo_com({"latitude": LAT, "longitude": LON}).needs_triage("x", LAT, LON)),
          False)

    # deslocação pequena (~20 m) -> continua congelada
    lat_perto = LAT + 20 / 111_320
    check("deslocada ~20m -> False",
          asyncio.run(repo_com({"latitude": LAT, "longitude": LON}).needs_triage("x", lat_perto, LON)),
          False)

    # deslocação grande (~500 m) -> retriar
    lat_longe = LAT + 500 / 111_320
    check("deslocada ~500m -> True",
          asyncio.run(repo_com({"latitude": LAT, "longitude": LON}).needs_triage("x", lat_longe, LON)),
          True)

    # triagem anterior à migração 006 (sem coordenada) -> não retriar,
    # senão o deploy desta alteração retriava tudo o que está activo
    check("coordenada nula (pré-006) -> False",
          asyncio.run(repo_com({"latitude": None, "longitude": None}).needs_triage("x", LAT, LON)),
          False)

    print("\n_distance_m:")
    d = _distance_m(LAT, LON, LAT + 1 / 111_320, LON)
    check(f"1/111320 grau de latitude ~ 1m (deu {d:.3f}m)", abs(d - 1.0) < 0.05, True)
    d2 = _distance_m(LAT, LON, LAT, LON + 1 / 111_320)
    esperado = 1.0 * __import__("math").cos(__import__("math").radians(LAT))
    check(f"mesmo delta em longitude encurta com o cosseno (deu {d2:.3f}m)",
          abs(d2 - esperado) < 0.05, True)
    check(f"tolerância é {TRIAGE_MOVE_TOLERANCE_M}m", TRIAGE_MOVE_TOLERANCE_M > 0, True)

    print(f"\n{'='*40}\nRESULTADO: {passou} passados, {falhou} falhados\n{'='*40}")
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
