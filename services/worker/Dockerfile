# =====================================================================
# Worker — polling fogos.pt + ingestão + triagem
# =====================================================================
FROM python:3.12-slim AS base

# Dependências do sistema para rasterio (GDAL) e curl_cffi (libcurl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev \
    gdal-bin \
    libcurl4-openssl-dev \
    libssl-dev \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependências Python
COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir \
    asyncpg \
    httpx \
    curl_cffi \
    rasterio \
    scikit-learn \
    boto3 \
    earthengine-api \
    git+https://github.com/forefireAPI/wildfire_ROS_models.git \
    && pip install --no-cache-dir -e .

# Worker script (incluindo services/__init__.py para o package)
COPY services/__init__.py ./services/__init__.py
COPY services/worker ./services/worker
COPY migrations ./migrations

# Modelos de combustível PT (montados ou copiados conforme caso)
COPY data /data

# Healthcheck: o worker escreve /tmp/worker_alive a cada ciclo.
# Consideramos vivo se o ficheiro foi modificado nos últimos 5 minutos
# (suficiente para 2 ciclos de polling a 120s).
HEALTHCHECK --interval=60s --timeout=10s --start-period=40s --retries=3 \
    CMD test -n "$(find /tmp/worker_alive -mmin -5 2>/dev/null)" || exit 1

# Comando default
CMD ["python", "-m", "services.worker.main"]
