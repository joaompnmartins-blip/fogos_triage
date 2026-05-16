# =====================================================================
# API — FastAPI service
# =====================================================================
FROM python:3.12-slim AS base

# Dependências de sistema mínimas (sem GDAL — API não toca em rasters)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcurl4-openssl-dev \
    libssl-dev \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps — só o necessário para a API (sem rasterio/wildfire_ROS_models pesados)
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    asyncpg \
    scikit-learn \
    pydantic

# Copiar código (precisamos do package fogos_triage para fuel_models e schemas)
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e .

COPY services/__init__.py ./services/__init__.py
COPY services/api ./services/api
COPY data /data

# Healthcheck via endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
