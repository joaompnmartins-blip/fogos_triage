"""
Aplicação FastAPI principal.

Composição: lifespan que cria pool Postgres → routers → CORS.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .deps import get_config
from fogos_triage.db.repository import _init_connection
from fogos_triage.landscape import ensure_landscape

log = logging.getLogger(__name__)
from .routes_fires import router as fires_router
from .routes_freesim import router_free_jobs, router_free_sim
from .routes_meta import (
    router_fuels,
    router_health,
    router_jobs,
    router_sim,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle da aplicação: cria pool no arranque, fecha à saída."""
    config = get_config()

    # Pre-aquecer landscape no arranque se R2 estiver configurado.
    # Falha não-fatal: o download será tentado de novo em cada pedido de simulação.
    if config.landscape_dir and config.r2_account_id:
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: ensure_landscape(
                    landscape_dir=config.landscape_dir,
                    r2_account_id=config.r2_account_id,
                    r2_access_key_id=config.r2_access_key_id,
                    r2_secret_access_key=config.r2_secret_access_key,
                    r2_bucket=config.r2_bucket,
                    r2_prefix=config.r2_prefix,
                ),
            )
            log.info("Landscape pré-carregada com sucesso no arranque da API")
        except Exception as exc:
            log.error("Landscape download falhou no arranque: %s — será tentado ao simular", exc)

    # init_pool regista codecs JSON/JSONB — essencial para que as colunas
    # scenarios_json (triage_results) e result_json (simulation_jobs)
    # venham desserializadas como list/dict e não como string.
    pool = await asyncpg.create_pool(
        config.database_url,
        min_size=2,
        max_size=10,
        command_timeout=30,
        init=_init_connection,
    )

    app.state.pool = pool
    app.state.config = config

    try:
        yield
    finally:
        await pool.close()


def create_app() -> FastAPI:
    """Factory function — facilita testes."""
    config = get_config()

    app = FastAPI(
        title="fogos_triage API",
        version=config.version,
        description=(
            "API operacional de triagem de fogos para Portugal. "
            "Consome a fogos.pt e a Landscape File PT, produz priorização "
            "P1-P4 baseada em Rothermel-Andrews 2018, Byram, Van Wagner."
        ),
        lifespan=lifespan,
    )

    # CORS — allow_credentials deve ser False quando allow_origins=["*"].
    # Bearer tokens não são "credentials" no sentido CORS (cookies/HTTP auth);
    # com credentials=True o Starlette recusa-se a enviar headers CORS com wildcard.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # Error handler genérico — não vazar stack traces para o cliente
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        import logging
        logging.exception(f"Erro não tratado em {request.url.path}: {exc}")
        return JSONResponse(
            status_code=500,
            content={"detail": "Erro interno do servidor"},
        )

    # Routers
    app.include_router(fires_router)
    app.include_router(router_fuels)
    app.include_router(router_sim)
    app.include_router(router_jobs)
    app.include_router(router_free_sim)
    app.include_router(router_free_jobs)
    app.include_router(router_health)

    return app


# Para uvicorn:  uvicorn services.api.main:app --reload
app = create_app()
