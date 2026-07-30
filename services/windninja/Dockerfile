# =====================================================================
# Sidecar WindNinja — campo de vento ajustado ao relevo
# =====================================================================
# Base conda-forge e não python:3.12-slim como os outros serviços: o
# WindNinja não existe em pip nem em apt, só em conda-forge. É essa a
# razão de ser deste container separado — ver WINDNINJA_PLAN.md.
#
# Sem volume e sem credenciais: recebe a janela do DEM no pedido HTTP.
# No Railway "each service can only have a single volume" e os volumes
# não se partilham, portanto ler o landscape do volume da API não é
# possível.
# =====================================================================
FROM condaforge/miniforge3:24.9.2-0

WORKDIR /app

# `windninja` traz o GDAL e o rasterio por dependência; fastapi/uvicorn
# vêm do mesmo canal para não misturar dois gestores de pacotes no
# mesmo ambiente.
RUN mamba install -y -c conda-forge \
        windninja \
        fastapi \
        uvicorn-standard \
        rasterio \
        numpy \
    && mamba clean -afy

# O WindNinja precisa de encontrar os seus dados (tabelas de rugosidade,
# etc.). No layout do conda ficam em share/windninja.
ENV WINDNINJA_DATA=/opt/conda/share/windninja \
    PYTHONUNBUFFERED=1

COPY services/windninja/main.py ./main.py

EXPOSE 8080

# Um worker só: cada corrida do WindNinja é CPU-bound e usa até 255 MB;
# vários workers em paralelo multiplicariam o pico de memória sem ganho,
# porque o chamador já serializa as corridas (ver fetch_wind_fields).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
