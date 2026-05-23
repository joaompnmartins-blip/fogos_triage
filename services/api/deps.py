"""
Configuração, autenticação e injecção de dependências da API.
"""
from __future__ import annotations

import os
from typing import Optional

import asyncpg
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


class APIConfig:
    """Configuração lida de env vars."""
    def __init__(self):
        self.database_url = os.environ["DATABASE_URL"]
        # API keys separadas por vírgula
        keys = os.environ.get("API_KEYS", "")
        self.api_keys = {k.strip() for k in keys.split(",") if k.strip()}
        # CORS — vírgulas-separados, "*" permite tudo (apenas em dev)
        origins = os.environ.get("ALLOWED_ORIGINS", "*")
        self.allowed_origins = (
            ["*"] if origins.strip() == "*"
            else [o.strip() for o in origins.split(",") if o.strip()]
        )
        self.version = os.environ.get("API_VERSION", "0.3.0")
        # Em dev, podemos desligar auth para testes rápidos
        self.require_auth = os.environ.get("REQUIRE_AUTH", "true").lower() == "true"
        self.landscape_dir = os.getenv("LANDSCAPE_DIR", "data/landscape")

    def is_dev_mode(self) -> bool:
        return os.environ.get("DEV_MODE", "false").lower() == "true"


_config: Optional[APIConfig] = None


def get_config() -> APIConfig:
    global _config
    if _config is None:
        _config = APIConfig()
    return _config


# ---------------------------------------------------------------------------
# Pool de Postgres
# ---------------------------------------------------------------------------
# O pool é criado no lifespan da app (ver services/api/main.py) e guardado
# em app.state.pool. As rotas acedem via Depends(get_pool).


async def get_pool(request: Request) -> asyncpg.Pool:
    """
    Dependency: devolve o pool a partir do state da aplicação.

    O pool é criado no lifespan e guardado em app.state.pool.
    Lemos via request.app.state — sempre acessível, sem middleware.
    """
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Pool de base de dados não inicializado",
        )
    return pool


# ---------------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------------


_bearer = HTTPBearer(auto_error=False)


async def require_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    config: APIConfig = Depends(get_config),
) -> str:
    """
    Valida o token Bearer contra a lista de API keys.
    Retorna o token autenticado (para logging).

    Pode ser desativado em dev via REQUIRE_AUTH=false.
    """
    if not config.require_auth:
        return "dev"

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key requerida (header: Authorization: Bearer <key>)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not config.api_keys:
        # Sem keys configuradas mas auth obrigatória — má configuração
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key validation indisponível (API_KEYS não configurada)",
        )

    if credentials.credentials not in config.api_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key inválida",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return credentials.credentials
