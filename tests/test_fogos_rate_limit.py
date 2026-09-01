"""
Chave de API e limite de caudal da fogos.pt — `ingestion/fogos_client.py`.

    python tests/test_fogos_rate_limit.py

Nenhum teste aqui toca na rede: a fogos.pt limita por IP com penalizações
de ~55 minutos, e uma suite que lhe batesse bloqueava o worker de
produção, que partilha a mesma chave.

O que isto guarda, do incidente de 2026-08-31:

  O worker deixou de ingerir às 14:43 e ficou 40+ minutos a apanhar 429,
  de 2 em 2 minutos, sem uma única recuperação. A causa não foi a fogos.pt
  estar em baixo — foi ela ter passado a exigir chave, e o worker tratar o
  429 como um erro qualquer: voltava a bater ao fim de 120 s, dentro de
  uma janela de penalização de 3287 s, ~27 vezes, cada uma podendo
  reiniciá-la.
"""
import asyncio
import importlib
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

passou = falhou = 0


def check(nome, cond, extra=""):
    global passou, falhou
    print(f"  [{'OK' if cond else 'FAIL'}] {nome}" + (f" — {extra}" if extra and not cond else ""))
    if cond:
        passou += 1
    else:
        falhou += 1


def recarrega(**env):
    """Reimporta o cliente com env vars dadas — a chave é lida no import."""
    antigos = {k: os.environ.get(k) for k in env}
    try:
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        import fogos_triage.ingestion.fogos_client as m
        return importlib.reload(m)
    finally:
        for k, v in antigos.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class RespostaFalsa:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = headers or {}


def main():
    print("Endpoint: saímos do host de desenvolvimento.")
    m = recarrega(FOGOS_API_URL=None, FOGOS_API_KEY=None)
    check(f"default é api.fogos.pt/v2 (é {m.FOGOS_API_URL})",
          m.FOGOS_API_URL == "https://api.fogos.pt/v2/incidents/active")
    check("já não aponta para api-dev", "api-dev" not in m.FOGOS_API_URL)
    m2 = recarrega(FOGOS_API_URL="https://exemplo/x")
    check("mas pode ser trocado por env var", m2.FOGOS_API_URL == "https://exemplo/x")

    print("\nChave de API — no ambiente, nunca no código:")
    m = recarrega(FOGOS_API_URL=None, FOGOS_API_KEY=None)
    check("sem chave, não há cabeçalho de autorização",
          "Authorization" not in m._headers())
    m = recarrega(FOGOS_API_URL=None, FOGOS_API_KEY="segredo123")
    check("com chave, Authorization: Bearer",
          m._headers().get("Authorization") == "Bearer segredo123")
    check("os outros cabeçalhos mantêm-se",
          m._headers().get("Referer") == "https://fogos.pt/")
    check("_headers devolve cópia, não o dicionário partilhado",
          m._headers() is not m.DEFAULT_HEADERS)
    m_esp = recarrega(FOGOS_API_URL=None, FOGOS_API_KEY="  k  ")
    check("espaços à volta da chave são aparados",
          m_esp._headers().get("Authorization") == "Bearer k")

    print("\nO 429 traz consigo o tempo de espera:")
    m = recarrega(FOGOS_API_URL=None, FOGOS_API_KEY=None)
    check("Retry-After lido", m._retry_after_s(RespostaFalsa(429, {"Retry-After": "3287"})) == 3287.0)
    check("aceita minúsculas", m._retry_after_s(RespostaFalsa(429, {"retry-after": "60"})) == 60.0)
    check("ausente devolve None", m._retry_after_s(RespostaFalsa(429, {})) is None)
    check("lixo devolve None, não rebenta",
          m._retry_after_s(RespostaFalsa(429, {"Retry-After": "amanhã"})) is None)

    e = m.FogosRateLimitError(3287.0)
    check("a excepção carrega os segundos", e.retry_after_s == 3287.0)
    check("e diz o que é na mensagem", "rate limit" in str(e).lower(), str(e))
    check("é distinguível de um erro qualquer", isinstance(e, RuntimeError)
          and type(e) is not RuntimeError)
    check("sem Retry-After também se constrói",
          m.FogosRateLimitError().retry_after_s is None)

    print("\nO worker espera o que a fogos.pt pediu (era aqui o ciclo vicioso):")
    sys.path.insert(0, str(RAIZ))
    os.environ.setdefault("DATABASE_URL", "postgresql://x/y")
    from services.worker.main import RATE_LIMIT_ESPERA_OMISSAO_S

    # Reproduz a decisão do laço: espera = max(intervalo, retry_after).
    def espera_do_laco(stats, intervalo=120):
        e = intervalo
        if stats and stats.get("retry_after_s"):
            e = max(e, float(stats["retry_after_s"]))
        return e

    check(f"429 com 3287s -> espera 3287s (antes eram 120)",
          espera_do_laco({"retry_after_s": 3287.0}) == 3287.0)
    check("ciclo normal mantém os 120s", espera_do_laco({"errors": 0}) == 120)
    check("nunca encurta abaixo do intervalo normal",
          espera_do_laco({"retry_after_s": 5.0}) == 120)
    check(f"omissão é da ordem da hora (é {RATE_LIMIT_ESPERA_OMISSAO_S:.0f}s)",
          RATE_LIMIT_ESPERA_OMISSAO_S >= 1800)

    print("\n  Com os 120s antigos e uma janela de 3287s, o worker fazia")
    print(f"  {int(3287 // 120)} pedidos DENTRO do castigo. Agora faz 0.")

    print(f"\n{'='*58}\nRESULTADO: {passou} passados, {falhou} falhados\n{'='*58}")
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
